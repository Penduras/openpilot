"""
MADS (Modular Assistive Driving System), ported from sunnypilot into xnor-dev.

Lets lateral (steering) control stay engaged independent of longitudinal (cruise)
engagement. Ported lean/Tesla-focused: xnor-dev doesn't carry sunnypilot's CP_SP /
dual event-bus architecture, so this uses the stock Events()/EventName machinery
directly instead of a parallel events_sp/EventNameSP bus.

Steering-mode-on-brake is hardcoded to DISENGAGE: sunnypilot itself only offers
"partial support" (DISENGAGE-only) for Tesla and Rivian, since neither has the
signals needed to safely continue steering through a brake press. The "paused"
state (silently continuing lateral through transient door/seatbelt/gear blips)
is unrelated to brake handling and is kept, since that's the core value MADS adds.

Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.
Adapted under the MIT License. See LICENSE.md.
"""
from cereal import log, custom
from opendbc.car import structs
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.selfdrived.events import ET
from openpilot.selfdrive.selfdrived.state import SOFT_DISABLE_TIME

State = custom.ModularAssistiveDrivingSystem.ModularAssistiveDrivingSystemState
ButtonType = structs.CarState.ButtonEvent.Type
EventName = log.OnroadEvent.EventName
SafetyModel = structs.CarParams.SafetyModel

SET_SPEED_BUTTONS = (ButtonType.accelCruise, ButtonType.resumeCruise, ButtonType.decelCruise, ButtonType.setCruise)
IGNORED_SAFETY_MODES = (SafetyModel.silent, SafetyModel.noOutput)

# Brands with no reliable ACC-main-button signal to hook engagement off of
MADS_NO_ACC_MAIN_BUTTON = ("rivian", "tesla")

ACTIVE_STATES = (State.enabled, State.softDisabling, State.overriding)
ENABLED_STATES = (State.paused, *ACTIVE_STATES)

GEARS_ALLOW_PAUSED = [EventName.wrongGear, EventName.reverseGear, EventName.brakeHold,
                      EventName.doorOpen, EventName.seatbeltNotLatched, EventName.parkBrake]
GEARS_ALLOW_PAUSED_SILENT = [EventName.silentWrongGear, EventName.silentReverseGear, EventName.silentBrakeHold,
                             EventName.silentDoorOpen, EventName.silentSeatbeltNotLatched, EventName.silentParkBrake]

ALT_EXP_ENABLE_MADS = 1024
ALT_EXP_MADS_DISENGAGE_LATERAL_ON_BRAKE = 2048


def set_alternative_experience(CP: structs.CarParams, params: Params) -> None:
  if params.get_bool("Mads"):
    CP.alternativeExperience |= ALT_EXP_ENABLE_MADS
    CP.alternativeExperience |= ALT_EXP_MADS_DISENGAGE_LATERAL_ON_BRAKE


