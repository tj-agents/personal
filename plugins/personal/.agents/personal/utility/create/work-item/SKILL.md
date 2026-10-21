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

Confirm the source primary checkout explicitly adopts `personal@tj-agents`, then use the selected
`personal:work-item` provider. Never adopt, configure or replace a provider while recording.

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
