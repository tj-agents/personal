---
name: address-feature
description: Address an existing personal Azure feature record. Use when an explicitly adopted personal project needs an identified feature implemented.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: engineering
provenance: house
---

# Address a personal feature

Load `personal:work-item`, then follow its **Address an existing item** section with expected kind
`feature`. Pass the named full URL when one is supplied.

Verify the persisted record is actually a feature. Do not reclassify or recreate it; retain closed
history and its existing repair owner. That shared section selects existing plan execution or
`engineering:feature`.
If source facts are unavailable, leave the item pending with no fallback.

```text
personal:address-feature Implement https://dev.azure.com/personal-demo/Personal/_workitems/edit/42 as the next approved feature.
```
