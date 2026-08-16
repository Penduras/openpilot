# xnor-openpilot (Penduras fork)

Personal fork of xnor-tech/openpilot, running on a **Comma Four ("mici")** device in a
**Tesla Model S HW3** via xnor's `tesla_legacy` panda safety mode. Owner/git identity:
`Penduras` (GitHub). This file is read automatically at the start of every Claude Code
session in this repo, on any machine — treat it as the durable, portable memory for this
project; the assistant's own local memory notes (deploy gotchas, architecture detail) may
only exist on whichever machine wrote them, so don't assume they're loaded.

## Device access

- Comma reachable via SSH: `comma@192.168.1.193` (home LAN) or `comma@100.125.74.75`
  (Tailscale — works off-LAN too, e.g. mid-drive). No static `authorized_keys` file on
  the device; SSH access is driven entirely by the `GithubUsername`/`GithubSshKeys`
  params, synced (one-shot, NOT automatic) from `https://github.com/<user>.keys`.
- Correct Python for one-off on-device checks: `/usr/local/venv/bin/python3` with cwd
  `/data/openpilot` (bare `python3` lacks `zmq`; a script run as a *file* rather than
  via `-c`/`-m` breaks `import openpilot...` — the repo root has a self-referencing
  `openpilot -> .` symlink that only resolves when cwd is on `sys.path`).
- **`manager.py` preimports every process module at its own startup.** A `git pull`
  alone does NOT apply a code change to an already-running preimported process — always
  `sudo reboot` after deploying and verify the *new* commit hash appears in fresh
  swaglog entries, not just `git log`.
- Multi-repo structure: main repo + `opendbc_repo` (`Penduras/opendbc`) and `panda`
  (`Penduras/panda`) git submodules, both with their own `dev` branches mirroring the
  main repo's — schema/firmware changes need commits in the relevant submodule(s), plus
  a submodule-bump commit in the main repo. A submodule pointer can auto-merge cleanly
  during a big merge and still silently end up on the wrong commit (no conflict ever
  flags it) — don't assume a clean merge means every submodule pointer actually moved
  where it should have; check each one explicitly.
- Validation workflow: WSL Ubuntu-24.04 at `~/openpilot_dev/openpilot` for real
  `capnp compile`/`scons`/`py_compile`/`ruff check` before every deploy.

## What's built

Speed Limit Control / Smart Cruise Control - Map & Vision (mapd v2.3.0,
`github.com/pfeiferj/mapd`), Tesla cruise-stalk-cancel wired to a real disengage event,
sunnypilot's Quiet Mode, a Tailscale on/off settings toggle for off-LAN reachability, and
a driver-override easing feature for angle-controlled steering (`latcontrol_angle.py`)
that blends toward the driver's actual angle while they're overriding instead of fighting
them. Full detail on how each of these actually works, and the real incidents that shaped
them (a SIGBUS crash from a mismatched cereal queue size, an mapd v2.3.0 settings-schema
migration panic, a race condition between this fork's speed-limit accept-watcher and
mapd's own internal accept-flag, a personality-scoped default that silently activated,
resolved 2026-08-16: the mapd `tileLoaded` stuck bug below, and — on `dev` only as of
2026-08-16, not yet merged to `main` — a real safety-relevant fix to the steering-override
easing that could otherwise trip a hard EPAS fault mid-corner), is worth asking the
assistant about — it maintains its own more detailed notes on this, separate from this
file.

## Working practices

- **After finishing a feature or bug fix, write or update a memory note about it** —
  this assistant's own persistent memory (not this file), at whatever path this session
  uses for it (e.g. `~/.claude/projects/<...>/memory/` — check your own environment).
  Cover what changed, why, and any non-obvious root cause. Do this on your own
  judgment, without being asked — it's how a fresh session, which has no access to this
  conversation's history, actually picks up where the last one left off. Follow the
  existing memory files' conventions: one fact per file, link related notes with
  `[[name]]`, add a one-line pointer to the `MEMORY.md` index.

## Resolved: mapd `tileLoaded: false` stuck bug

Root-caused and fixed 2026-08-16 (previously documented here as an open issue with no
known root cause). mapd has no persistent "do I already have this data" state, so any
restart re-triggers its entire configured-region download from scratch with no resume
logic — and mapd's own main loop is single-threaded, so GPS/position-checking doesn't
run at all while a download is in progress. Fixed via a disk-based check in
`mapd_config.py` (`has_existing_map_data()`) that skips the redundant redownload trigger
when real map data already exists on disk. Ask the assistant for the full incident
detail (how it was actually diagnosed — capturing mapd's own stdout/stderr for the first
time, and reading mapd's real Go source — is worth knowing if a similar third-party
binary issue comes up again).

## Gotchas worth knowing before touching things

- `Widget` (`system/ui/widgets/__init__.py`) has read-only properties with no setter:
  `rect`, `is_pressed`, `enabled`, `is_visible`, `_hit_rect` — shadowing one of these as
  an instance attribute in a subclass crashes the *entire* onroad UI process at boot,
  not just that widget.
- Inline `ssh host "cmd with $var"` or backticks in a `git commit -m "..."` gets
  expanded/executed by the *local* shell before it ever reaches its destination —
  silently corrupts nginx configs, DB values, or drops text from commit messages. Use a
  heredoc file or `-F`/`< script` instead, and verify the actual result afterward.
