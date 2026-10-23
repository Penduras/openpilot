from openpilot.selfdrive.controls.lib.longitudinal_planner import apply_limit_offset, hold_for_next_limit, SPEED_UP_LEAD_TIME

KPH = 1 / 3.6


class TestHoldForNextLimit:
  def hold(self, v_ego, limit, nxt, dist, sugg):
    return hold_for_next_limit(v_ego * KPH, limit * KPH, nxt * KPH, dist, sugg * KPH)

  def test_holds_old_limit_while_far(self):
    # 60 -> 80, mapd already suggesting 80, sign still 150 m away at 60 km/h (lead window ~50 m)
    cap = self.hold(60, 60, 80, 150, 80)
    assert cap is not None and abs(cap - 60 * KPH) < 1e-6

  def test_releases_inside_lead_time(self):
    v = 60 * KPH
    dist = v * SPEED_UP_LEAD_TIME
    assert self.hold(60, 60, 80, dist - 1, 80) is None
    assert self.hold(60, 60, 80, dist + 1, 80) is not None

  def test_lead_time_scales_with_speed(self):
    # same distance, slower car -> still held; faster car -> released
    assert self.hold(30, 30, 50, 60, 50) is not None  # 60 m > 30 km/h * 3 s = 25 m
    assert self.hold(80, 80, 100, 60, 100) is None  # 60 m < 80 km/h * 3 s = 67 m

  def test_never_caps_below_current_speed(self):
    # driver already faster than the limit: cap follows the car, so the hold never causes braking
    cap = self.hold(70, 60, 80, 150, 80)
    assert cap is not None and abs(cap - 70 * KPH) < 1e-6

  def test_ignores_gas_override_without_speedup_trigger(self):
    # mapd has not suggested the new limit (suggestion still the old one): no hold
    assert self.hold(70, 60, 80, 150, 60) is None

  def test_no_hold_without_upcoming_increase(self):
    assert self.hold(60, 60, 60, 150, 60) is None  # same limit
    assert self.hold(60, 60, 50, 150, 50) is None  # decrease: never delayed
    assert self.hold(60, 0, 80, 150, 80) is None  # no current limit known
    assert self.hold(60, 60, 80, 0, 80) is None  # no distance


class TestApplyLimitOffset:
  def test_off_is_identity(self):
    assert apply_limit_offset(20., 20., 0) == 20.

  def test_scales_when_limit_binds(self):
    assert abs(apply_limit_offset(20., 20., 4) - 20.8) < 1e-9

  def test_curve_binding_not_raised(self):
    assert apply_limit_offset(12., 20., 4) == 12.

  def test_no_limit_part(self):
    assert apply_limit_offset(20., 0., 4) == 20.
