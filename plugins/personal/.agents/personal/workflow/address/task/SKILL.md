---
name: address-task
description: Address an existing GitHub task record in an explicitly adopted personal project.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: engineering, work-items
provenance: house
---

# Address a personal task

Apply this entry only after the source primary checkout explicitly selects `personal@tj-agents` and
`work-items:manage` resolves its declared GitHub provider. Reject employer scope or another selected
provider. Do not adopt or replace a provider.

Read the named GitHub item with `work-items:manage`, verify its managed kind is `task`, then enter the
task's declared workflow with the same canonical identity and delivery owner. Use `engineering:feature` for
an authorized scoped change. Do not reclassify or recreate it. Use Work Items for factual updates and closure
evidence; no local backlog exists.

```text
personal:address-task Complete owner/repository#42 after verifying its Feature parent.
```
