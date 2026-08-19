import math

from openpilot.cereal import log
from openpilot.selfdrive.controls.lib.latcontrol import LatControl

# TODO This is speed dependent
STEER_ANGLE_SATURATION_THRESHOLD = 2.5  # Degrees

# xnor: on angle-controlled cars (Tesla) the EPAS actively servos toward whatever
# angle we command, so a driver override means physically fighting that target the
# whole time it's held. Blend the commanded angle to the driver's actual angle while
# they're overriding (so the car stops pushing back), then ease back to the model's
# target over this many seconds after they let go, instead of snapping back instantly.
OVERRIDE_RELEASE_TAU = 0.5  # seconds

# xnor: 2026-08-16 - override_blend used to jump straight to 1.0 the instant
# steeringPressed went true, only the release side was eased. That's fine in isolation,
# but mid-corner the model's desired angle and the driver's actual angle can already
# differ by a lot, so an instant blend snap can itself be a big one-tick jump in the
# *commanded* angle - enough to trip panda's own steer_angle_cmd_checks() rate-of-change
# limit (opendbc/safety/lateral.h) and hard-fault the EPAS (steerFault -> SOFT_DISABLE
# "TAKE CONTROL IMMEDIATELY", see mads.py's comment on that same alert). Confirmed live:
# hit on a slight corner with a plausibly-flickery grip (talking while driving). Ramping
# the engage side too (faster than release, since a genuine deliberate override should
# still feel near-immediate) spreads that transition over several ticks instead of one,
# without touching the hard disengage path itself - same as the original design intent.
OVERRIDE_ENGAGE_TAU = 0.1  # seconds

# xnor: 2026-08-19 - Tesla-only "cooperative steering" light-touch nudge, for corrective
# torque below the steeringPressed threshold (1.0 Nm on Tesla - opendbc/car/tesla/values.py
# STEER_THRESHOLD; not imported here since this file is shared across brands, so
# COOP_STEER_FULL_NM below is a self-contained approximation of that scale, not a hard
# link to it). Below that threshold nothing happened at all before this: a light nudge to
# correct the model's line either did nothing or had to be pushed hard enough to trigger a
# full override_blend takeover. Idea from sunnypilot's community "cooperative steering"
# work (dzid26/sunnypilot, branch vtb-sla, opendbc/sunnypilot/car/tesla/coop_steering.py) -
# NOT a direct port. That code depends on a `control_type` passthrough (control_type==2,
# "LANE_KEEP_ASSIST") that this car's actual safety mode never exposes (confirmed against
# our own opendbc_repo submodule - tesla_legacy.h's tx_hook only accepts control_type
# 0/NONE or 1/ANGLE_CONTROL for anything openpilot sends). Community member Nitrotito hit
# the same wall on a legacy-CAN HW1 car and worked around it the way this does: convert
# torque into an angle offset added before the existing angle-rate limiter, riding through
# the same ANGLE_CONTROL path unchanged instead of needing a new control type panda would
# reject.
#
# Deliberately conservative and NOT live-verified yet (built and validated offline only,
# 2026-08-19) - needs a real drive to confirm both the feel/tuning AND the sign convention
# (steeringTorque and steeringAngleDeg are both raw EPAS signals negated the same way in
# carstate.py, and desire_helper.py already trusts steeringTorque's sign for lane-change
# intent, so this should be directionally consistent - but that's inference from code, not
# confirmed on the road).
COOP_STEER_DEADZONE_NM = 0.3  # Nm - filters steering-wheel weight/bias noise, similar scale
                               # to dzid26's own 0.5 Nm deadzone
COOP_STEER_FULL_NM = 1.0  # Nm - torque at which the nudge reaches its own max offset; chosen
                           # to roughly hand off to the full override_blend takeover around
                           # where steeringPressed itself triggers, not imported as a hard link
COOP_STEER_MAX_LAT_ACCEL = 1.5  # m/s^2 - deliberately gentler than the ~3.6 m/s^2 ISO/panda
                                 # ceiling other code in this stack uses - a light-touch nudge,
                                 # not a takeover
COOP_STEER_OFFSET_RATE = 30.  # deg/s - max rate the offset itself may change, independent of
                               # how fast the driver's torque itself changes, so a sudden
                               # torque spike can't produce a one-tick jump in commanded angle

