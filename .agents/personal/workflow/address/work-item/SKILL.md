---
name: address-work-item
description: Reconcile an existing personal GitHub work item and enter Workflow execution with its mapped Engineering technical operation. Use when asked to address, fix or deliver an identified personal backlog item.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: engineering, python
provenance: house
---

# Address a personal work item

This is the execution intent. It reconciles an existing record with one Workflow goal; it does not create
a duplicate goal or provider record.

Read the identified item through `personal:work-item`, verify the source primary checkout selects
`personal@tj-agents` and declares no other provider. Reconcile the canonical GitHub
identity, managed kind, current facts and any existing repair owner before delivery work. Reject employer
evidence, another provider, a foreign identity or an unmanaged body. If an owner already exists,
`workflow:run` reuses it. If a legitimate item is unowned, `workflow:run` acquires its sole whole-goal
owner; do not reject it merely for being unowned.

Map the persisted kind to one bounded Engineering technical operation: `bug` to `engineering:address-bug`; `mistake` to
`engineering:address-mistake`; `debt` to `engineering:address-debt`; and `feature`, `story` or `task` to
`engineering:feature`. Enter `workflow:run` with the same canonical identity and that operation.
Workflow retains and reconciles the sole whole-goal owner; the selected Engineering operation performs
the bounded software delivery and returns its evidence. This workflow does not recreate or reclassify the
work item. Use this skill's address helper for factual updates and closure evidence after the Engineering
operation supplies them.

```text
personal:address-work-item owner/repository#42
1. personal:work-item reads owner/repository#42 and confirms kind story, an open state and no current owner.
2. Reconcile the canonical GitHub identity, then enter workflow:run with owner/repository#42 and the mapped engineering:feature operation; Workflow acquires the sole goal owner.
3. engineering:feature completes the bounded software delivery and returns verification evidence. After verified acceptance, run python -B <skill-directory>/scripts/address_work_item.py update --root . --item owner/repository#42 --input facts.json --expected-hash HASH and then close with its recorded verification evidence.
```
