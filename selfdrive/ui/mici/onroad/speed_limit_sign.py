from dataclasses import dataclass

import pyray as rl

from cereal import custom
from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

# xnor: adapted from sunnypilot's selfdrive/ui/sunnypilot/onroad/speed_limit.py (already
# raylib/pyray-based, so it ports directly onto our mici UI stack). Trimmed: no SpeedLimitMode
# setting (shows whenever SpeedLimitControl is on), no pre-active up/down arrow icon (would need
# porting sunnypilot's PNG assets - the sign's own pulsing fade already signals preActive).

METER_TO_FOOT = 3.28084
METER_TO_MILE = 0.000621371
KM_TO_MILE = 0.621371

SIGN_WIDTH = 108
SIGN_HEIGHT = 108

AssistState = custom.LongitudinalPlanSP.SpeedLimit.AssistState
SpeedLimitSource = custom.LongitudinalPlanSP.SpeedLimit.Source


@dataclass(frozen=True)
class Colors:
  WHITE = rl.WHITE
  BLACK = rl.BLACK
  RED = rl.Color(235, 32, 32, 255)
  GREY = rl.Color(145, 155, 149, 255)
  DARK_GREY = rl.Color(77, 77, 77, 255)
  SUB_BG = rl.Color(0, 0, 0, 180)
  MUTCD_LINES = rl.Color(255, 255, 255, 100)


class _PreActiveFadeAnimator:
  """Pulses while the preActive prompt is showing, otherwise fully opaque."""

  def __init__(self, target_fps: int, duration_on: float = 0.75, rc: float = 0.05):
    self._filter = FirstOrderFilter(1.0, rc, 1 / target_fps)
    self._frame = 0
    self._target_fps = target_fps
    self._duration_on = duration_on

  def update(self, active: bool):
    if active:
      self._frame += 1
      if (self._frame % self._target_fps) < (self._target_fps * self._duration_on):
        self._filter.x = 1.0
      else:
        self._filter.update(0.0)
    else:
      self._frame = 0
      self._filter.update(1.0)

  @property
  def alpha(self) -> float:
    return self._filter.x


