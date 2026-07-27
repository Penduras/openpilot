import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

# xnor: small "SCC-M" badge indicating Smart Cruise Control - Map is active (mapd is
# currently slowing for a mapped upcoming curve), mirroring sunnypilot's
# selfdrive/ui/sunnypilot/onroad/smart_cruise_control.py but reading mapdOut directly
# since mapd computes map-curve speed internally (see selfdrive/mapd/mapd_config.py).

BOX_WIDTH = 160
FONT_SIZE = 36
PADDING_V = 5


class SccMapBadge(Widget):
  def __init__(self):
    super().__init__()
    self.enabled = False
    self.active = False
    self.long_override = False

    self._font = gui_app.font(FontWeight.BOLD)

  def _update_state(self) -> None:
    sm = ui_state.sm
    self.enabled = ui_state.params.get_bool("SmartCruiseControlMap")

    if sm.updated["mapdOut"]:
      self.active = sm["mapdOut"].mapCurveSpeed > 0.

    if sm.updated["carControl"]:
      self.long_override = sm["carControl"].cruiseControl.override

  def _render(self, rect: rl.Rectangle) -> None:
    if not self.enabled:
      return

    text = "SCC-M"
    sz = measure_text_cached(self._font, text, FONT_SIZE)
    box_height = int(sz.y + PADDING_V * 2)

    box_color = rl.Color(255, 165, 0, 255) if self.long_override else rl.Color(0, 255, 0, 255)
    text_color = rl.BLACK

    box_x = rect.x + rect.width - 260 - BOX_WIDTH / 2
    box_y = rect.height / 4 - 40 - box_height / 2

    box_color = rl.color_alpha(box_color, 1.0 if self.active else 0.4)
    text_color = rl.color_alpha(text_color, 1.0 if self.active else 0.4)

    rl.draw_rectangle_rounded(rl.Rectangle(box_x, box_y, BOX_WIDTH, box_height), 0.2, 10, box_color)

    text_pos = rl.Vector2(box_x + (BOX_WIDTH - sz.x) / 2, box_y + (box_height - sz.y) / 2)
    rl.draw_text_ex(self._font, text, text_pos, FONT_SIZE, 0, text_color)
