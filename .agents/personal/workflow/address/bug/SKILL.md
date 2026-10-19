---
name: address-bug
description: Address an existing personal Azure bug record. Use when an explicitly adopted personal project needs an identified bug investigated or fixed.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: engineering
provenance: house
---

# Address a personal bug

Load `personal:work-item`, then follow its **Address an existing item** section with expected kind
`bug`. Pass the named full URL when one is supplied.

Verify the persisted record is actually a bug. Do not reclassify or recreate it; retain closed history
and its existing repair owner. That shared section selects `engineering:address-bug` for the lifecycle.
If source facts are unavailable, leave the item pending with no fallback.

```text
personal:address-bug Fix https://dev.azure.com/personal-demo/Personal/_workitems/edit/42 after reproducing the save crash.
```
