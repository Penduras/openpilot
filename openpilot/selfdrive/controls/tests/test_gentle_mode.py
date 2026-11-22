import numpy as np

from openpilot.cereal import log
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import GENTLE_JERK_FACTOR, get_jerk_factor
from openpilot.selfdrive.controls.lib.longitudinal_planner import (A_CRUISE_MIN, A_CRUISE_MIN_GENTLE, GENTLE_ACCEL_SCALE,
                                                                    GENTLE_JERK_SCALE, get_cruise_accel, get_max_accel, gentle_accel_cap)

P = log.LongitudinalPersonality


class FakeCP:
  steerRatio = 15.0
  wheelbase = 2.96


class TestGentleMode:
  def test_accel_cap_is_lower_everywhere(self):
    for v in (0., 5., 10., 20., 30., 40.):
      assert 0. < gentle_accel_cap(v) < get_max_accel(v)
      assert np.isclose(gentle_accel_cap(v), get_max_accel(v) * GENTLE_ACCEL_SCALE)

  def test_cruise_accel_ramps_slower_when_gentle(self):
    kw = {"e2e": False, "v_cruise": 30., "v_ego": 10., "a_cruise_prev": 0., "angle_steers": 0., "CP": FakeCP(), "dt": 0.05,
          "accel_coast": 0., "allow_throttle": True}
    normal = get_cruise_accel(**kw)
    gentle = get_cruise_accel(**kw, gentle=True)
    assert 0. < gentle < normal
    assert np.isclose(gentle / normal, GENTLE_JERK_SCALE)

  def test_braking_not_limited(self):
    kw = {"e2e": False, "v_cruise": 5., "v_ego": 20., "a_cruise_prev": -0.5, "angle_steers": 0., "CP": FakeCP(), "dt": 0.05,
          "accel_coast": 0., "allow_throttle": True}
    assert get_cruise_accel(**kw, gentle=True) <= 0.
    # the planner only caps the positive side
    assert min(-3.0, gentle_accel_cap(20.)) == -3.0

  def test_jerk_factor_floor(self):
    assert GENTLE_JERK_FACTOR > get_jerk_factor(P.aggressive)
    for p in (P.aggressive, P.standard, P.relaxed):
      assert max(get_jerk_factor(p), GENTLE_JERK_FACTOR) == GENTLE_JERK_FACTOR

  def test_cruise_slowdown_floor(self):
    # a big set-speed drop (80 -> 30 km/h) must brake properly in normal mode and softer in gentle mode
    kw = {"e2e": False, "v_cruise": 30 / 3.6, "v_ego": 80 / 3.6, "a_cruise_prev": A_CRUISE_MIN, "angle_steers": 0., "CP": FakeCP(), "dt": 0.05,
          "accel_coast": 0., "allow_throttle": True}
    assert A_CRUISE_MIN < A_CRUISE_MIN_GENTLE < 0.
    assert np.isclose(get_cruise_accel(**kw), A_CRUISE_MIN)
    kw["a_cruise_prev"] = A_CRUISE_MIN_GENTLE
    assert np.isclose(get_cruise_accel(**kw, gentle=True), A_CRUISE_MIN_GENTLE)
