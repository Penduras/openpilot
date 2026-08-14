#!/usr/bin/env python3
import datetime
import time

import cereal.messaging as messaging
from cereal import custom, log
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.selfdrive.mapd import OSM_DOWNLOAD_PATH
from openpilot.selfdrive.mapd.actions import send_accept_speed_limit
from openpilot.selfdrive.mapd.mapd_installer import MapdInstallManager

# xnor: mapd v2 has no persistent "download this region" param - a download is only
# triggered by a one-shot mapdIn cereal message, which mapd's subscriber may not be up
# for yet on first boot. This retries every RETRY_PERIOD until mapd reports the download
# as active (or has files), then goes idle - self-healing across mapd/manager restarts
# without needing precise startup ordering.
#
# Once initial setup is done, it also re-triggers the same download periodically (picking
# up whatever OSM data is currently hosted upstream) but only while on an unmetered
# wifi/ethernet connection, so it never burns cellular data doing it.
#
# It also drives speed-limit acceptance itself rather than trusting mapd's own accept
# machinery. This was originally forced by a real bug in mapd v2.1.0 (state.go's Send()
# never called output.SetSpeedLimitAccepted(), confirmed against mapd's own source) -
# fixed in v2.3.0, but kept anyway as a second, independent mechanism rather than
# trusting the upstream fix blindly; it's harmless if redundant. mapd's own
# adjust_set_speed_to_accept_speed_limit stalk-accept path also wasn't triggering
# reliably on a real drive, so both directions are accepted automatically, immediately,
# with no driver action required either way (deliberate choice - watches
# mapdOut.speedLimitSuggestedSpeed rather than the raw mapdOut.speedLimit, since mapd's
# own SuggestNewSpeedLimit() (speed_limit.go) already pre-empts speedLimitSuggestedSpeed
# to an upcoming lower limit once within braking distance - slow_down_for_next_speed_limit
# defaults on, never overridden below - while speedLimit itself only changes once you're
# actually on the new way; using the raw field meant a lower cap only ever engaged right
# at the sign instead of decelerating into it). Sends the exact same mapdIn{acceptSpeedLimit}
# message the onroad sign's tap-to-accept uses, which IS confirmed working end-to-end.
# This needs to react quickly, so the loop runs at TICK_HZ, with the slow tasks (download
# retry, weekly update check) gated by their own elapsed-time tracking instead of the
# loop's own rate.

MapdInputType = custom.MapdInputType
NetworkType = log.DeviceState.NetworkType
TICK_HZ = 10.
RETRY_PERIOD = 15.  # seconds, between download-trigger retries
UPDATE_CHECK_INTERVAL = datetime.timedelta(days=7)  # re-check for fresher map data weekly
WIFI_LIKE_NETWORKS = (NetworkType.wifi, NetworkType.ethernet)


# mapd v2.3.0 (PR #123, "capnp-updates"/settings restructure) nested MapdSettings into
# sub-structs (speed_limit/subscriber/logger/personalities) and added a settings_version
# gate in Load() - a stored blob with no "settings_version" key reads as 0, which its
# Migrate() has no case for and panics on a nil type-assert (confirmed on a real device,
# see memory: xnor_openpilot_deploy_gotchas). "settings_version": 2 here is required to
# skip that path entirely, matching the SETTINGS_VERSION constant in mapd's settings.go.
# The sub-object keys below only need to carry what we're overriding - Default() already
# populated the full struct (including the fields we don't set here) before Load()
# unmarshals this JSON on top, so a partial nested object still merges field-by-field
# rather than zeroing out whatever it omits, same as the old flat structure did.
#
# subscriber.shadow_selfdrive_state is new here too (default off): without it, mapd never
# subscribes to selfdriveState at all, so CurrentPersonality() (map_curve.go/speed_limit.go/
# vision_curve.go) always falls through to its Standard profile regardless of the
# aggressive/standard/relaxed personality actually selected in this fork's own UI. Turning
# it on lets mapd's curve/jerk tuning follow whichever personality the driver has picked,
# instead of ignoring that choice.
MAPD_SETTINGS_VERSION = 2


def build_settings(params: Params) -> dict:
  return {
    "settings_version": MAPD_SETTINGS_VERSION,
    "speed_limit_control_enabled": params.get_bool("SpeedLimitControl"),
    "map_curve_speed_control_enabled": params.get_bool("SmartCruiseControlMap"),
    "vision_curve_speed_control_enabled": params.get_bool("SmartCruiseControlVision"),
    "subscriber": {
      "shadow_selfdrive_state": True,
    },
    "speed_limit": {
      "speed_limit_change_requires_accept": True,
      "adjust_set_speed_to_accept_speed_limit": False,
      "press_gas_to_override_speed_limit": True,
      "hold_last_seen_speed_limit": True,
    },
  }


