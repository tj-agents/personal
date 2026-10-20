---
name: address-feature
description: Address an existing GitHub feature record in an explicitly adopted personal project.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: engineering, work-items
provenance: house
---

# Address a personal feature

Apply this entry only after the source primary checkout explicitly selects `personal@tj-agents` and
`work-items:manage` resolves its declared GitHub provider. Reject employer scope or another selected
provider. Do not adopt or replace a provider.

Read the named GitHub item with `work-items:manage`, verify its managed kind is `feature`, then enter
`engineering:feature` with the same canonical identity and delivery owner. Do not reclassify or recreate it.
Use Work Items for factual updates and closure evidence; no local backlog exists.

```text
personal:address-feature Implement owner/repository#42 as the next approved feature.
```
