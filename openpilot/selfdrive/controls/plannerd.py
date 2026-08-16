#!/usr/bin/env python3
from opendbc.car.structs import car
from openpilot.common.params import Params
from openpilot.common.realtime import Priority, config_realtime_process
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.controls.lib.ldw import LaneDepartureWarning
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
import openpilot.cereal.messaging as messaging


def main():
  config_realtime_process(5, Priority.CTRL_LOW)

  cloudlog.info("plannerd is waiting for CarParams")
  params = Params()
  CP = messaging.log_from_bytes(params.get("CarParams", block=True), car.CarParams)
  cloudlog.info("plannerd got CarParams: %s", CP.brand)

  ldw = LaneDepartureWarning()
  longitudinal_planner = LongitudinalPlanner(CP)
  pm = messaging.PubMaster(['longitudinalPlan', 'driverAssistance'])
  # xnor: mapdOut is a best-effort background feature's output (see selfdrived.py's
  # ignored_processes, ported from sunnypilot PR #1880 for the same underlying reason) -
  # excluded from alive/freq/valid checks so a transient mapd hiccup can't flip
  # driverAssistance.valid via sm.all_checks() below, which (unlike the old whitelist-
  # based all_checks(['carState', ...]) this fork used to call) now checks every
  # subscribed service by default since upstream's plannerd rewrite.
  mapd_ignore = ['mapdOut']
  sm = messaging.SubMaster(['carControl', 'carState', 'controlsState', 'vehicleParameters', 'radarState', 'modelV2', 'selfdriveState',
                            'mapdOut'],
                           poll='modelV2', ignore_alive=mapd_ignore, ignore_avg_freq=mapd_ignore, ignore_valid=mapd_ignore)

  while True:
    sm.update()
    if sm.updated['modelV2']:
      longitudinal_planner.update(sm)
      longitudinal_planner.publish(sm, pm)

      ldw.update(sm.frame, sm['modelV2'], sm['carState'], sm['carControl'])
      msg = messaging.new_message('driverAssistance')
      msg.valid = sm.all_checks()
      msg.driverAssistance.leftLaneDeparture = ldw.left
      msg.driverAssistance.rightLaneDeparture = ldw.right
      pm.send('driverAssistance', msg)


if __name__ == "__main__":
  main()
