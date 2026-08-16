#!/usr/bin/env python3
import subprocess

from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.selfdrive.tailscale import TAILSCALED_PATH, TAILSCALE_STATE_DIR, TAILSCALE_SOCKET_PATH, TAILSCALED_UNIT
from openpilot.selfdrive.tailscale.tailscale_installer import TailscaleInstallManager

# xnor: starts/stops tailscaled as a *transient* systemd unit (systemd-run, not a
# persistent unit file) in step with the TailscaleEnabled toggle. AGNOS's root
# filesystem is read-only (confirmed via `mount | grep ' / '` on a real device), so a
# normal `systemctl enable`-style persistent unit can't be written to /etc - systemd-run
# needs no on-disk unit file at all. Tailscale's own state (node key, auth) persists
# under TAILSCALE_STATE_DIR on the writable /data partition regardless of how many times
# the transient unit itself is started/stopped, so toggling this off and back on later
# reconnects as the same already-authorized device - no re-authentication needed.
#
# manager.py's processes run as the unprivileged "comma" user (confirmed via `ps aux` on
# a real device), not root, so the systemd calls below need sudo - matches how this was
# driven by hand before this toggle existed. sudo is passwordless for this user
# (confirmed via `sudo -n true`), so this never blocks waiting on a password prompt.
#
# First-time setup is NOT automated here: `tailscale up` requires a human to visit a
# login URL and approve the device in a browser, which can't happen unassisted. This
# watcher only ever starts/stops the daemon - if TAILSCALE_STATE_DIR has no prior auth,
# tailscaled comes up but sits unauthenticated (NeedsLogin) until someone runs
# `tailscale up` manually once. After that, this toggle purely controls whether the
# already-authorized daemon is running.
#
# Only starts/stops a background daemon, so there's no need to react instantly - polls
# every POLL_PERIOD instead of running a tight loop like mapd_config.py's speed-limit
# path does.
POLL_PERIOD = 5.  # seconds


def tailscaled_active() -> bool:
  result = subprocess.run(["systemctl", "is-active", TAILSCALED_UNIT], capture_output=True, text=True, check=False)
  return result.stdout.strip() == "active"


def start_tailscaled() -> None:
  subprocess.run([
    "sudo", "systemd-run", f"--unit={TAILSCALED_UNIT}", "--description=Tailscale (xnor toggle)",
    TAILSCALED_PATH, f"--statedir={TAILSCALE_STATE_DIR}", f"--socket={TAILSCALE_SOCKET_PATH}",
  ], check=False)


def stop_tailscaled() -> None:
  subprocess.run(["sudo", "systemctl", "stop", TAILSCALED_UNIT], check=False)


def main():
  params = Params()
  installer = TailscaleInstallManager()

  rk = Ratekeeper(1. / POLL_PERIOD, print_delay_threshold=None)
  while True:
    enabled = params.get_bool("TailscaleEnabled")

    if enabled:
      installer.check_and_download()

    active = tailscaled_active()
    if enabled and not active:
      start_tailscaled()
    elif not enabled and active:
      stop_tailscaled()

    rk.keep_time()


if __name__ == "__main__":
  main()
