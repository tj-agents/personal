---
name: address-work-item
description: Reconcile an existing personal GitHub work item and enter the Core Engineering lifecycle. Use when asked to address, fix or deliver an identified personal backlog item.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: engineering, python
provenance: house
---

# Address a personal work item

This is the execution intent. It reconciles an existing record with one Engineering lifecycle; it neither
creates a second record nor starts a second owner.

Read the identified item through `personal:work-item`, verify the source primary checkout selects
`personal@tj-agents`. Reconcile the canonical GitHub
identity, managed kind, current facts and any existing repair owner before delivery work. Reject employer
evidence, another provider, a foreign identity or an unmanaged body. If an owner already exists, continue
with that owner. If a legitimate item is unowned, the selected Engineering lifecycle acquires its owner;
do not reject it merely for being unowned.

Map the persisted kind to one lifecycle: `bug` to `engineering:address-bug`; `mistake` to
`engineering:address-mistake`; `debt` to `engineering:address-debt`; and `feature`, `story` or `task` to
`engineering:feature`. Core owns execution tracking and delivery; this workflow does not recreate or
reclassify the work item. Use this skill's address helper for factual updates and closure evidence after
the Engineering lifecycle supplies them.

```text
personal:address-work-item owner/repository#42
1. personal:work-item reads owner/repository#42 and confirms kind story, an open state and no current owner.
2. Reconcile its canonical GitHub identity, then enter engineering:feature with that reference; Engineering acquires the delivery owner.
3. After verified acceptance, run python -B <skill-directory>/scripts/address_work_item.py update --root . --item owner/repository#42 --input facts.json --expected-hash HASH and then close with its recorded verification evidence.
```
