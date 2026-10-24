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
generates the mandatory native instruction block in AGENTS.md, merges distinct CLAUDE.md instructions into
AGENTS.md once each, and leaves CLAUDE.md as the exact `@AGENTS.md` pointer; `@./AGENTS.md` is the same
pointer, and any other Claude-only `@path` import is refused rather than copied in as plain text. It also
removes its own earlier-generated `.github/workflows/check-personal-policy.yml` CI caller, since adoption
no longer wires CI enforcement, while refusing to touch a workflow of that name it did not generate. It
refuses retained compatibility declarations and broken block markers. The policy has one authored body;
generated native blocks are checked, never edited by hand.
This is native instruction delivery, not a claim of plugin hook execution or trust.

Ask Tommy once whether agents may merge without his approval once checks pass, and add
`--agents-may-merge true|false`. Adoption writes `.github/merge-policy.json`, which
the GitHub Actions merge-policy utility enforces, or changes only that flag; without the answer it leaves the
policy undeclared and says so.


```powershell
# Windows, from a checkout of tj-agents/personal, for an explicitly personal repository:
python -B .agents/personal/utility/adopt/scripts/adopt.py --root C:/repos/my-app --mode preview --selection-tool C:/repos/core/.agents/machine/utility/plugin-selection/scripts/adopt_plugins.py
# Review the preview, then use --mode write; CI uses --mode check.
# Linux/macOS use python3 and their checkout paths with the same arguments.
```

Before declaring adoption complete, run its check and verify a fresh actual Claude and Codex entry point
in the project on supported platforms. Confirm the rule was loaded and inspect its installed selection;
a version command or a generated file is insufficient. Keep any missing host evidence with the goal.
