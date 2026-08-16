import openpilot.cereal.messaging as messaging
from openpilot.cereal import custom

# xnor: small shared helper so mapd_config.py's auto-accept watcher and the onroad sign's
# tap-to-accept gesture don't each hand-roll the same message construction.


def send_accept_speed_limit(pm: messaging.PubMaster) -> None:
  msg = messaging.new_message('mapdIn')
  msg.mapdIn.type = custom.MapdInputType.acceptSpeedLimit
  pm.send('mapdIn', msg)
