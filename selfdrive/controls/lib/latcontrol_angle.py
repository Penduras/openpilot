import math

from cereal import log
from openpilot.selfdrive.controls.lib.latcontrol import LatControl

# TODO This is speed dependent
STEER_ANGLE_SATURATION_THRESHOLD = 2.5  # Degrees

# xnor: on angle-controlled cars (Tesla) the EPAS actively servos toward whatever
# angle we command, so a driver override means physically fighting that target the
# whole time it's held. Blend the commanded angle to the driver's actual angle while
# they're overriding (so the car stops pushing back), then ease back to the model's
# target over this many seconds after they let go, instead of snapping back instantly.
OVERRIDE_RELEASE_TAU = 0.5  # seconds


class LatControlAngle(LatControl):
  def __init__(self, CP, CI, dt):
    super().__init__(CP, CI, dt)
    self.sat_check_min_speed = 5.
    self.use_steer_limited_by_safety = CP.brand == "tesla"
    self.override_blend = 0.0  # 0 = fully model-commanded, 1 = fully following driver's angle

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, curvature_limited, lat_delay):
    angle_log = log.ControlsState.LateralAngleState.new_message()

    if not active:
      angle_log.active = False
      angle_steers_des = float(CS.steeringAngleDeg)
      self.override_blend = 0.0
    else:
      angle_log.active = True
      model_angle_des = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
      model_angle_des += params.angleOffsetDeg

      if CS.steeringPressed:
        self.override_blend = 1.0
      else:
        self.override_blend = max(0.0, self.override_blend - self.dt / OVERRIDE_RELEASE_TAU)

      angle_steers_des = self.override_blend * CS.steeringAngleDeg + (1.0 - self.override_blend) * model_angle_des

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
