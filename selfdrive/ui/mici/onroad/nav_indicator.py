import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

# xnor: first cut at reading Tesla's own in-car navigation off CAN (UI_driverAssistMapData,
# sourced from the infotainment computer's active route - see the stockNav* fields in
# opendbc/car/tesla/carstate.py). Only distance-to-next-turn and a "is it a left exit" flag
# are decoded so far, out of a message that has room for more (see CarState.stockNav*
# doc-comment in car.capnp) - this widget is deliberately labeled and minimal so it's
# obvious how little of the signal is actually understood yet, pending real-drive
# verification that the decoded bits mean what we think they mean.

BOX_HEIGHT = 80
FONT_SIZE = 32
LABEL_SIZE = 18
DIAG_SIZE = 16
PADDING_H = 20


class NavIndicator(Widget):
  def __init__(self):
    super().__init__()
    self.route_active = False
    self.next_maneuver_distance = 0.0
    self.next_maneuver_left = False
    self.controlled_access = False

    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._font_demi = gui_app.font(FontWeight.SEMI_BOLD)

  def _update_state(self) -> None:
    sm = ui_state.sm
    if sm.updated["carState"]:
      cs = sm["carState"]
      self.route_active = cs.stockNavRouteActive
      self.next_maneuver_distance = cs.stockNavNextManeuverDistance
      self.next_maneuver_left = cs.stockNavNextManeuverLeft
      self.controlled_access = cs.stockNavControlledAccess

  def _format_distance(self) -> str:
    d = self.next_maneuver_distance
    if ui_state.is_metric:
      return f"{round(d)} m"
    return f"{round(d * 3.28084)} ft"

  def _render(self, rect: rl.Rectangle) -> None:
    if not ui_state.params.get_bool("ShowStockNav"):
      return
    if not (self.route_active and self.next_maneuver_distance > 0.):
      return

    label = "NAV ←" if self.next_maneuver_left else "NAV"
    dist_text = self._format_distance()
    # xnor: temporary diagnostic line - see if nextManeuverDistance pinning at its 300m
    # ceiling correlates with DAS not considering the road a controlled-access highway
    diag_text = "highway: yes" if self.controlled_access else "highway: no"

    label_sz = measure_text_cached(self._font_demi, label, LABEL_SIZE)
    dist_sz = measure_text_cached(self._font_bold, dist_text, FONT_SIZE)
    diag_sz = measure_text_cached(self._font_demi, diag_text, DIAG_SIZE)
    box_width = int(max(label_sz.x, dist_sz.x, diag_sz.x) + PADDING_H * 2)

    box_x = rect.x + (rect.width - box_width) / 2
    box_y = rect.y + 20

    box = rl.Rectangle(box_x, box_y, box_width, BOX_HEIGHT)
    rl.draw_rectangle_rounded(box, 0.2, 10, rl.Color(0, 0, 0, 180))

    cx = box_x + box_width / 2
    rl.draw_text_ex(self._font_demi, label, rl.Vector2(cx - label_sz.x / 2, box_y + 4), LABEL_SIZE, 0, rl.Color(180, 180, 180, 255))
    rl.draw_text_ex(self._font_bold, dist_text, rl.Vector2(cx - dist_sz.x / 2, box_y + 24), FONT_SIZE, 0, rl.WHITE)
    diag_color = rl.Color(120, 220, 120, 255) if self.controlled_access else rl.Color(220, 120, 120, 255)
    rl.draw_text_ex(self._font_demi, diag_text, rl.Vector2(cx - diag_sz.x / 2, box_y + 58), DIAG_SIZE, 0, diag_color)
