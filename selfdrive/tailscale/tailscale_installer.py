import logging
import os
import stat
import tarfile
import time
from io import BytesIO

import requests

from openpilot.common.params import Params
from openpilot.selfdrive.tailscale import TAILSCALE_DIR, TAILSCALED_PATH, TAILSCALE_CLI_PATH

# xnor: static/portable tailscale build for arm64 Linux - same "no package manager, no
# root-filesystem writes" pattern as mapd_installer.py, needed because AGNOS's root
# filesystem is mounted read-only (apt/systemd-unit-file installs aren't possible here).
# "_latest_arm64.tgz" is a stable alias Tailscale's own CDN maintains for exactly this
# kind of unattended install - resolved to a real, size-verified release when this was
# validated by hand (tailscale_1.102.2_arm64.tgz, ~35.7MB) before this toggle existed.
#
# The tarball wraps its contents in a version-named top-level directory
# (tailscale_<ver>_arm64/tailscaled, .../tailscale, plus a systemd/ dir we don't need),
# so extraction matches by basename rather than a fixed path - robust to version bumps
# without needing to know the exact wrapping directory name ahead of time.
URL = "https://pkgs.tailscale.com/stable/tailscale_latest_arm64.tgz"
WANTED_FILES = ("tailscaled", "tailscale")


def mark_installed(params: Params | None = None) -> None:
  if params is None:
    params = Params()
  params.put_bool("TailscaleInstalled", True)


class TailscaleInstallManager:
  def __init__(self):
    self._params = Params()

  def download(self) -> None:
    self.ensure_directories_exist()
    if self._download_and_extract():
      mark_installed(self._params)

  def check_and_download(self) -> None:
    if self.download_needed():
      self.download()

  def download_needed(self) -> bool:
    return not (os.path.exists(TAILSCALED_PATH) and os.path.exists(TAILSCALE_CLI_PATH))

  @staticmethod
  def ensure_directories_exist() -> None:
    if not os.path.exists(TAILSCALE_DIR):
      os.makedirs(TAILSCALE_DIR)

  @staticmethod
  def _extract_member(tar: tarfile.TarFile, member: tarfile.TarInfo, dest: str) -> None:
    extracted = tar.extractfile(member)
    if extracted is None:
      return
    with open(dest, 'wb') as output:
      output.write(extracted.read())
      output.flush()
      os.fsync(output.fileno())
    current_permissions = stat.S_IMODE(os.lstat(dest).st_mode)
    os.chmod(dest, current_permissions | stat.S_IEXEC)

  def _download_and_extract(self, num_retries=5) -> bool:
    download_timeout = 60
    for cnt in range(num_retries):
      try:
        response = requests.get(URL, stream=True, timeout=download_timeout)
        response.raise_for_status()
        with tarfile.open(fileobj=BytesIO(response.content), mode='r:gz') as tar:
          for member in tar.getmembers():
            if member.isfile() and os.path.basename(member.name) in WANTED_FILES:
              self._extract_member(tar, member, os.path.join(TAILSCALE_DIR, os.path.basename(member.name)))
        return not self.download_needed()
      except (requests.exceptions.RequestException, tarfile.TarError) as e:
        logging.warning(f"tailscale: download attempt {cnt} failed: {e}")
        time.sleep(0.5)

    logging.error("tailscale: failed to download after all retries")
    return False
