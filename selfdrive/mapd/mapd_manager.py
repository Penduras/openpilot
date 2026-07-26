#!/usr/bin/env python3
import json
import os
import platform

import cereal.messaging as messaging
from openpilot.common.gps import get_gps_location_service
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper, config_realtime_process
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.mapd import OSM_DOWNLOAD_NATIONS
from openpilot.selfdrive.mapd.coordinate import Coordinate, coordinate_from_param
from openpilot.selfdrive.mapd.mapd_installer import VERSION, MapdInstallManager, update_installed_version
from openpilot.system.hardware.hw import Paths

# xnor: ported from sunnypilot's mapd_manager + live_map_data (base_map_data.py + osm_map_data.py merged).
# Simplified: no country/state picker (region is hardcoded), no offroad re-download-alert flow.
#
# Data flow: this process feeds our GPS position to the mapd binary via shared-memory params,
# reads back the speed limit it resolved from its local OSM database, and republishes it as the
# liveMapDataSP cereal message that SpeedLimitResolver consumes.

MAX_SPEED_LIMIT = 255. * (1000. / 3600.)  # m/s, matches V_CRUISE_UNSET in km/h


class OsmMapData:
  def __init__(self):
    self.params = Params()
    self.mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else self.params

    # xnor: this fork has no fused liveLocationKalman - use the raw GPS fix directly,
    # matching what SpeedLimitResolver already keys its own fix-age check off of.
    self._gps_service = get_gps_location_service(self.params)
    self.sm = messaging.SubMaster([self._gps_service])
    self.pm = messaging.PubMaster(['liveMapDataSP'])

    self.last_bearing: float | None = None
    self.last_position = coordinate_from_param("LastGPSPositionLLK", self.params)

  def update_location(self) -> None:
    gps = self.sm[self._gps_service]

    if self.sm.valid[self._gps_service]:
      self.last_bearing = gps.bearingDeg
      self.last_position = Coordinate(gps.latitude, gps.longitude)

    if self.last_position is None:
      return

    params = {
      "latitude": self.last_position.latitude,
      "longitude": self.last_position.longitude,
    }
    if self.last_bearing is not None:
      params['bearing'] = self.last_bearing

    self.mem_params.put("LastGPSPosition", json.dumps(params))
    self.params.put("LastGPSPositionLLK", json.dumps(params))

  def get_current_speed_limit(self) -> float:
    return float(self.mem_params.get("MapSpeedLimit") or 0.0)

  def get_current_road_name(self) -> str:
    return str(self.mem_params.get("RoadName") or "")

  def get_next_speed_limit_and_distance(self) -> tuple[float, float]:
    # NextMapSpeedLimit is a JSON-typed param - Params.get() already returns a decoded dict.
    next_speed_limit_section = self.mem_params.get("NextMapSpeedLimit") or {}
    next_speed_limit = next_speed_limit_section.get('speedlimit', 0.0)
    next_speed_limit_latitude = next_speed_limit_section.get('latitude')
    next_speed_limit_longitude = next_speed_limit_section.get('longitude')
    next_speed_limit_distance = 0.0

    if next_speed_limit_latitude and next_speed_limit_longitude:
      next_speed_limit_coordinates = Coordinate(next_speed_limit_latitude, next_speed_limit_longitude)
      next_speed_limit_distance = (self.last_position or Coordinate(0, 0)).distance_to(next_speed_limit_coordinates)

    return next_speed_limit, next_speed_limit_distance

  def publish(self) -> None:
    speed_limit = self.get_current_speed_limit()
    next_speed_limit, next_speed_limit_distance = self.get_next_speed_limit_and_distance()

    mapd_sp_send = messaging.new_message('liveMapDataSP')
    mapd_sp_send.valid = self.sm.valid[self._gps_service]
    live_map_data = mapd_sp_send.liveMapDataSP

    live_map_data.speedLimitValid = bool(MAX_SPEED_LIMIT > speed_limit > 0)
    live_map_data.speedLimit = speed_limit
    live_map_data.speedLimitAheadValid = bool(MAX_SPEED_LIMIT > next_speed_limit > 0)
    live_map_data.speedLimitAhead = next_speed_limit
    live_map_data.speedLimitAheadDistance = next_speed_limit_distance
    live_map_data.roadName = self.get_current_road_name()

    self.pm.send('liveMapDataSP', mapd_sp_send)

  def tick(self) -> None:
    self.sm.update(0)
    self.update_location()
    self.publish()


def init_osm_download_region(mem_params: Params) -> None:
  mem_params.put("OSMDownloadLocations", {"nations": OSM_DOWNLOAD_NATIONS, "states": []})
  if not mem_params.get("OSMDownloadBounds"):
    mem_params.put("OSMDownloadBounds", "")
  if not mem_params.get("LastGPSPosition"):
    mem_params.put("LastGPSPosition", "{}")


def main_thread():
  params = Params()
  mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else params

  install_manager = MapdInstallManager()
  install_manager.ensure_directories_exist()
  install_manager.check_and_download()
  update_installed_version(VERSION, params)

  config_realtime_process([0, 1, 2, 3], 5)

  rk = Ratekeeper(1, print_delay_threshold=None)
  live_map_sp = OsmMapData()

  try:
    os.mkdir(Paths.mapd_root())
  except FileExistsError:
    pass
  except PermissionError:
    cloudlog.exception(f"mapd: failed to make {Paths.mapd_root()}")

  init_osm_download_region(mem_params)

  while True:
    live_map_sp.tick()
    rk.keep_time()


def main():
  main_thread()


if __name__ == "__main__":
  main()
