---
name: address-work-item
description: Reconcile an existing personal GitHub work item and enter Workflow execution with its mapped Engineering technical operation. Use when asked to address, fix or deliver an identified personal backlog item.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: tj-item, gh
provenance: house
---

# Address a personal work item

This is the execution intent. It reconciles an existing record with one Workflow goal; it does not create
a duplicate goal or provider record.

Read the identified item with `tj item resolve <ref> --body` (`personal:work-item`) and verify the source primary
checkout selects `personal@tj-agents`. Reconcile the returned `ref`, kind, current facts and any existing repair
owner before delivery work. Reject employer evidence or a foreign identity. If an owner already exists,
`workflow:run` reuses it. If a legitimate item is unowned, `workflow:run` acquires its sole whole-goal
owner; do not reject it merely for being unowned.

Map the kind to one bounded Engineering technical operation: `bug` to `engineering:address-bug`; `mistake` to
`engineering:address-mistake`; `debt` to `engineering:address-debt`; and `feature`, `story` or `task` to
`engineering:feature`. Enter `workflow:run` with the same canonical identity and that operation.
Workflow retains and reconciles the sole whole-goal owner; the selected Engineering operation performs
the bounded software delivery and returns its evidence. This workflow does not recreate or reclassify the
work item. Record factual progress with `tj item comment`; the PR moves the card to In Review and its
merge closes the issue.

```text
personal:address-work-item owner/repository#42
1. tj item resolve https://github.com/owner/repository/issues/42 returns kind story, state To Do and no current owner.
2. Reconcile github:github.com/owner/repository:42, then enter workflow:run with it and the mapped engineering:feature operation; Workflow acquires the sole goal owner.
3. engineering:feature delivers and returns verification evidence; tj item comment 42 --body-file evidence.md records it.
```
