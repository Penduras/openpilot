import os

from openpilot.common.basedir import BASEDIR

MAPD_BIN_DIR = os.path.join(BASEDIR, 'selfdrive', 'mapd')
MAPD_PATH = os.path.join(MAPD_BIN_DIR, 'mapd')

# xnor: hardcoded OSM download region (no country/state picker UI ported).
# ISO 3166-1 alpha-2 codes as used by mapd's settings/download_menu.json "nation" menu.
OSM_DOWNLOAD_PATH = "nation.NO,nation.SE,nation.FI"
