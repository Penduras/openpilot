import time

from cereal import custom, car, log
from openpilot.common.params import Params
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL

# xnor: ported from sunnypilot's SpeedLimitAssist, trimmed to the "non_pcm_long" state-machine
# branch only. Tesla (with openpilotLongitudinalControl) commands accel/brake directly over CAN
# rather than emulating stalk button presses to move a stock PCM's max set speed, so sunnypilot's
# other branch (update_state_machine_pcm_op_long, with its pending/adapting states) doesn't apply
# here - this car only ever needs {disabled, inactive, preActive, active}.
#
# Per xnor: full auto-adjust is enabled, but a new/lower speed limit still requires the driver to
# either dial the cruise speed to match, or tap a cruise button once in the confirming direction
# while the preActive prompt is showing - it never silently changes your set speed on its own.

ButtonType = car.CarState.ButtonEvent.Type
EventName = log.OnroadEvent.EventName
AssistState = custom.LongitudinalPlanSP.SpeedLimit.AssistState

ACTIVE_STATES = (AssistState.active,)
ENABLED_STATES = (AssistState.preActive, *ACTIVE_STATES)

DISABLED_GUARD_PERIOD = 0.5  # secs.
PRE_ACTIVE_GUARD_PERIOD = 5  # secs. Time to wait after showing the preActive prompt before giving up.

CONFIRM_SPEED_THRESHOLD = {
  True: 80,   # km/h
  False: 50,  # mph
}

V_CRUISE_UNSET = 255.

CRUISE_BUTTONS_PLUS = (ButtonType.accelCruise, ButtonType.resumeCruise)
CRUISE_BUTTONS_MINUS = (ButtonType.decelCruise, ButtonType.setCruise)
CRUISE_BUTTON_CONFIRM_HOLD = 0.5  # secs.


def compare_cluster_target(v_cruise_cluster: float, target_set_speed: float, is_metric: bool) -> tuple[bool, bool]:
  speed_conv = CV.MS_TO_KPH if is_metric else CV.MS_TO_MPH
  v_cruise_cluster_conv = round(v_cruise_cluster * speed_conv)
  target_set_speed_conv = round(target_set_speed * speed_conv)

  req_plus = v_cruise_cluster_conv < target_set_speed_conv
  req_minus = v_cruise_cluster_conv > target_set_speed_conv
  return req_plus, req_minus


