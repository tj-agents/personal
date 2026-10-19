---
name: address-task
description: Address an existing personal Azure task record. Use when an explicitly adopted personal project needs an identified task completed.
kind: workflow
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: engineering
provenance: house
---

# Address a personal task

Load `personal:work-item`, then follow its **Address an existing item** section with expected kind
`task`. Pass the named full URL when one is supplied.

Verify the persisted record is actually a task. Do not reclassify or recreate it; retain closed history
and its existing repair owner. That shared section follows the task's declared workflow and uses
`engineering:feature` for authorized scoped new or changed product behavior.
If source facts are unavailable, leave the item pending with no fallback.

```text
personal:address-task Complete https://dev.azure.com/personal-demo/Personal/_workitems/edit/42 after verifying its Feature parent.
```