# xnor: 2026-08-19 - found via rlog replay of the first test drive (see
# xnor-openpilot-slc-architecture memory for the full analysis): a large residual offset left
# over from an earlier correction could linger for close to a second unwinding at
# COOP_STEER_OFFSET_RATE while the driver had already applied real, deadzone-exceeding torque
# in the opposite direction - worst observed case was a -25.5deg offset still fighting a fresh
# +0.46 Nm reversal. A real sign reversal in the driver's own torque is an unambiguous "I want
# the opposite direction now" signal, so it doesn't need the same conservative rate a fresh
# same-direction nudge does - allow unwinding substantially faster in that specific case, still
# rate-limited (not an instant snap) and well under panda's own ~250 deg/s EPS-fault ceiling.
COOP_STEER_UNWIND_RATE = 150.  # deg/s - only applied when the driver's current (deadzone-
                                # filtered) torque actively opposes the sign of the offset we're
                                # currently holding


class LatControlAngle(LatControl):
  def __init__(self, CP, CI, dt):
    super().__init__(CP, CI, dt)
    self.sat_check_min_speed = 5.
    self.use_steer_limited_by_safety = CP.brand in ("tesla", "hyundai")
    self.is_tesla = CP.brand == "tesla"
    self.override_blend = 0.0  # 0 = fully model-commanded, 1 = fully following driver's angle
    self.coop_steer_offset = 0.0  # deg - Tesla-only light-touch torque nudge, see constants above

  def _update_coop_steer_offset(self, CS, VM) -> float:
    """Light-touch torque-proportional angle nudge for corrective input below a full
    override, fading out as override_blend ramps in so the handoff stays smooth."""
    torque = CS.steeringTorque
    driver_torque_dz = math.copysign(max(0., abs(torque) - COOP_STEER_DEADZONE_NM), torque)

    v_ego_raw = max(CS.vEgo, 1.)
    max_curvature = COOP_STEER_MAX_LAT_ACCEL / (v_ego_raw ** 2)
    max_offset = abs(math.degrees(VM.get_steer_from_curvature(max_curvature, CS.vEgo, 0.)))

    torque_range = COOP_STEER_FULL_NM - COOP_STEER_DEADZONE_NM
    ratio = 0. if torque_range <= 0 else max(-1., min(1., driver_torque_dz / torque_range))
    target_offset = ratio * max_offset * (1.0 - self.override_blend)

    # real driver torque actively opposing the offset we're currently holding is an unambiguous
    # "the opposite direction now" signal - unwind faster than a fresh same-direction nudge
    opposing = self.coop_steer_offset != 0. and driver_torque_dz * self.coop_steer_offset < 0.
    rate = COOP_STEER_UNWIND_RATE if opposing else COOP_STEER_OFFSET_RATE
    max_delta = rate * self.dt
    return max(self.coop_steer_offset - max_delta, min(self.coop_steer_offset + max_delta, target_offset))

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, curvature_limited, lat_delay):
    angle_log = log.ControlsState.LateralAngleState.new_message()

    if not active:
      angle_log.active = False
      angle_steers_des = float(CS.steeringAngleDeg)
      self.override_blend = 0.0
      self.coop_steer_offset = 0.0
    else:
      angle_log.active = True
      model_angle_des = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
      model_angle_des += params.angleOffsetDeg

      if CS.steeringPressed:
        self.override_blend = min(1.0, self.override_blend + self.dt / OVERRIDE_ENGAGE_TAU)
      else:
        self.override_blend = max(0.0, self.override_blend - self.dt / OVERRIDE_RELEASE_TAU)

      self.coop_steer_offset = self._update_coop_steer_offset(CS, VM) if self.is_tesla else 0.0

      angle_steers_des = self.override_blend * CS.steeringAngleDeg + \
                          (1.0 - self.override_blend) * (model_angle_des + self.coop_steer_offset)

    if self.use_steer_limited_by_safety:
      # these cars' carcontrollers calculate max lateral accel and jerk, so we can rely on carOutput for saturation
      angle_control_saturated = steer_limited_by_safety
    else:
      # for cars which use a method of limiting torque such as a torque signal (Nissan and Toyota)
      # or relying on EPS (Ford Q3), carOutput does not capture maxing out torque  # TODO: this can be improved
      angle_control_saturated = abs(angle_steers_des - CS.steeringAngleDeg) > STEER_ANGLE_SATURATION_THRESHOLD
    angle_log.saturated = bool(self._check_saturation(angle_control_saturated, CS, False, curvature_limited))
    angle_log.steeringAngleDeg = float(CS.steeringAngleDeg)
    angle_log.steeringAngleDesiredDeg = angle_steers_des
    return 0, float(angle_steers_des), angle_log
