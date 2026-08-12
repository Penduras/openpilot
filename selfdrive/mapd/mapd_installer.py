import logging
import os
import stat
import time
from pathlib import Path

import requests

from openpilot.common.params import Params
from openpilot.selfdrive.mapd import MAPD_PATH, MAPD_BIN_DIR

# xnor: ported from sunnypilot/pfeiferj's mapd installer, trimmed to just the
# download-on-first-run path (no boot spinner screen, no release-branch checks).
# NOTE: v1.x used a different protocol (mem_params) than the current v2.x (cereal
# MapdIn/MapdOut messages) - make sure VERSION/URL and the schema stay in sync.
#
# v2.1.0 -> v2.3.0, second attempt: the first attempt crash-looped because
# v2.3.0 added a settings_version gate to Load() and our MapdSettings param had
# no such key (see the retry with an actual fix in mapd_config.py's
# build_settings(), and memory: xnor_openpilot_deploy_gotchas for the full
# incident). build_settings() now writes settings_version and the correct
# nested speed_limit/subscriber sub-objects for v2.3.0's actual schema,
# verified by parsing the real v2.3.0 settings.go struct definitions rather
# than guessing. Also fixes the speedLimitAccepted bug (our SpeedLimitAcceptWatcher
# workaround stays in place regardless) and a signed-vs-magnitude bug in vision
# curve detection that likely made SCC-Vision only react to curves one way.
VERSION = "v2.3.0"
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
    # xnor: only record the version as installed if the download actually succeeded -
    # this used to be unconditional, which let a real crash-looping binary sit on disk
    # silently marked "installed" after a boot-time network hiccup meant the download
    # of a downgrade attempt (v2.3.0 -> v2.1.0) never actually happened. The old
    # (crashing) binary stayed in place while download_needed() saw the versions match
    # and stopped retrying entirely - only caught by manually inspecting the binary
    # over SSH, not by anything this installer reported.
    if self._download_file():
      update_installed_version(VERSION, self._params)

  def check_and_download(self) -> None:
    if self.download_needed():
      self.download()

  def download_needed(self) -> bool:
    return not os.path.exists(MAPD_PATH) or self.get_installed_version() != VERSION

  @staticmethod
  def ensure_directories_exist() -> None:
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

  def _download_file(self, num_retries=5) -> bool:
    temp_file = Path(MAPD_PATH + ".tmp")
    download_timeout = 60
    for cnt in range(num_retries):
      try:
        response = requests.get(URL, stream=True, timeout=download_timeout)
        response.raise_for_status()
        self._safe_write_and_set_executable(temp_file, response.content)
        # No exceptions encountered. Safe to replace original file.
        temp_file.replace(MAPD_PATH)
        return True
      except requests.exceptions.RequestException as e:
        logging.warning(f"mapd: download attempt {cnt} failed: {e}")
        time.sleep(0.5)

    if temp_file.exists():
      temp_file.unlink()
    logging.error("mapd: failed to download after all retries")
    return False

  def get_installed_version(self) -> str:
    return str(self._params.get("MapdVersion") or "")
