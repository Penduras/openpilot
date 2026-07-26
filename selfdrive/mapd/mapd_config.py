#!/usr/bin/env python3
import cereal.messaging as messaging
from cereal import custom
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.selfdrive.mapd import OSM_DOWNLOAD_PATH
from openpilot.selfdrive.mapd.mapd_installer import MapdInstallManager

# xnor: mapd v2 has no persistent "download this region" param - a download is only
# triggered by a one-shot mapdIn cereal message, which mapd's subscriber may not be up
# for yet on first boot. This retries every RETRY_PERIOD until mapd reports the download
# as active (or has files), then goes idle - self-healing across mapd/manager restarts
# without needing precise startup ordering.

MapdInputType = custom.MapdInputType
RETRY_PERIOD = 15.  # seconds


def build_settings(params: Params) -> dict:
  return {
    "speed_limit_control_enabled": params.get_bool("SpeedLimitControl"),
    "speed_limit_change_requires_accept": True,
    "adjust_set_speed_to_accept_speed_limit": True,
    "hold_last_seen_speed_limit": True,
  }


def send_download_trigger(pm: messaging.PubMaster) -> None:
  msg = messaging.new_message('mapdIn')
  msg.mapdIn.type = MapdInputType.download
  msg.mapdIn.str = OSM_DOWNLOAD_PATH
  pm.send('mapdIn', msg)


def download_in_progress_or_done(sm: messaging.SubMaster) -> bool:
  progress = sm['mapdExtendedOut'].downloadProgress
  return bool(progress.active or progress.totalFiles > 0)


def main():
  params = Params()
  params.put("MapdSettings", build_settings(params))

  MapdInstallManager().check_and_download()

  pm = messaging.PubMaster(['mapdIn'])
  sm = messaging.SubMaster(['mapdExtendedOut'])

  rk = Ratekeeper(1 / RETRY_PERIOD, print_delay_threshold=None)
  while True:
    sm.update(0)
    if not download_in_progress_or_done(sm):
      send_download_trigger(pm)
    rk.keep_time()


if __name__ == "__main__":
  main()
