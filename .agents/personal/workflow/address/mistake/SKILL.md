---
name: address-mistake
description: Address an existing personal Azure mistake record. Use when an explicitly adopted personal project needs an identified mistake reconciled.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: engineering
provenance: house
---

# Address a personal mistake

Load `personal:work-item`, then follow its **Address an existing item** section with expected kind
`mistake`. Pass the named full URL when one is supplied.

Verify the persisted record is actually a mistake. Do not reclassify or recreate it; retain closed
history and its existing repair owner. That shared section selects `engineering:address-mistake`.
If source facts are unavailable, leave the item pending with no fallback.

```text
personal:address-mistake Reconcile https://dev.azure.com/personal-demo/Personal/_workitems/edit/42 with the release procedure.
```
