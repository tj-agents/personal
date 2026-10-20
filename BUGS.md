# Bugs

## B001 — Windows Git symlink emulation was edited as native instructions

Kind: bug. Observed: 2026-10-19. Priority: P2. State: resolved.
Source owner: personal:adopt, native_plan.
Evidence: CLI's tracked CLAUDE.md mode was 120000 with core.symlinks=false, so Windows
materialized its link target as an ordinary file. Adoption appended policy to that target text;
frozen review correctly rejected the resulting invalid link before publication.
Cause: filesystem is_symlink alone cannot detect Git's Windows link emulation.
Repair: reject tracked AGENTS.md/CLAUDE.md link modes before any native or selection writes.
Known caller CLI replaces its link with a regular @AGENTS.md native import in the same rollout.
Acceptance: preview/write/check preserve every file while rejecting emulated tracked links on
Windows and Linux; ordinary native imports and packaged utility checks still pass; source-owner
CI and actual CLI policy checks pass before delivery is complete.

Resolution evidence: Personal PR6 merged 37f93858a59ab5318573cf2c3608585301544e85, reviewed
90cf38e0b9ddba06f083d6be6ad8232b4e010ecc; candidate CI 39310530534 and causal main 39311610720
plus policy 39311610042 passed. Twelve tests passed on Windows and a real native Linux Git clone.
All five committed canonical/host/package adopter scripts match on verified main, and the actual
CLI caller now uses a regular native import and passes adoption check. No remaining repair action.

## B002 — Reusable policy CI used floating action refs in strict consumers

Kind: bug. Observed: 2026-10-19. Priority: P2. State: resolved.
Source owner: personal reusable policy workflow.
Evidence: Concertable/customer PR38 run39323692208 rejected actions/checkout@v4 and
setup-python@v5 before any policy step because its organization requires full commit pins.
Repair: pin both shared checkouts and setup-python to official upstream tag commits, verified
through the owning repositories GitHub ref APIs. Preserve the current-main policy checkout,
read-only token scope and no secret forwarding. No consumer security policy is relaxed.
Acceptance: reviewed source CI passes and the actual strict Customer consumer executes its
Windows/Linux policy checks successfully using the repaired reusable workflow.

Resolution evidence: Personal PR8 merged cba7c5cec8f95b8e50cf5e1d9da7468a7d65fd92; source
CI 39324720419 and causal main CI 39325156908 / policy 39325156491 passed. Actual strict
Customer runs 39323692208 and 39323682895 attempt2 executed policy checks successfully on both
Windows and Linux. The consumer security policy was preserved; no remaining runner repair action.
