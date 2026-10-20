---
name: bug
description: Record a known bug in the explicitly selected GitHub Work Items provider for an adopted personal project.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: engineering, work-items
provenance: house
---

# Record a personal bug

Apply this entry only after the source primary checkout explicitly selects `personal@tj-agents` and
`work-items:manage` resolves its declared GitHub provider. Reject employer scope or another selected
provider. Do not adopt, configure or replace a provider while recording.

Then load `work-items:write-bug` and fix the record kind to `bug`. Preserve the canonical existing
identity, factual evidence, unknowns and supplied reproduction details. The shared provider owns schema
lookup, validation, creation, updates and persisted readback.

Record only. An explicit request to fix an existing bug belongs to `personal:address-bug`.
If source facts are unavailable, retain them with the current task; do not use another backend or a local backlog.

```text
personal:bug Record the reproducible crash when saving an empty profile.
```
