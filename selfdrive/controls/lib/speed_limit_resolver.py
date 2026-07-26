import time

import cereal.messaging as messaging
from cereal import custom
from openpilot.common.gps import get_gps_location_service
from openpilot.common.params import Params

# xnor: ported from sunnypilot's SpeedLimitResolver, trimmed down since Tesla has no native
# speed-limit CAN signal - map data (mapd) is the only source, so the multi-source policy
# system (car/map/combined) doesn't apply here.
LIMIT_MAX_MAP_DATA_AGE = 10.  # s Maximum time to hold map data before considering it invalid.

SpeedLimitSource = custom.LongitudinalPlanSP.SpeedLimit.Source


class SpeedLimitResolver:
  def __init__(self):
    self.params = Params()
    self._gps_location_service = get_gps_location_service(self.params)

    self.v_ego = 0.
    self.source = SpeedLimitSource.none
    self.distance = 0.

    self.speed_limit = 0.
    self.speed_limit_last = 0.
    self.speed_limit_final = 0.
    self.speed_limit_final_last = 0.
    self.speed_limit_offset = 0.  # TODO-xnor: expose an offset setting, hardcoded to 0 for now

  def update_speed_limit_states(self) -> None:
    self.speed_limit_final = self.speed_limit + self.speed_limit_offset

    if self.speed_limit > 0.:
      self.speed_limit_last = self.speed_limit
      self.speed_limit_final_last = self.speed_limit_final

  @property
  def speed_limit_valid(self) -> bool:
    return self.speed_limit > 0.

  @property
  def speed_limit_last_valid(self) -> bool:
    return self.speed_limit_last > 0.

  def _resolve_from_map_data(self, sm: messaging.SubMaster) -> tuple[float, float]:
    gps_data = sm[self._gps_location_service]
    map_data = sm['liveMapDataSP']

    gps_fix_age = time.monotonic() - gps_data.unixTimestampMillis * 1e-3
    if gps_fix_age > LIMIT_MAX_MAP_DATA_AGE:
      return 0., 0.

    speed_limit = map_data.speedLimit if map_data.speedLimitValid else 0.
    return speed_limit, 0.

  def update(self, v_ego: float, sm: messaging.SubMaster) -> None:
    self.v_ego = v_ego

    speed_limit, distance = self._resolve_from_map_data(sm)
    self.source = SpeedLimitSource.map if speed_limit > 0. else SpeedLimitSource.none
    self.speed_limit, self.distance = speed_limit, distance

    self.update_speed_limit_states()
