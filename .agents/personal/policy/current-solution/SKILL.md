---
name: current-solution
description: Mandatory current-solution, proportionate-engineering and GitHub work-tracking rules for explicitly adopted personal projects.
kind: policy
domain: personal
profile: core
applicability: projects explicitly selecting personal
requires: personal
provenance: house
---

# Personal projects

These rules are mandatory in projects that explicitly adopt `personal@tj-agents`. Adoption records the
project's personal scope; a home directory, author name or employer association never establishes it.
Employer projects remain outside this profile unless Tommy explicitly changes that scope.

Keep one current supported solution. When replacing behavior, remove the superseded names, aliases,
fallback implementations, adapters, configuration formats and compatibility branches. Coordinate and
migrate all known callers, project declarations, installed registrations, generated artifacts and live
runtime entry points in the same cutover. Do not retain obsolete behavior for hypothetical external users;
coordinate upgrades with the actual collaborating developers.

Verify the entry points people actually use on every supported platform, including Windows and Linux
launch paths where supported. Source edits, successful generation, passing unit tests and version commands
alone do not prove that a migration is complete. Check installed bindings and fresh runtime behavior.
Record any unverified entry point as incomplete, with its resolver and observable acceptance condition.

For example, replacing `old-launch` with `launch` means migrating the registered shell command, project
configuration and actual callers, deleting the old entry, then invoking `launch` from a fresh session on
each supported OS. Running `launch --version` alone leaves the cutover unverified.

```text
Replace old-launch with launch:
1. Migrate the registered shell command, configuration and actual callers.
2. Delete the old entry and regenerate installed settings.
3. Invoke launch from a fresh supported Windows/Linux session and check its actual behavior.
Result: launch --version alone leaves this migration incomplete.
```

Do not independently add a backwards-compatibility exception. Surface an explicit contrary user requirement
as a deliberate policy decision, identify the affected supported behavior and reconcile this profile's
scope before implementing it. Never hide an exception in a fallback or adapter.

Solve the demonstrated problem with the smallest suitable implementation. Add abstractions, dependencies,
configuration switches, duplicate paths or process machinery only for a concrete current need. Prefer the
capabilities the project already selects. Verify the behavior and meaningful failure paths in proportion
to the change; do not add tests that merely repeat the implementation or a checklist with no concrete benefit.

## Work tracking

GitHub Issues owns the live backlog for projects that adopt Personal. Use `personal:work-item` to read or
list work, `personal:create-work-item` to record it and `personal:address-work-item` to execute an existing
item. These operations use the repository's explicit `personal:work-item` provider binding. A missing or
different binding blocks the operation; it never authorizes silently selecting another tracker.

Keep scope, acceptance, hierarchy, dependencies, status, verification and the next action in the canonical
issues. Keep lasting design and reference material in the project's permanent documentation, linked to
those issues. Do not create a `plans/` backlog or another local queue. Core's shared agent store owns
session and execution state; it does not replace the GitHub backlog.

When migrating existing plans, reuse existing issue identities and preserve useful design in permanent
documentation. Verify coverage and update active links and resume references before removing the old
plans. Repository instructions must not duplicate these shared tracking rules.

```text
Existing feature: read its GitHub issue and children through personal:work-item.
New task: record it through personal:create-work-item under the existing feature.
Implementation: use personal:address-work-item for that task; update its issue with progress and evidence.
Design: maintain docs/design.md and link the feature; do not create plans/TASK_PLAN.md.
```

This policy is authored once here. Personal adoption generates its marked native instruction block from
this body and checks it for drift. A selected plugin or an `always` tier alone is not proof of loading.
