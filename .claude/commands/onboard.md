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
   `uv sync --extra dev --extra testing --extra docs` (do NOT add `--all-extras` or
   `--extra tools`; the `tools` extra pulls a full driving-simulator dependency this
   project doesn't use), `capnp compile` + `scons -j8 cereal/`, `python3 -m py_compile`
   and `ruff check` against this fork's actual changes (`selfdrive/mapd/`,
   `selfdrive/tailscale/`). This was fully validated clean on 2026-08-15, so it should
   be fast — just confirm and note anything that doesn't pass, don't go debugging a
   problem that probably isn't there.

Then give a short status summary: what you learned, and whether the environment is
ready to work in.

One standing practice for the rest of this session, not just this onboarding pass: per
CLAUDE.md's "Working practices" section, write or update a memory note whenever you
finish a feature or bug fix — on your own initiative, without being asked. That's the
only way the *next* onboarding actually stays current instead of drifting stale like
the deploy-gotchas file did on 2026-08-14/15.