class MadsStateMachine:
  def __init__(self, mads: "ModularAssistiveDrivingSystem"):
    self.selfdrive = mads.selfdrive
    self.ss_state_machine = mads.selfdrive.state_machine
    self._events = mads.selfdrive.events

    self.state = State.disabled

  def add_current_alert_types(self, alert_type):
    if not self.selfdrive.enabled:
      self.ss_state_machine.current_alert_types.append(alert_type)

  def check_contains(self, event_type: str) -> bool:
    return self._events.contains(event_type)

  def check_contains_in_list(self) -> bool:
    return self._events.contains_in_list(GEARS_ALLOW_PAUSED) or self._events.contains_in_list(GEARS_ALLOW_PAUSED_SILENT)

  def update(self):
    if self.state != State.disabled:
      if self.check_contains(ET.USER_DISABLE):
        if self._events.has(EventName.silentLkasDisable):
          self.state = State.paused
        else:
          self.state = State.disabled
        self.ss_state_machine.current_alert_types.append(ET.USER_DISABLE)

      elif self.check_contains(ET.IMMEDIATE_DISABLE):
        self.state = State.disabled
        self.add_current_alert_types(ET.IMMEDIATE_DISABLE)

      else:
        if self.state == State.enabled:
          if self.check_contains(ET.SOFT_DISABLE):
            self.state = State.softDisabling
            if not self.selfdrive.enabled:
              self.ss_state_machine.soft_disable_timer = int(SOFT_DISABLE_TIME / DT_CTRL)
              self.ss_state_machine.current_alert_types.append(ET.SOFT_DISABLE)

          elif self.check_contains(ET.OVERRIDE_LATERAL):
            self.state = State.overriding
            self.add_current_alert_types(ET.OVERRIDE_LATERAL)

        elif self.state == State.softDisabling:
          if not self.check_contains(ET.SOFT_DISABLE):
            self.state = State.enabled

          elif self.ss_state_machine.soft_disable_timer > 0:
            self.add_current_alert_types(ET.SOFT_DISABLE)

          elif self.ss_state_machine.soft_disable_timer <= 0:
            self.state = State.disabled

        elif self.state == State.paused:
          if self.check_contains(ET.ENABLE):
            if self.check_contains(ET.NO_ENTRY):
              self.add_current_alert_types(ET.NO_ENTRY)
            else:
              if self.check_contains(ET.OVERRIDE_LATERAL):
                self.state = State.overriding
              else:
                self.state = State.enabled
              self.add_current_alert_types(ET.ENABLE)

        elif self.state == State.overriding:
          if self.check_contains(ET.SOFT_DISABLE):
            self.state = State.softDisabling
            if not self.selfdrive.enabled:
              self.ss_state_machine.soft_disable_timer = int(SOFT_DISABLE_TIME / DT_CTRL)
              self.ss_state_machine.current_alert_types.append(ET.SOFT_DISABLE)
          elif not self.check_contains(ET.OVERRIDE_LATERAL):
            self.state = State.enabled
          else:
            self.ss_state_machine.current_alert_types += [ET.OVERRIDE_LATERAL]

    elif self.state == State.disabled:
      if self.check_contains(ET.ENABLE):
        if self.check_contains(ET.NO_ENTRY):
          if self.check_contains_in_list():
            self.state = State.paused
          self.add_current_alert_types(ET.NO_ENTRY)
        else:
          if self.check_contains(ET.OVERRIDE_LATERAL):
            self.state = State.overriding
          else:
            self.state = State.enabled
          self.add_current_alert_types(ET.ENABLE)

    enabled = self.state in ENABLED_STATES
    active = self.state in ACTIVE_STATES
    if active:
      self.add_current_alert_types(ET.WARNING)

    return enabled, active


