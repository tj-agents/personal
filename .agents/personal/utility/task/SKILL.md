---
name: task
description: Record a known task in the explicitly selected GitHub Work Items provider for an adopted personal project.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: engineering, work-items
provenance: house
---

# Record a personal task

Apply this entry only after the source primary checkout explicitly selects `personal@tj-agents` and
`work-items:manage` resolves its declared GitHub provider. Reject employer scope or another selected
provider. Do not adopt, configure or replace a provider while recording.

Then load `work-items:write-task` and fix the record kind to `task`. Preserve the canonical existing
identity, factual evidence, unknowns and supplied Feature parent. The shared provider owns schema lookup,
validation, creation, updates and persisted readback.

Record only. An explicit request to complete an existing task belongs to `personal:address-task`.
If source facts are unavailable, retain them with the current task; do not use another backend or a local backlog.

```text
personal:task Record the task to verify parent links under the activity timeline Feature.
```
