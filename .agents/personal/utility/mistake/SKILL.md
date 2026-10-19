---
name: mistake
description: Record a known mistake in the selected personal Azure work-item provider. Use when an explicitly adopted personal project has verified mistake facts to capture.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: engineering
provenance: house
---

# Record a personal mistake

Load `personal:work-item` first. Follow its entry-point prerequisites to verify explicit personal
adoption and the selected provider; do not configure or adopt a project automatically.

Then load `engineering:write-mistake` and fix the record kind to `mistake`. Preserve the canonical
existing identity, factual evidence, unknowns and the observed error. The shared provider owns schema
lookup, validation, creation, updates and persisted readback.

Record only. An explicit request to repair an existing mistake belongs to `personal:address-mistake`.
If source facts are unavailable, leave the record pending; do not invent facts or use a fallback store.

```text
personal:mistake Record that the release command was run against the wrong environment.
```
