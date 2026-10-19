---
name: bug
description: Record a known bug in the selected personal Azure work-item provider. Use when an explicitly adopted personal project has verified bug facts to capture.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: engineering
provenance: house
---

# Record a personal bug

Load `personal:work-item` first. Follow its entry-point prerequisites to verify explicit personal
adoption and the selected provider; do not configure or adopt a project automatically.

Then load `engineering:write-bug` and fix the record kind to `bug`. Preserve the canonical existing
identity, factual evidence, unknowns and any supplied reproduction details. The shared provider owns
schema lookup, validation, creation, updates and persisted readback.

Record only. An explicit request to fix an existing bug belongs to `personal:address-bug`.
If source facts are unavailable, leave the record pending; do not invent facts or use a fallback store.

```text
personal:bug Record the reproducible crash when saving an empty profile.
```
