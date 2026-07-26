import logging
import os
import stat
import time
from pathlib import Path

import requests

from openpilot.common.params import Params
from openpilot.system.hardware.hw import Paths
from openpilot.selfdrive.mapd import MAPD_PATH, MAPD_BIN_DIR

# xnor: ported from sunnypilot/pfeiferj's mapd installer, trimmed to just the
# download-on-first-run path (no boot spinner screen, no release-branch checks).
# NOTE: v1.x used a different protocol (mem_params) than the current v2.x (cereal
# MapdIn/MapdOut messages) - make sure VERSION/URL and the schema stay in sync.
VERSION = "v2.1.0"
URL = f"https://github.com/pfeiferj/mapd/releases/download/{VERSION}/mapd"


def update_installed_version(version: str, params: Params | None = None) -> None:
  if params is None:
    params = Params()

  params.put("MapdVersion", version)


class MapdInstallManager:
  def __init__(self):
    self._params = Params()

  def download(self) -> None:
    self.ensure_directories_exist()
    self._download_file()
    update_installed_version(VERSION, self._params)

  def check_and_download(self) -> None:
    if self.download_needed():
      self.download()

  def download_needed(self) -> bool:
    return not os.path.exists(MAPD_PATH) or self.get_installed_version() != VERSION

  @staticmethod
  def ensure_directories_exist() -> None:
    if not os.path.exists(Paths.mapd_root()):
      os.makedirs(Paths.mapd_root())
    if not os.path.exists(MAPD_BIN_DIR):
      os.makedirs(MAPD_BIN_DIR)

  @staticmethod
  def _safe_write_and_set_executable(file_path: Path, content: bytes) -> None:
    with open(file_path, 'wb') as output:
      output.write(content)
      output.flush()
      os.fsync(output.fileno())
    current_permissions = stat.S_IMODE(os.lstat(file_path).st_mode)
    os.chmod(file_path, current_permissions | stat.S_IEXEC)

  def _download_file(self, num_retries=5) -> None:
    temp_file = Path(MAPD_PATH + ".tmp")
    download_timeout = 60
    for cnt in range(num_retries):
      try:
        response = requests.get(URL, stream=True, timeout=download_timeout)
        response.raise_for_status()
        self._safe_write_and_set_executable(temp_file, response.content)
        # No exceptions encountered. Safe to replace original file.
        temp_file.replace(MAPD_PATH)
        return
      except requests.exceptions.RequestException as e:
        logging.warning(f"mapd: download attempt {cnt} failed: {e}")
        time.sleep(0.5)

    if temp_file.exists():
      temp_file.unlink()
    logging.error("mapd: failed to download after all retries")

  def get_installed_version(self) -> str:
    return str(self._params.get("MapdVersion") or "")
