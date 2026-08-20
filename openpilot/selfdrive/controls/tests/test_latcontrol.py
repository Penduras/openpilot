from openpilot.common.test import OpenpilotTestCase
from openpilot.common.parameterized import parameterized

from openpilot.cereal import log
from opendbc.car.structs import car
from opendbc.car.car_helpers import interfaces
from opendbc.car.honda.values import CAR as HONDA
from opendbc.car.toyota.values import CAR as TOYOTA
from opendbc.car.nissan.values import CAR as NISSAN
from opendbc.car.gm.values import CAR as GM
from opendbc.car.tesla.values import CAR as TESLA
from opendbc.car.vehicle_model import VehicleModel
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque
from openpilot.selfdrive.controls.lib.latcontrol_angle import LatControlAngle, COOP_STEER_DEADZONE_NM, COOP_STEER_FULL_NM, COOP_STEER_ABS_MAX_DEG


class TestLatControl(OpenpilotTestCase):

  @parameterized.expand([(HONDA.HONDA_CIVIC, LatControlPID), (TOYOTA.TOYOTA_RAV4, LatControlTorque),
                         (NISSAN.NISSAN_LEAF, LatControlAngle), (GM.CHEVROLET_BOLT_EUV, LatControlTorque)])
  def test_saturation(self, car_name, controller):
    CarInterface = interfaces[car_name]
    CP = CarInterface.get_non_essential_params(car_name)
    CI = CarInterface(CP)
    VM = VehicleModel(CP)

    controller = controller(CP.as_reader(), CI, DT_CTRL)

    CS = car.CarState.new_message()
    CS.vEgo = 30
    CS.steeringPressed = False

    params = log.VehicleParameters.new_message()

    # Saturate for curvature limited and controller limited
    for _ in range(1000):
      _, _, lac_log = controller.update(True, CS, VM, params, False, 0, True, 0.2)
    assert lac_log.saturated

    for _ in range(1000):
      _, _, lac_log = controller.update(True, CS, VM, params, False, 0, False, 0.2)
    assert not lac_log.saturated

    for _ in range(1000):
      _, _, lac_log = controller.update(True, CS, VM, params, False, 1, False, 0.2)
    assert lac_log.saturated


class TestCoopSteerOffset(OpenpilotTestCase):
  # xnor: 2026-08-19 - covers the new Tesla-only light-touch torque nudge in
  # latcontrol_angle.py. See that file's own comment for the full rationale.

  def _make_controller(self):
    CarInterface = interfaces[TESLA.TESLA_MODEL_S_HW3]
    CP = CarInterface.get_non_essential_params(TESLA.TESLA_MODEL_S_HW3)
    CI = CarInterface(CP)
    VM = VehicleModel(CP)
    return LatControlAngle(CP.as_reader(), CI, DT_CTRL), VM

  def _run(self, controller, VM, steering_torque, steering_pressed, ticks=1):
    CS = car.CarState.new_message()
    CS.vEgo = 20.
    CS.steeringTorque = steering_torque
    CS.steeringPressed = steering_pressed
    params = log.VehicleParameters.new_message()
    for _ in range(ticks):
      controller.update(True, CS, VM, params, False, 0., False, 0.2)
    return controller.coop_steer_offset

  def test_zero_torque_zero_offset(self):
    controller, VM = self._make_controller()
    assert self._run(controller, VM, 0., False, ticks=50) == 0.

  def test_below_deadzone_no_offset(self):
    controller, VM = self._make_controller()
    offset = self._run(controller, VM, COOP_STEER_DEADZONE_NM * 0.5, False, ticks=50)
    assert offset == 0.

  def test_positive_torque_gives_positive_offset(self):
    controller, VM = self._make_controller()
    offset = self._run(controller, VM, COOP_STEER_FULL_NM, False, ticks=50)
    assert offset > 0.

  def test_negative_torque_gives_negative_offset(self):
    controller, VM = self._make_controller()
    offset = self._run(controller, VM, -COOP_STEER_FULL_NM, False, ticks=50)
    assert offset < 0.

  def test_offset_fades_out_once_override_engages(self):
    controller, VM = self._make_controller()
    # ramp up under light torque first
    self._run(controller, VM, COOP_STEER_FULL_NM, False, ticks=50)
    assert controller.coop_steer_offset > 0.
    # now a full override kicks in (steeringPressed) - offset should fade to ~0
    # as override_blend saturates to 1.0
    offset = self._run(controller, VM, COOP_STEER_FULL_NM, True, ticks=200)
    assert abs(offset) < 0.01

  def test_non_tesla_always_zero(self):
    CarInterface = interfaces[NISSAN.NISSAN_LEAF]
    CP = CarInterface.get_non_essential_params(NISSAN.NISSAN_LEAF)
    CI = CarInterface(CP)
    VM = VehicleModel(CP)
    controller = LatControlAngle(CP.as_reader(), CI, DT_CTRL)
    offset = self._run(controller, VM, COOP_STEER_FULL_NM, False, ticks=50)
    assert offset == 0.

  def test_low_speed_offset_stays_under_abs_cap(self):
    # xnor: 2026-08-20 - regression test for the low-speed blowup found via rlog replay of a
    # real multi-drive session: the lateral-accel-based speed scaling divides by v_ego^2 and
    # produced up to -64.8deg at under 2 m/s from a ~1 Nm nudge, nowhere near "light touch".
    controller, VM = self._make_controller()
    CS = car.CarState.new_message()
    CS.vEgo = 0.5  # near-stopped, parking-lot speed
    CS.steeringTorque = COOP_STEER_FULL_NM
    CS.steeringPressed = False
    params = log.VehicleParameters.new_message()
    for _ in range(200):
      controller.update(True, CS, VM, params, False, 0., False, 0.2)
    assert abs(controller.coop_steer_offset) <= COOP_STEER_ABS_MAX_DEG + 1e-6
