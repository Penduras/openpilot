import os

from openpilot.common.hardware.hw import Paths

# xnor: deliberately NOT inside the git checkout (e.g. selfdrive/) - comma's updated.py
# does a git-clean-style wipe of untracked files during its overlay finalize cycle, which
# was silently deleting the downloaded binary shortly after every install. Paths.mapd_root()
# lives under /data/media/0, entirely outside the repo tree, so it survives update cycles.
MAPD_BIN_DIR = Paths.mapd_root()
MAPD_PATH = os.path.join(MAPD_BIN_DIR, 'mapd')

# xnor: hardcoded OSM download region (no country/state picker UI ported).
# ISO 3166-1 alpha-2 codes as used by mapd's settings/download_menu.json "nation" menu.
OSM_DOWNLOAD_PATH = "nation.NO,nation.SE,nation.FI"