class ModularAssistiveDrivingSystem:
  def __init__(self, selfdrive):
    self.CP = selfdrive.CP
    self.params = selfdrive.params

    self.enabled = False
    self.active = False
    self.lateral_mismatch_counter = 0
    self.selfdrive = selfdrive
    self.selfdrive.enabled_prev = False
    self.state_machine = MadsStateMachine(self)
    self.events = self.selfdrive.events
    self.disengage_on_accelerator = Params().get_bool("DisengageOnAccelerator")

    self.allow_always = self.CP.brand == "tesla"
    self.no_main_cruise = self.CP.brand in MADS_NO_ACC_MAIN_BUTTON

    # read params on init
    self.enabled_toggle = self.params.get_bool("Mads")

  def pedal_pressed_non_gas_pressed(self, CS: structs.CarState) -> bool:
    if self.events.has(EventName.pedalPressed) and not (CS.gasPressed and not self.selfdrive.CS_prev.gasPressed and self.disengage_on_accelerator):
      return True
    return False

  def should_silent_lkas_enable(self, CS: structs.CarState) -> bool:
    if self.events.contains_in_list(GEARS_ALLOW_PAUSED_SILENT):
      return False
    return True

  def get_wrong_car_mode(self, alert_only: bool) -> None:
    if alert_only:
      if self.events.has(EventName.wrongCarMode):
        self.replace_event(EventName.wrongCarMode, EventName.wrongCarModeAlertOnly)
    else:
      self.events.remove(EventName.wrongCarMode)

  def transition_paused_state(self):
    if self.state_machine.state != State.paused:
      self.events.add(EventName.silentLkasDisable)

  def replace_event(self, old_event: int, new_event: int):
    self.events.remove(old_event)
    self.events.add(new_event)

  def data_sample(self):
    # Panda's controlsAllowedLateral status arrives over a different socket than CAN,
    # so allow a couple frames of mismatch before disengaging.
    if not self.active or self.selfdrive.enabled:
      self.lateral_mismatch_counter = 0

  def update_events(self, CS: structs.CarState):
    if not self.selfdrive.enabled and self.enabled:
      if CS.standstill:
        if self.events.has(EventName.doorOpen):
          self.replace_event(EventName.doorOpen, EventName.silentDoorOpen)
          self.transition_paused_state()
        if self.events.has(EventName.seatbeltNotLatched):
          self.replace_event(EventName.seatbeltNotLatched, EventName.silentSeatbeltNotLatched)
          self.transition_paused_state()
      if self.events.has(EventName.wrongGear) and (CS.vEgo < 2.5 or CS.gearShifter == structs.CarState.GearShifter.reverse):
        self.replace_event(EventName.wrongGear, EventName.silentWrongGear)
        self.transition_paused_state()
      if self.events.has(EventName.reverseGear):
        self.replace_event(EventName.reverseGear, EventName.silentReverseGear)
        self.transition_paused_state()
      if self.events.has(EventName.brakeHold):
        self.replace_event(EventName.brakeHold, EventName.silentBrakeHold)
        self.transition_paused_state()
      if self.events.has(EventName.parkBrake):
        self.replace_event(EventName.parkBrake, EventName.silentParkBrake)
        self.transition_paused_state()

      self.events.remove(EventName.preEnableStandstill)
      self.events.remove(EventName.belowEngageSpeed)
      self.events.remove(EventName.speedTooLow)
      self.events.remove(EventName.cruiseDisabled)
      self.events.remove(EventName.manualRestart)
      self.events.remove(EventName.espActive)

    selfdrive_enable_events = self.events.has(EventName.pcmEnable) or self.events.has(EventName.buttonEnable)
    set_speed_btns_enable = any(be.type in SET_SPEED_BUTTONS for be in CS.buttonEvents)

    self.get_wrong_car_mode(selfdrive_enable_events or set_speed_btns_enable)

    if selfdrive_enable_events:
      if self.pedal_pressed_non_gas_pressed(CS):
        self.events.add(EventName.pedalPressedAlertOnly)
      # unified engagement: don't block the primary engage-event, MADS follows it
    else:
      pass  # no ACC-main-button hookup for tesla/rivian

    for be in CS.buttonEvents:
      if be.type == ButtonType.cancel:
        if not self.selfdrive.enabled and self.selfdrive.enabled_prev:
          self.events.add(EventName.manualLongitudinalRequired)
        # xnor: cancel always disengages longitudinal fully, so mirror the LKAS button's
        # "already off" branch (lkasDisable) - cancel has no partial/lateral-only case.
        # Without this, MADS never learns cruise was cancelled (cruiseState.available's
        # own fallback is gated off for tesla via no_main_cruise below), keeps trying to
        # steer, the real EPAS refuses once DI_cruiseState is OFF, and that surfaces as a
        # steerFault -> SOFT_DISABLE "TAKE CONTROL IMMEDIATELY" alert instead of a clean
        # disengage chime.
        if be.pressed and self.enabled and not self.selfdrive.enabled:
          self.events.add(EventName.lkasDisable)
      if be.type == ButtonType.lkas and be.pressed and (CS.cruiseState.available or self.allow_always):
        if self.enabled:
          if self.selfdrive.enabled:
            self.events.add(EventName.manualSteeringRequired)
          else:
            self.events.add(EventName.lkasDisable)
        else:
          self.events.add(EventName.lkasEnable)

    if not CS.cruiseState.available and not self.no_main_cruise:
      self.events.remove(EventName.buttonEnable)
      if self.selfdrive.CS_prev.cruiseState.available:
        self.events.add(EventName.lkasDisable)

    # steering-mode-on-brake: DISENGAGE only (matches sunnypilot's Tesla/Rivian "partial support" tier)
    if self.pedal_pressed_non_gas_pressed(CS):
      if self.enabled:
        self.events.add(EventName.lkasDisable)
      else:
        if self.events.has(EventName.lkasEnable):
          self.events.remove(EventName.lkasEnable)
          self.events.add(EventName.pedalPressedAlertOnly)

    if self.should_silent_lkas_enable(CS):
      if self.state_machine.state == State.paused:
        self.events.add(EventName.silentLkasEnable)

    self.events.remove(EventName.pcmDisable)
    self.events.remove(EventName.buttonCancel)
    self.events.remove(EventName.pedalPressed)
    self.events.remove(EventName.wrongCruiseMode)

  def update(self, CS: structs.CarState):
    if not self.enabled_toggle:
      return

    self.data_sample()
    self.update_events(CS)

    if not self.CP.passive and self.selfdrive.initialized:
      self.enabled, self.active = self.state_machine.update()

    self.selfdrive.enabled_prev = self.selfdrive.enabled
