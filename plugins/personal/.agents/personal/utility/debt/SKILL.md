---
name: debt
description: Record known technical debt in the explicitly selected GitHub Work Items provider for an adopted personal project.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: engineering, work-items
provenance: house
---

# Record personal debt

Apply this entry only after the source primary checkout explicitly selects `personal@tj-agents` and
`work-items:manage` resolves its declared GitHub provider. Reject employer scope or another selected
provider. Do not adopt, configure or replace a provider while recording.

Then load `work-items:write-debt` and fix the record kind to `debt`. Preserve the canonical existing
identity, factual evidence, unknowns and concrete maintenance concern. The shared provider owns schema
lookup, validation, creation, updates and persisted readback.

Record only. An explicit request to fix existing debt belongs to `personal:address-debt`.
If source facts are unavailable, retain them with the current task; do not use another backend or a local backlog.

```text
personal:debt Record the duplicated deployment configuration that must be consolidated.
```
