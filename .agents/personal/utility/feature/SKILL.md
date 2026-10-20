---
name: feature
description: Record a known feature in the explicitly selected GitHub Work Items provider for an adopted personal project.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: engineering, work-items
provenance: house
---

# Record a personal feature

Apply this entry only after the source primary checkout explicitly selects `personal@tj-agents` and
`work-items:manage` resolves its declared GitHub provider. Reject employer scope or another selected
provider. Do not adopt, configure or replace a provider while recording.

Then load `work-items:write-feature` and fix the record kind to `feature`. Preserve the canonical existing
identity, factual evidence, unknowns and requested outcome. The shared provider owns schema lookup,
validation, creation, updates and persisted readback.

Record only. An explicit request to implement an existing feature belongs to `personal:address-feature`.
If source facts are unavailable, retain them with the current task; do not use another backend or a local backlog.

```text
personal:feature Record the request for a searchable activity timeline.
```
