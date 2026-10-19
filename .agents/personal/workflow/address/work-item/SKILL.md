---
name: address-work-item
description: Address an existing personal Azure work item by reading its persisted kind and entering the matching shared engineering lifecycle. Use when explicitly asked to implement or fix a personal work item whose kind is not yet known; recording alone uses personal:work-item or a personal kind entry.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: engineering
provenance: house
---

# Address a personal work item

Load `personal:work-item` and follow its **Address an existing item** procedure without an expected kind.
Use the exact named record, or select within the user's requested scope when no record was named.
The provider's persisted kind chooses the lifecycle. Retain its canonical identity and existing repair
owner, and update it through the same provider after verification.

```text
personal:address-work-item Implement https://dev.azure.com/personal-demo/Personal/_workitems/edit/42
```
