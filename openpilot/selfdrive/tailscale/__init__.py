import os

# xnor: like mapd (selfdrive/mapd/__init__.py), deliberately outside the git checkout -
# comma's updated.py git-clean-wipes untracked files inside the repo tree on every
# update cycle, which would silently delete the downloaded binary and auth state
# otherwise. /data/tailscale is a sibling of /data/openpilot, not inside it, so it's
# untouched by that wipe. Matches the exact layout set up and validated by hand on a
# real device before this toggle existed (see memory: xnor_openpilot_deploy_gotchas).
TAILSCALE_DIR = "/data/tailscale"
TAILSCALED_PATH = os.path.join(TAILSCALE_DIR, "tailscaled")
TAILSCALE_CLI_PATH = os.path.join(TAILSCALE_DIR, "tailscale")
TAILSCALE_STATE_DIR = os.path.join(TAILSCALE_DIR, "state")
TAILSCALE_SOCKET_PATH = os.path.join(TAILSCALE_DIR, "tailscaled.sock")

# xnor: transient systemd unit name (systemd-run, no on-disk unit file - AGNOS's root
# filesystem is read-only, confirmed via `mount | grep ' / '` on a real device, so a
# normal persistent `systemctl enable` unit can't be written to /etc).
TAILSCALED_UNIT = "tailscaled"