class SpeedLimitSignRenderer(Widget):
  def __init__(self):
    super().__init__()
    self.speed_limit = 0.0
    self.speed_limit_last = 0.0
    self.speed_limit_valid = False
    self.speed_limit_last_valid = False
    self.speed_limit_final_last = 0.0
    self.speed_limit_source = SpeedLimitSource.none
    self.assist_state = AssistState.disabled

    self.speed_limit_ahead = 0.0
    self.speed_limit_ahead_dist = 0.0
    self.speed_limit_ahead_valid = False

    self.speed: float = 0.0
    self.v_ego_cluster_seen: bool = False

    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._font_demi = gui_app.font(FontWeight.SEMI_BOLD)
    self._font_norm = gui_app.font(FontWeight.NORMAL)

    self._pre_active_fade = _PreActiveFadeAnimator(gui_app.target_fps, duration_on=0.75, rc=0.05)

  @property
  def _speed_conv(self):
    return CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH

  def _update_state(self) -> None:
    sm = ui_state.sm
    if sm.recv_frame["carState"] < ui_state.started_frame:
      self.speed = 0.0
      return

    if sm.updated["longitudinalPlanSP"]:
      lp_sp = sm["longitudinalPlanSP"]
      resolver = lp_sp.speedLimit.resolver
      assist = lp_sp.speedLimit.assist

      self.speed_limit = resolver.speedLimit * self._speed_conv
      self.speed_limit_last = resolver.speedLimitLast * self._speed_conv
      self.speed_limit_valid = resolver.speedLimitValid
      self.speed_limit_last_valid = resolver.speedLimitLastValid
      self.speed_limit_final_last = resolver.speedLimitFinalLast * self._speed_conv
      self.speed_limit_source = resolver.source
      self.assist_state = assist.state

    if sm.updated["liveMapDataSP"]:
      lmd = sm["liveMapDataSP"]
      self.speed_limit_ahead_valid = lmd.speedLimitAheadValid
      self.speed_limit_ahead = lmd.speedLimitAhead * self._speed_conv
      self.speed_limit_ahead_dist = lmd.speedLimitAheadDistance

    self._pre_active_fade.update(self.assist_state == AssistState.preActive)

    car_state = sm["carState"]
    self.v_ego_cluster_seen = self.v_ego_cluster_seen or car_state.vEgoCluster != 0.0
    v_ego = car_state.vEgoCluster if self.v_ego_cluster_seen else car_state.vEgo
    self.speed = max(0.0, v_ego * self._speed_conv)

  @staticmethod
  def _draw_text_centered(font, text, size, pos_center, color):
    sz = measure_text_cached(font, text, size)
    rl.draw_text_ex(font, text, rl.Vector2(pos_center.x - sz.x / 2, pos_center.y - sz.y / 2), size, 0, color)

  def _render(self, rect: rl.Rectangle) -> None:
    if not ui_state.params.get_bool("SpeedLimitControl"):
      return

    x = rect.x + rect.width - SIGN_WIDTH - 30
    y = rect.y + 45

    sign_rect = rl.Rectangle(x, y, SIGN_WIDTH, SIGN_HEIGHT)
    alpha = self._pre_active_fade.alpha

    self._draw_sign(sign_rect, alpha)
    self._draw_ahead_info(sign_rect)

  def _draw_sign(self, rect, alpha=1.0) -> None:
    has_limit = self.speed_limit_valid or self.speed_limit_last_valid
    is_overspeed = has_limit and round(self.speed_limit_final_last) < round(self.speed)

    limit_str = str(round(self.speed_limit_last)) if has_limit else "---"
    txt_color = Colors.RED if is_overspeed else (Colors.BLACK if self.speed_limit_valid else Colors.GREY)

    if ui_state.is_metric:
      self._render_vienna(rect, limit_str, txt_color, alpha)
    else:
      self._render_mutcd(rect, limit_str, txt_color, alpha)

  def _render_vienna(self, rect, val, color, alpha=1.0) -> None:
    center = rl.Vector2(rect.x + rect.width / 2, rect.y + rect.height / 2)
    radius = rect.width / 2

    white = rl.color_alpha(Colors.WHITE, alpha)
    red = rl.color_alpha(Colors.RED, alpha)
    text_color = rl.color_alpha(color, alpha)

    rl.draw_circle_v(center, radius, white)
    rl.draw_ring(center, radius * 0.8, radius, 0, 360, 36, red)

    font_size = 46 if len(val) >= 3 else 56
    self._draw_text_centered(self._font_bold, val, font_size, center, text_color)

  def _render_mutcd(self, rect, val, color, alpha=1.0) -> None:
    white = rl.color_alpha(Colors.WHITE, alpha)
    black = rl.color_alpha(Colors.BLACK, alpha)
    text_color = rl.color_alpha(color, alpha)

    rl.draw_rectangle_rounded(rect, 0.2, 10, white)
    inner = rl.Rectangle(rect.x + 6, rect.y + 6, rect.width - 12, rect.height - 12)
    rl.draw_rectangle_rounded_lines_ex(inner, 0.2, 10, 3, black)

    self._draw_text_centered(self._font_demi, "LIMIT", 22, rl.Vector2(rect.x + rect.width / 2, rect.y + 22), black)
    self._draw_text_centered(self._font_bold, val, 52, rl.Vector2(rect.x + rect.width / 2, rect.y + 70), text_color)

  def _draw_ahead_info(self, sign_rect) -> None:
    source_is_map = self.speed_limit_source == SpeedLimitSource.map
    valid = self.speed_limit_ahead_valid and self.speed_limit_ahead > 0 and self.speed_limit_ahead != self.speed_limit

    if not (valid and source_is_map):
      return

    rect = rl.Rectangle(sign_rect.x + (sign_rect.width - 130) / 2, sign_rect.y + sign_rect.height + 8, 130, 110)
    rl.draw_rectangle_rounded(rect, 0.25, 10, Colors.SUB_BG)
    rl.draw_rectangle_rounded_lines_ex(rect, 0.25, 10, 2, Colors.MUTCD_LINES)

    mid_x = rect.x + rect.width / 2
    self._draw_text_centered(self._font_demi, "AHEAD", 26, rl.Vector2(mid_x, rect.y + 20), Colors.GREY)
    self._draw_text_centered(self._font_bold, str(round(self.speed_limit_ahead)), 46, rl.Vector2(mid_x, rect.y + 58), Colors.WHITE)
    self._draw_text_centered(self._font_norm, self._format_dist(self.speed_limit_ahead_dist), 24, rl.Vector2(mid_x, rect.y + 92), Colors.GREY)

  @staticmethod
  def _format_dist(d) -> str:
    if ui_state.is_metric:
      if d < 50:
        return tr("Near")
      if d >= 1000:
        return f"{d / 1000:.1f} km"
      d_rounded = round(d, -1) if d < 200 else round(d, -2)
      return f"{int(d_rounded)} m"

    d_ft = d * METER_TO_FOOT
    if d_ft < 100:
      return tr("Near")
    if d_ft >= 900:
      return f"{d * METER_TO_MILE:.1f} mi"
    if d_ft < 500:
      return f"{int(round(d_ft / 50) * 50)} ft"
    return f"{int(round(d_ft / 100) * 100)} ft"