def send_download_trigger(pm: messaging.PubMaster) -> None:
  msg = messaging.new_message('mapdIn')
  msg.mapdIn.type = MapdInputType.download
  msg.mapdIn.str = OSM_DOWNLOAD_PATH
  pm.send('mapdIn', msg)


def download_in_progress_or_done(sm: messaging.SubMaster) -> bool:
  progress = sm['mapdExtendedOut'].downloadProgress
  return bool(progress.active or progress.totalFiles > 0)


def on_unmetered_wifi(sm: messaging.SubMaster) -> bool:
  ds = sm['deviceState']
  return ds.networkType in WIFI_LIKE_NETWORKS and not ds.networkMetered


def update_check_due(params: Params) -> bool:
  last_check = params.get("OsmLastUpdateCheck")
  now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
  return last_check is None or (now - last_check) > UPDATE_CHECK_INTERVAL


class SpeedLimitAcceptWatcher:
  """Auto-accepts any resolved speed limit change immediately, no driver confirmation
  needed either direction - deliberate policy choice (not the original design: this
  used to require a cruise-stalk bump to accept an increase, but what looked like
  "auto-up" in practice turned out to be an accident - see below - and once noticed,
  full bidirectional auto-accept is what was actually wanted).

  Withholds the auto-accept while the driver has the gas pressed: mapd's pre-emptive
  lead-in (SuggestNewSpeedLimit's jerk-limited distanceToReachSpeed, in speed_limit.go)
  is a live function of car.VEgo/car.AEgo, both of which are exactly what change while
  pressing the gas to override - so the resolved suggestion can flap during an active
  override, and every accept we send resets mapd's own OverrideSpeed
  (UpdateAcceptedLimitValue zeroes it whenever AcceptedLimit doesn't match a moving
  Suggestion.Value), fighting the driver's press_gas_to_override_speed_limit input
  instead of respecting it. Gas-press is an explicit signal the driver already wants to
  exceed the limit, so there's nothing useful an auto-accept adds in that window anyway.

  (Note on the history here: the previous downward-only version relied on a
  carState.vCruise increase - a cruise-stalk bump - to accept a pending higher
  suggestion. What actually looked like automatic upward adjustment before the
  gas-press gate was added was never that path firing; speedLimitSuggestedSpeed jitters
  naturally during ordinary driving since its pre-emptive lead-in is live-computed from
  VEgo/AEgo even outside a gas-press event, which made the old downward-only trigger
  re-fire often enough to keep mapd's internal accept flag continuously "fresh" -
  and once that flag is set, mapd mirrors AcceptedLimit to Suggestion.Value regardless
  of which way it just moved. The gas-press gate reduced how often that re-firing
  happened, which broke the illusion. Rather than chase that accident, this now does
  deliberately what it looked like it was doing by accident.)
  """

  def __init__(self):
    self.last_suggested: float | None = None

  def update(self, sm: messaging.SubMaster, pm: messaging.PubMaster, params: Params) -> None:
    if not params.get_bool("SpeedLimitControl"):
      return

    gas_pressed = sm['carState'].gasPressed

    mapd_out = sm['mapdOut']
    if mapd_out.tileLoaded and mapd_out.speedLimitSuggestedSpeed > 0.:
      if not gas_pressed and self.last_suggested is not None and mapd_out.speedLimitSuggestedSpeed != self.last_suggested:
        send_accept_speed_limit(pm)
      self.last_suggested = mapd_out.speedLimitSuggestedSpeed


def main():
  params = Params()
  params.put("MapdSettings", build_settings(params))

  MapdInstallManager().check_and_download()

  pm = messaging.PubMaster(['mapdIn'])
  sm = messaging.SubMaster(['mapdExtendedOut', 'mapdOut', 'deviceState', 'carState'])
  accept_watcher = SpeedLimitAcceptWatcher()

  last_retry = 0.
  rk = Ratekeeper(TICK_HZ, print_delay_threshold=None)
  while True:
    sm.update(0)
    now = time.monotonic()

    if now - last_retry > RETRY_PERIOD:
      if not download_in_progress_or_done(sm):
        send_download_trigger(pm)
        last_retry = now
      elif update_check_due(params) and on_unmetered_wifi(sm):
        send_download_trigger(pm)
        last_retry = now
        params.put("OsmLastUpdateCheck", datetime.datetime.now(datetime.UTC).replace(tzinfo=None))

    accept_watcher.update(sm, pm, params)
    rk.keep_time()


if __name__ == "__main__":
  main()
