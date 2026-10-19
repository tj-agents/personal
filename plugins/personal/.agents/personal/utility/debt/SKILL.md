---
name: debt
description: Record known technical debt in the selected personal Azure work-item provider. Use when an explicitly adopted personal project has verified debt facts to capture.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: engineering
provenance: house
---

# Record personal debt

Load `personal:work-item` first. Follow its entry-point prerequisites to verify explicit personal
adoption and the selected provider; do not configure or adopt a project automatically.

Then load `engineering:write-debt` and fix the record kind to `debt`. Preserve the canonical existing
identity, factual evidence, unknowns and the concrete maintenance concern. The shared provider owns
schema lookup, validation, creation, updates and persisted readback.

Record only. An explicit request to fix existing debt belongs to `personal:address-debt`.
If source facts are unavailable, leave the record pending; do not invent facts or use a fallback store.

```text
personal:debt Record the duplicated deployment configuration that must be consolidated.
```
