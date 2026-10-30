---
name: create-work-item
description: Classify and record one personal GitHub work item without starting implementation. Use when a personal bug, mistake, debt, feature, Story or task must be captured.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: engineering, python
provenance: house
---

# Create a personal work item

This is the recording intent: it classifies and creates one record. It does not start, assign or track
execution.

Before selecting `--root`, identify the affected system, intended outcome and responsible source
repository from its actual source and instructions. Use that repository's primary checkout and GitHub
origin, even when the observation arose elsewhere. If scope is unclear, ask which system and outcome
the user means before choosing a tracker. Keep employer-owned evidence within its authorized provider.
Read any identified existing item and reconcile its owner and history before creation. A wrong-repository
item calls for a deliberate transfer or linked reconciliation, not a duplicate submission.

The source primary checkout's `personal@tj-agents` selection selects this provider. Never adopt,
configure or replace a provider while recording. Creation places the issue on the repository and owner
boards; report a returned `boards.error` rather than retrying the issue.

Within authorized personal work, record noticed or reported incidental problems without requiring a
request to implement them. Honor explicit limits on recording. Preserve the active goal and next action
under `workflow:session`; creation supplies no repair, priority or handoff decision.

Classify the supplied facts once: faulty behavior is `bug`; an observed agent or process error is
`mistake`; a deliberate deferral is `debt`; changed product behavior is `feature`; concrete work with a
completion condition is `task`; a user-centered outcome is `story`. Read an identified existing item before classifying it. Reconcile a
repeated observation with its canonical item and keep its existing identity.

Use `template`, `validate` and `preview` to prepare facts, then create with one stable request ID:

```text
python -B <skill-directory>/scripts/create_work_item.py template --kind story
python -B <skill-directory>/scripts/create_work_item.py validate --input facts.json
python -B <skill-directory>/scripts/create_work_item.py preview --input facts.json
python -B <skill-directory>/scripts/create_work_item.py create --root . --input facts.json --request-id UNIQUE-STABLE-ID
```

Record only. Do not begin implementation; an existing item belongs to `personal:address-work-item`.
Retain the request ID after an uncertain response and reconcile it before another submission.

```text
While adding a CLI feature, a shared Workflow recording failure is reported.
Verify Core owns the policy and selects Personal, then use Core as --root.
If an issue already exists in CLI, reconcile that identity and its history before any creation.
Record the issue under existing personal authority and continue the CLI feature.
An employer observation retains its employer provider and required creation decision.
```
