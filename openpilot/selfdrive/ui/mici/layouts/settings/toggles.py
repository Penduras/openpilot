import datetime
import time

from openpilot.cereal import log

from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigParamControl, BigMultiParamToggle
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog, BigDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from openpilot.selfdrive.ui.ui_state import ui_state

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants


class MapDataUpdateButton(BigButton):
  """xnor: asks mapd_config for a fresh offline map download, i.e. what the weekly check does, on demand.
  Nothing is deleted: mapd keeps using the existing data until the new files land. The sub-label shows the
  progress (MapdDownloadStatus, written by mapd_config) or when the last update was started."""
  POLL_PERIOD = 0.5

  def __init__(self):
    super().__init__("update\nmap data", "", gui_app.texture("icons_mici/settings/device/update.png", 64, 64))
    self._confirm_icon = gui_app.texture("icons_mici/settings/device/update.png", 64, 64)
    self._last_poll = 0.
    self.set_click_callback(self._on_click)
    self._refresh_value()

  def _refresh_value(self):
    params = ui_state.params
    status = params.get("MapdDownloadStatus") or ""
    if status:
      value = status
    elif params.get_bool("MapdRefreshRequested"):
      value = "requesting..."
    else:
      last = params.get("OsmLastUpdateCheck")
      value = f"last update {last.strftime('%b %d').lower()}" if isinstance(last, datetime.datetime) else "no update yet"
    if value != self.value:
      self.set_value(value)

  def _update_state(self):
    super()._update_state()
    now = time.monotonic()
    if now - self._last_poll >= self.POLL_PERIOD:
      self._last_poll = now
      self._refresh_value()

  def _on_click(self):
    params = ui_state.params
    if ui_state.started:
      gui_app.push_widget(BigDialog("", "Park the car first. Speed limit features pause while the map downloads."))
    elif not (params.get_bool("SpeedLimitControl") or params.get_bool("SmartCruiseControlMap")):
      gui_app.push_widget(BigDialog("", "Turn on speed limit control or smart cruise control - map first."))
    elif params.get_bool("MapdRefreshRequested") or params.get("MapdDownloadStatus"):
      gui_app.push_widget(BigDialog("", "A map update is already running."))
    else:
      gui_app.push_widget(BigConfirmationDialog("slide to\nupdate map data", self._confirm_icon,
                                                lambda: params.put_bool("MapdRefreshRequested", True)))


class SpeedLimitOffsetButton(BigButton):
  """xnor: tap to step the speed limit offset (SpeedLimitOffset param, percent) 0..10, wrapping around.
  The sub-label shows the current value; BigMultiParamToggle would draw one pill per option (11 of them)."""
  MAX_PERCENT = 10

  def __init__(self):
    super().__init__("speed limit\noffset", "")
    self.set_click_callback(self._on_click)
    self.refresh()

  def _percent(self) -> int:
    return max(0, min(self.MAX_PERCENT, ui_state.params.get("SpeedLimitOffset") or 0))

  def refresh(self):
    pct = self._percent()
    value = f"+{pct}%" if pct else "off"
    if value != self.value:
      self.set_value(value)

  def _on_click(self):
    ui_state.params.put("SpeedLimitOffset", (self._percent() + 1) % (self.MAX_PERCENT + 1), block=True)
    self.refresh()


class ToggleFolder(NavScroller):
  def __init__(self, widgets):
    super().__init__()
    self._scroller.add_widgets(widgets)


class TogglesLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    self._personality_toggle = BigMultiParamToggle("driving personality", "LongitudinalPersonality", ["aggressive", "standard", "relaxed"],
                                                   description="Standard is recommended.\n" +
                                                               "Aggressive follows closer, with firmer gas and braking.\n" +
                                                               "Relaxed leaves more space.\n" +
                                                               "Use the steering wheel distance button on supported cars.")
    self._experimental_btn = BigParamControl("experimental mode", "ExperimentalMode",
                                       description_icon=gui_app.texture("icons_mici/experimental_mode.png", 64, 64),
                                       description="Let the driving model control gas and brakes.\n" +
                                                   "Includes stopping for red lights and stop signs.\n" +
                                                   "Set speed is a maximum, not a target.\n" +
                                                   "These are alpha features. Expect mistakes.\n" +
                                                   "The path colors show acceleration and braking.")
    gentle_toggle = BigParamControl("gentle mode (winter)", "GentleMode",
                                    description="Softer gas and brakes for ice and snow.\n" +
                                                "Caps acceleration and smooths speed changes.\n" +
                                                "Following distance is unchanged.\n" +
                                                "Emergency braking is not limited.")
    is_metric_toggle = BigParamControl("use metric units", "IsMetric")
    ldw_toggle = BigParamControl("lane departure warnings", "IsLdwEnabled",
                                 description="Warn when you drift across a detected lane line.\n" +
                                             "Only above 31 mph (50 km/h), with no turn signal.")
    always_on_dm_toggle = BigParamControl("always-on driver monitor", "AlwaysOnDM", description="Monitor the driver even when openpilot is not engaged.")
    record_front = BigParamControl("record & upload cabin camera", "RecordFront",
                                   description_icon=gui_app.texture("icons_mici/settings/device/cameras.png", 64, 64),
                                   toggle_callback=restart_needed_callback, description="Upload cabin camera data to help improve driver monitoring.")
    record_mic = BigParamControl("record & upload mic audio", "RecordAudio", description_icon=gui_app.texture("icons_mici/microphone.png", 64, 64),
                                 toggle_callback=restart_needed_callback,
                                 description="Record microphone audio while driving.\n" +
                                             "Audio is included in dashcam videos in comma connect.")
    enable_openpilot = BigParamControl("enable openpilot", "OpenpilotEnabledToggle", toggle_callback=restart_needed_callback,
                                       description="Enable to use openpilot driver assistance.\n" +
                                                   "Disable to use your car's stock driver assistance.")
    quiet_mode_toggle = BigParamControl("quiet mode", "QuietMode")
    tailscale_toggle = BigParamControl("tailscale remote access", "TailscaleEnabled")
    mads_toggle = BigParamControl("modular assistive driving system (mads)", "Mads", toggle_callback=restart_needed_callback)
    speed_limit_toggle = BigParamControl("speed limit control", "SpeedLimitControl", toggle_callback=restart_needed_callback)
    self._speed_limit_offset = SpeedLimitOffsetButton()
    speed_limit_offset = self._speed_limit_offset
    scc_map_toggle = BigParamControl("smart cruise control - map", "SmartCruiseControlMap", toggle_callback=restart_needed_callback)
    scc_vision_toggle = BigParamControl("smart cruise control - vision", "SmartCruiseControlVision", toggle_callback=restart_needed_callback)

    # xnor: the toggle list got long, so the top level holds a few folders that each open a short list
    folders = (
      ("driving", [self._personality_toggle, self._experimental_btn, gentle_toggle]),
      ("speed &\nmap", [speed_limit_toggle, speed_limit_offset, scc_map_toggle, scc_vision_toggle, MapDataUpdateButton()]),
      ("display &\nalerts", [is_metric_toggle, ldw_toggle, quiet_mode_toggle]),
      ("recording &\nsystem", [record_front, record_mic, always_on_dm_toggle, tailscale_toggle, enable_openpilot, mads_toggle]),
    )
    self._folder_buttons = []
    for title, widgets in folders:
      panel = ToggleFolder(widgets)
      btn = BigButton(title, "")
      btn.set_click_callback(lambda panel=panel: gui_app.push_widget(panel))
      self._folder_buttons.append(btn)
    self._scroller.add_widgets(self._folder_buttons)

    # Toggle lists
    self._refresh_toggles = (
      ("ExperimentalMode", self._experimental_btn),
      ("GentleMode", gentle_toggle),
      ("IsMetric", is_metric_toggle),
      ("IsLdwEnabled", ldw_toggle),
      ("AlwaysOnDM", always_on_dm_toggle),
      ("QuietMode", quiet_mode_toggle),
      ("TailscaleEnabled", tailscale_toggle),
      ("RecordFront", record_front),
      ("RecordAudio", record_mic),
      ("OpenpilotEnabledToggle", enable_openpilot),
      ("Mads", mads_toggle),
      ("SpeedLimitControl", speed_limit_toggle),
      ("SmartCruiseControlMap", scc_map_toggle),
      ("SmartCruiseControlVision", scc_vision_toggle),
    )

    enable_openpilot.set_enabled(lambda: not ui_state.engaged)
    record_front.set_enabled(False if ui_state.params.get_bool("RecordFrontLock") else (lambda: not ui_state.engaged))
    record_mic.set_enabled(lambda: not ui_state.engaged)

    if ui_state.params.get_bool("ShowDebugInfo"):
      gui_app.set_show_touches(True)
      gui_app.set_show_fps(True)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    super()._update_state()

    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._personality_toggle.set_value(self._personality_toggle._options[personality])
      ui_state.personality = personality

  def show_event(self):
    super().show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    # CP gating for experimental mode
    if ui_state.CP is not None:
      if ui_state.has_longitudinal_control:
        self._experimental_btn.set_visible(True)
        self._personality_toggle.set_visible(True)
      else:
        # no long for now
        self._experimental_btn.set_visible(False)
        self._experimental_btn.set_checked(False)
        self._personality_toggle.set_visible(False)
        ui_state.params.remove("ExperimentalMode")

    self._speed_limit_offset.refresh()

    # Refresh toggles from params to mirror external changes
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))
