---
name: address-debt
description: Address existing GitHub technical debt in an explicitly adopted personal project.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: engineering, work-items
provenance: house
---

# Address personal debt

Apply this entry only after the source primary checkout explicitly selects `personal@tj-agents` and
`work-items:manage` resolves its declared GitHub provider. Reject employer scope or another selected
provider. Do not adopt or replace a provider.

Read the named GitHub item with `work-items:manage`, verify its managed kind is `debt`, then enter
`engineering:address-debt` with the same canonical identity and repair owner. Do not reclassify or recreate
it. Use Work Items for factual updates and closure evidence; no local backlog exists.

```text
personal:address-debt Consolidate owner/repository#42 without losing deployment settings.
```
