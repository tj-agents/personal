# Bugs

## B001 — Windows Git symlink emulation was edited as native instructions

Kind: bug. Observed: 2026-10-19. Priority: P2. State: in-progress.
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
