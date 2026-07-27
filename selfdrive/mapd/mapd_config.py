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
# It also auto-accepts any new speed limit that's LOWER than the last one the driver
# accepted - mapd's own speed_limit_change_requires_accept is a blanket flag with no
# direction awareness, so this bridges "always confirm going faster, never need to
# confirm going slower". Upward changes are left alone; they still require the driver to
# either bump the cruise stalk (adjust_set_speed_to_accept_speed_limit) or tap the onroad
# sign. This needs to react quickly, so the loop runs at TICK_HZ, with the slow tasks
# (download retry, weekly update check) gated by their own elapsed-time tracking instead
# of the loop's own rate.

MapdInputType = custom.MapdInputType
NetworkType = log.DeviceState.NetworkType
TICK_HZ = 10.
RETRY_PERIOD = 15.  # seconds, between download-trigger retries
UPDATE_CHECK_INTERVAL = datetime.timedelta(days=7)  # re-check for fresher map data weekly
WIFI_LIKE_NETWORKS = (NetworkType.wifi, NetworkType.ethernet)


def build_settings(params: Params) -> dict:
  return {
    "speed_limit_control_enabled": params.get_bool("SpeedLimitControl"),
    "speed_limit_change_requires_accept": True,
    "adjust_set_speed_to_accept_speed_limit": True,
    "press_gas_to_override_speed_limit": True,
    "hold_last_seen_speed_limit": True,
    "map_curve_speed_control_enabled": params.get_bool("SmartCruiseControlMap"),
    "vision_curve_speed_control_enabled": params.get_bool("SmartCruiseControlVision"),
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


class DownwardAutoAccept:
  """Auto-accepts a new speed limit the instant it's lower than the last accepted one."""

  def __init__(self):
    self.last_accepted: float | None = None

  def update(self, sm: messaging.SubMaster, pm: messaging.PubMaster) -> None:
    mapd_out = sm['mapdOut']
    if not (mapd_out.tileLoaded and mapd_out.speedLimit > 0.):
      return

    if mapd_out.speedLimitAccepted:
      self.last_accepted = mapd_out.speedLimit
    elif self.last_accepted is not None and mapd_out.speedLimit < self.last_accepted:
      send_accept_speed_limit(pm)


def main():
  params = Params()
  params.put("MapdSettings", build_settings(params))

  MapdInstallManager().check_and_download()

  pm = messaging.PubMaster(['mapdIn'])
  sm = messaging.SubMaster(['mapdExtendedOut', 'mapdOut', 'deviceState'])
  auto_accept = DownwardAutoAccept()

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

    auto_accept.update(sm, pm)
    rk.keep_time()


if __name__ == "__main__":
  main()
