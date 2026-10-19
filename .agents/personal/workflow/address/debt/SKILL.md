---
name: address-debt
description: Address an existing personal Azure debt record. Use when an explicitly adopted personal project needs identified technical debt resolved.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: engineering
provenance: house
---

# Address personal debt

Load `personal:work-item`, then follow its **Address an existing item** section with expected kind
`debt`. Pass the named full URL when one is supplied.

Verify the persisted record is actually debt. Do not reclassify or recreate it; retain closed history
and its existing repair owner. That shared section selects `engineering:address-debt` for the lifecycle.
If source facts are unavailable, leave the item pending with no fallback.

```text
personal:address-debt Consolidate https://dev.azure.com/personal-demo/Personal/_workitems/edit/42 without losing deployment settings.
```
