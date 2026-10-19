# Mistakes

## M001 — Generated host script copies were left outside the repair commit

Observed: 2026-10-19. State: in-progress.
Personal B001 repair generated all copies, but a hand-picked staging list omitted the root
Claude and Codex skill script adapters. Local freshness checked the working tree, not the frozen
commit. PR #6 CI caught both stale committed copies before any merge.
Correction: commit both generated adapters, re-review the exact candidate and require green CI.
Prevention: compare the frozen candidate with every expected generated output, and inspect remaining
working-tree changes before publication; allow only the identified runtime binding. Keep Core's
separate rule that its bot-owned generated payloads remain uncommitted.
Acceptance: exact candidate generation checks and Windows/Linux/native packaging CI pass, then
verified main contains byte-identical canonical and host copies.