class SpeedLimitAssist:
  def __init__(self):
    self.params = Params()
    self.frame = -1
    self.long_engaged_timer = 0
    self.pre_active_timer = 0
    self.is_metric = self.params.get_bool("IsMetric")
    self.enabled = self.params.get_bool("SpeedLimitControl")
    self.long_enabled = False
    self.long_enabled_prev = False
    self.is_enabled = False
    self.is_active = False
    self.output_v_target = V_CRUISE_UNSET
    self.output_a_target = 0.
    self.v_ego = 0.
    self.a_ego = 0.
    self.v_offset = 0.
    self.target_set_speed_conv = 0
    self.prev_target_set_speed_conv = 0
    self.v_cruise_cluster = 0.
    self.v_cruise_cluster_prev = 0.
    self.v_cruise_cluster_conv = 0
    self.prev_v_cruise_cluster_conv = 0
    self._has_speed_limit = False
    self._speed_limit = 0.
    self._speed_limit_final_last = 0.
    self.speed_limit_prev = 0.
    self._distance = 0.
    self.state = AssistState.disabled
    self._state_prev = AssistState.disabled

    self._plus_hold = 0.
    self._minus_hold = 0.

    self.new_events: list = []

  @property
  def speed_limit_changed(self) -> bool:
    return self._has_speed_limit and bool(self._speed_limit != self.speed_limit_prev)

  @property
  def v_cruise_cluster_changed(self) -> bool:
    return bool(self.v_cruise_cluster_conv != self.prev_v_cruise_cluster_conv)

  @property
  def target_set_speed_confirmed(self) -> bool:
    return bool(self.v_cruise_cluster_conv == self.target_set_speed_conv)

  @property
  def v_cruise_cluster_below_confirm_speed_threshold(self) -> bool:
    return bool(self.v_cruise_cluster_conv < CONFIRM_SPEED_THRESHOLD[self.is_metric])

  @property
  def apply_confirm_speed_threshold(self) -> bool:
    if self.v_cruise_cluster_below_confirm_speed_threshold:
      return True
    return bool(self.target_set_speed_conv < CONFIRM_SPEED_THRESHOLD[self.is_metric])

  def get_v_target_from_control(self) -> float:
    if self._has_speed_limit and self.is_active:
      return self._speed_limit_final_last
    return V_CRUISE_UNSET

  def get_a_target_from_control(self) -> float:
    return self.a_ego

  def update_params(self) -> None:
    self.is_metric = self.params.get_bool("IsMetric")
    self.enabled = self.params.get_bool("SpeedLimitControl")

  def update_car_state(self, CS: car.CarState) -> None:
    now = time.monotonic()
    for b in CS.buttonEvents:
      if not b.pressed:
        if b.type in CRUISE_BUTTONS_PLUS:
          self._plus_hold = max(self._plus_hold, now + CRUISE_BUTTON_CONFIRM_HOLD)
        elif b.type in CRUISE_BUTTONS_MINUS:
          self._minus_hold = max(self._minus_hold, now + CRUISE_BUTTON_CONFIRM_HOLD)

  def _get_button_release(self, req_plus: bool, req_minus: bool) -> bool:
    now = time.monotonic()
    confirmed = (req_plus and now <= self._plus_hold) or (req_minus and now <= self._minus_hold)
    if confirmed:
      self._plus_hold = 0.
      self._minus_hold = 0.
      return True

    if now > self._plus_hold:
      self._plus_hold = 0.
    if now > self._minus_hold:
      self._minus_hold = 0.
    return False

  def update_calculations(self, v_cruise_cluster: float) -> None:
    speed_conv = CV.MS_TO_KPH if self.is_metric else CV.MS_TO_MPH
    self.v_cruise_cluster = v_cruise_cluster
    self.v_offset = self._speed_limit_final_last - self.v_ego

    self.target_set_speed_conv = round(self._speed_limit_final_last * speed_conv)
    self.v_cruise_cluster_conv = round(self.v_cruise_cluster * speed_conv)

  def _update_confirmed(self) -> bool:
    if self.target_set_speed_confirmed:
      return True
    if self.state != AssistState.preActive:
      return False

    req_plus, req_minus = compare_cluster_target(self.v_cruise_cluster, self._speed_limit_final_last, self.is_metric)
    return self._get_button_release(req_plus, req_minus)

  def update_state_machine(self) -> tuple[bool, bool]:
    self.long_engaged_timer = max(0, self.long_engaged_timer - 1)
    self.pre_active_timer = max(0, self.pre_active_timer - 1)

    if self.state != AssistState.disabled:
      if not self.long_enabled or not self.enabled:
        self.state = AssistState.disabled

      elif self.state == AssistState.active:
        if self.v_cruise_cluster_changed:
          self.state = AssistState.inactive
        elif self.speed_limit_changed and self.apply_confirm_speed_threshold:
          self.state = AssistState.preActive
          self.pre_active_timer = int(PRE_ACTIVE_GUARD_PERIOD / DT_MDL)

      elif self.state == AssistState.preActive:
        if self._update_confirmed():
          self.state = AssistState.active
        elif self.pre_active_timer <= 0:
          self.state = AssistState.inactive

      elif self.state == AssistState.inactive:
        if self.speed_limit_changed:
          self.state = AssistState.preActive
          self.pre_active_timer = int(PRE_ACTIVE_GUARD_PERIOD / DT_MDL)
        elif self._update_confirmed():
          self.state = AssistState.active

    elif self.state == AssistState.disabled:
      if self.long_enabled and self.enabled:
        if not self.long_enabled_prev or self.v_cruise_cluster_changed:
          self.long_engaged_timer = int(DISABLED_GUARD_PERIOD / DT_MDL)
        elif self.long_engaged_timer <= 0:
          if self._update_confirmed():
            self.state = AssistState.active
          elif self._has_speed_limit:
            self.state = AssistState.preActive
            self.pre_active_timer = int(PRE_ACTIVE_GUARD_PERIOD / DT_MDL)
          else:
            self.state = AssistState.inactive

    enabled = self.state in ENABLED_STATES
    active = self.state in ACTIVE_STATES
    return enabled, active

  def _active_event(self):
    return EventName.speedLimitChanged if self.v_cruise_cluster_below_confirm_speed_threshold else EventName.speedLimitActive

  def _update_events(self) -> None:
    self.new_events = []
    if self.state == AssistState.preActive:
      self.new_events.append(EventName.speedLimitPreActive)

    if self.is_active:
      if self._state_prev not in ACTIVE_STATES:
        self.new_events.append(self._active_event())
      elif self._speed_limit != self.speed_limit_prev and self.speed_limit_prev > 0 and self._speed_limit > 0:
        self.new_events.append(self._active_event())

  def update(self, long_enabled: bool, v_ego: float, a_ego: float, v_cruise_cluster: float, speed_limit: float,
             speed_limit_final_last: float, has_speed_limit: bool, distance: float) -> None:
    self.long_enabled = long_enabled
    self.v_ego = v_ego
    self.a_ego = a_ego

    self._has_speed_limit = has_speed_limit
    self._speed_limit = speed_limit
    self._speed_limit_final_last = speed_limit_final_last
    self._distance = distance

    self.update_params()
    self.update_calculations(v_cruise_cluster)

    self._state_prev = self.state
    self.is_enabled, self.is_active = self.update_state_machine()

    self._update_events()

    self.speed_limit_prev = self._speed_limit
    self.v_cruise_cluster_prev = self.v_cruise_cluster
    self.long_enabled_prev = self.long_enabled
    self.prev_target_set_speed_conv = self.target_set_speed_conv
    self.prev_v_cruise_cluster_conv = self.v_cruise_cluster_conv

    self.output_v_target = self.get_v_target_from_control()
    self.output_a_target = self.get_a_target_from_control()

    self.frame += 1
