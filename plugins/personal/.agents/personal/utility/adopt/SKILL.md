---
name: adopt
description: Adopt or check mandatory personal-project policy through explicit selection and native Claude/Codex instructions.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: python, machine
provenance: house
---

# Adopt personal project policy

Use only for a project Tommy explicitly identifies as personal. Never infer scope from its location or
from every repository on a machine. Preserve unrelated work and use the project's owning delivery branch.

Run `python <skill-directory>/scripts/adopt.py --root <project> --mode write --selection-tool <machine-plugin-selection>/scripts/adopt_plugins.py`.
Resolve the selection tool from the installed `machine:plugin-selection` skill, which ships it; do not
assemble or maintain another copy. Preview with `--mode preview`, and use the identical command with
`--mode check` in CI. Use `python3` on Linux/macOS. Requires Python 3.11 or newer.

The Core tool owns plugin declarations and host settings. This command selects `personal@tj-agents`,
generates the mandatory native instruction block in AGENTS.md, and covers Claude through its AGENTS.md
import or an equal generated block in CLAUDE.md. It refuses retained compatibility declarations and broken
block markers. The policy has one authored body; generated native blocks are checked, never edited by hand.
This is native instruction delivery, not a claim of plugin hook execution or trust.

Adoption also writes a dedicated CI caller to check the current published policy on Windows and Linux.
It preserves other workflows and refuses to overwrite an unrelated file at that path. For example,
after adopting a project, deleting its marked AGENTS.md block or reintroducing a compatibility alias makes
the policy check fail; rerun adoption after a policy update and review the generated changes together.

Before declaring adoption complete, run its check and verify a fresh actual Claude and Codex entry point
in the project on supported platforms. Confirm the rule was loaded and inspect its installed selection;
a version command or a generated file is insufficient. Keep any missing host evidence with the goal.
