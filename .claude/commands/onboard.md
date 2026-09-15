---
description: Orient a fresh session on this project and confirm the dev environment is ready
---

Do these three things, in order, then stop and report back — don't start any other
work yet:

1. Read `CLAUDE.md` (repo root) and summarize what you now know about this project.

2. If it exists on this machine, read every file in
   `/root/.claude/projects/-workspace-xnor-openpilot/memory/` (start with `MEMORY.md`)
   for the deeper technical notes — real incidents, architecture detail, and gotchas
   that don't fit in CLAUDE.md. If that path doesn't exist here, say so and skip it;
   it's specific to the Plex-hosted container.

3. Quick sanity check only, not a rebuild: confirm the dev toolchain still works —
   `uv sync --extra testing --extra tools` (the `dev`/`docs` extras no longer exist as
   of the 2026-08 xnor-dev resync — `dev`'s only member folded into `tools`, `docs` was
   dropped; `tools`'s `metadrive-simulator` line is itself commented out in
   `pyproject.toml`, so this extra is now just `matplotlib` + native libs, and it's
   actually REQUIRED — `scons` needs `tools`'s `ncurses` dep just to read `SConstruct`.
   Do NOT add `--all-extras`. If `pyproject.toml`'s extras ever change again, re-derive
   the right flags from the file directly (`grep -n "optional-dependencies" -A 30
   pyproject.toml`) rather than trusting this note blindly), `capnp compile` +
   `scons -j8 openpilot/cereal/` (note the `openpilot/` prefix — this repo adopted an
   `openpilot/`-rooted layout in the 2026-08 resync, so it's no longer bare `cereal/`),
   `python3 -m py_compile` and `ruff check` against this fork's actual changes
   (`openpilot/selfdrive/mapd/`, `openpilot/selfdrive/tailscale/`). This was fully
   validated clean on 2026-09-14, so it should be fast — just confirm and note anything
   that doesn't pass, don't go debugging a problem that probably isn't there.

Then give a short status summary: what you learned, and whether the environment is
ready to work in.

One standing practice for the rest of this session, not just this onboarding pass: per
CLAUDE.md's "Working practices" section, write or update a memory note whenever you
finish a feature or bug fix — on your own initiative, without being asked. That's the
only way the *next* onboarding actually stays current instead of drifting stale like
the deploy-gotchas file did on 2026-08-14/15.
