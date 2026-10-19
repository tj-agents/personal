---
name: feature
description: Record a known feature in the selected personal Azure work-item provider. Use when an explicitly adopted personal project has verified feature facts to capture.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: engineering
provenance: house
---

# Record a personal feature

Load `personal:work-item` first. Follow its entry-point prerequisites to verify explicit personal
adoption and the selected provider; do not configure or adopt a project automatically.

Then load `engineering:write-feature` and fix the record kind to `feature`. Preserve the canonical
existing identity, factual evidence, unknowns and the requested outcome. The shared provider owns schema
lookup, validation, creation, updates and persisted readback.

Record only. An explicit request to implement an existing feature belongs to `personal:address-feature`.
If source facts are unavailable, leave the record pending; do not invent facts or use a fallback store.

```text
personal:feature Record the request for a searchable activity timeline.
```
