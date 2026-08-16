"""
Ported from sunnypilot (selfdrive/ui/quiet_mode.py, release-mici) - self-contained,
no changes needed for this fork.

Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.
Adapted under the MIT License. See LICENSE.md.
"""
from openpilot.cereal import log

from openpilot.common.params import Params

# xnor: was car.CarControl.HUDControl.AudibleAlert (the old signal-level enum) - updated
# during the xnor-dev resync merge (2026-08-15) to match what soundd.py actually compares
# against now (sm['selfdriveState'].alertSound.raw, log.SelfdriveState.AudibleAlert) since
# upstream added that struct-native enum; the two enums aren't guaranteed to share the
# same underlying ordinals, so comparing against the wrong one would have silently broken
# every comparison in this file.
AudibleAlert = log.SelfdriveState.AudibleAlert

ALERTS_ALWAYS_PLAY = {
  AudibleAlert.warningSoft,
  AudibleAlert.warningImmediate,
  AudibleAlert.promptDistracted,
  AudibleAlert.promptRepeat,
}


class QuietMode:
  def __init__(self):
    self.params = Params()
    self.enabled: bool = self.params.get_bool("QuietMode")
    self._frame = 0

  def load_param(self) -> None:
    self._frame += 1
    if self._frame % 50 == 0:  # 2.5 seconds
      self.enabled = self.params.get_bool("QuietMode")

  def should_play_sound(self, current_alert: int) -> bool:
    """
    Check if a sound should be played based on the Quiet Mode setting
    and the current alert.
    """
    if not self.enabled:
      return bool(current_alert != AudibleAlert.none)

    return current_alert in ALERTS_ALWAYS_PLAY
