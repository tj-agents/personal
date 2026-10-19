---
name: task
description: Record a known task in the selected personal Azure work-item provider. Use when an explicitly adopted personal project has verified task facts to capture.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: engineering
provenance: house
---

# Record a personal task

Load `personal:work-item` first. Follow its entry-point prerequisites to verify explicit personal
adoption and the selected provider; do not configure or adopt a project automatically.

Then load `engineering:write-task` and fix the record kind to `task`. Preserve the canonical existing
identity, factual evidence, unknowns and the supplied Feature parent. The shared provider owns schema
lookup, validation, creation, updates and persisted readback.

Record only. An explicit request to complete an existing task belongs to `personal:address-task`.
If source facts are unavailable, leave the record pending; do not invent facts or use a fallback store.

```text
personal:task Record the task to verify parent links under the activity timeline Feature.
```
