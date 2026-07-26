import os

from openpilot.common.basedir import BASEDIR

MAPD_BIN_DIR = os.path.join(BASEDIR, 'third_party/mapd_pfeiferj')
MAPD_PATH = os.path.join(MAPD_BIN_DIR, 'mapd')

# xnor: hardcoded OSM download region (no country/state picker UI ported)
OSM_DOWNLOAD_NATIONS = ["Norway", "Sweden", "Finland"]
