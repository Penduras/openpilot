import math

import pyray as rl

from openpilot.selfdrive.ui.mici.onroad.speed_limit_sign import SpeedLimitSignRenderer
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

# xnor: small onroad badge indicating a Smart Cruise Control sub-feature (map- or
# vision-derived curve speed) is active, mirroring sunnypilot's
# selfdrive/ui/sunnypilot/onroad/smart_cruise_control.py but reading mapdOut directly
# since mapd computes both map- and vision-curve speed internally (see
# selfdrive/mapd/mapd_config.py). Positioned as a satellite dot on the speed limit sign's
# own circumference, at a clock-face angle, rather than stacked as a separate element -
# reuses SpeedLimitSignRenderer._sign_rect so the anchor always matches the sign exactly.

BOX_SIZE = 36
FONT_SIZE = 22
BADGE_GAP = 4  # gap between the sign's edge and the badge


class SccBadge(Widget):
  def __init__(self, label: str, param_key: str, speed_field: str, clock_hour: float):
    super().__init__()
    self._label = label
    self._param_key = param_key
    self._speed_field = speed_field
    self._angle = math.radians(clock_hour * 30)  # 0 = 12 o'clock, clockwise

    self.badge_enabled = False
    self.active = False
    self.long_override = False

    self._font = gui_app.font(FontWeight.BOLD)

  def _update_state(self) -> None:
    sm = ui_state.sm
    self.badge_enabled = ui_state.params.get_bool(self._param_key)

    if sm.updated["mapdOut"]:
      self.active = getattr(sm["mapdOut"], self._speed_field) > 0.

    if sm.updated["carControl"]:
      self.long_override = sm["carControl"].cruiseControl.override

  def _center(self, rect: rl.Rectangle) -> rl.Vector2:
    sign_rect = SpeedLimitSignRenderer._sign_rect(rect)
    sign_radius = sign_rect.width / 2
    cx = sign_rect.x + sign_radius
    cy = sign_rect.y + sign_radius
    r = sign_radius + BADGE_GAP + BOX_SIZE / 2
    return rl.Vector2(cx + r * math.sin(self._angle), cy - r * math.cos(self._angle))

  def _render(self, rect: rl.Rectangle) -> None:
    if not self.badge_enabled:
      return

    center = self._center(rect)
    box = rl.Rectangle(center.x - BOX_SIZE / 2, center.y - BOX_SIZE / 2, BOX_SIZE, BOX_SIZE)

    box_color = rl.Color(255, 165, 0, 255) if self.long_override else rl.Color(0, 255, 0, 255)
    text_color = rl.BLACK

    box_color = rl.color_alpha(box_color, 1.0 if self.active else 0.4)
    text_color = rl.color_alpha(text_color, 1.0 if self.active else 0.4)

    rl.draw_rectangle_rounded(box, 0.3, 10, box_color)

    sz = measure_text_cached(self._font, self._label, FONT_SIZE)
    text_pos = rl.Vector2(center.x - sz.x / 2, center.y - sz.y / 2)
    rl.draw_text_ex(self._font, self._label, text_pos, FONT_SIZE, 0, text_color)
