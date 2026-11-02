# personal

Personal means personal projects only. Infonetica is work scope, including the `tj-agents/infonetica`
plugin source repository and every worktree. Never select or inject this profile there. GitHub ownership,
a publisher account or a checkout location does not establish personal scope; read the target project's
README.md and AGENTS.md before adoption.

Mandatory standards for explicitly adopted personal projects.

Published as plugin `tj-agents/personal` from the `tj-agents` marketplace.

## Skills

- Policies: `personal:rules`.
- Conventions: `personal:revision`.
- Utilities: `personal:use`, `personal:bot-identity`.

## Adopt a personal project

Explicitly select `personal@tj-agents` through `agent:plugins`, then run the
shipped adoption utility. Its `--selection-tool` option performs both steps together. Use `--mode preview`
to inspect changes, `--mode write` to apply them and `--mode check` in CI. See the
[adoption procedure](.agents/personal/utility/use/SKILL.md) for the complete command.

The mandatory policy is generated into AGENTS.md from one authored body with a source hash. Adoption merges
distinct CLAUDE.md instructions into AGENTS.md and leaves CLAUDE.md as its exact import pointer. This uses
native project instructions, so it does not depend on plugin hook activation. Adoption is complete only after
a passing check and fresh host verification; discovery, installation and version output are insufficient.

The check also rejects retained compatibility declarations. Remove obsolete bindings and migrate actual
callers in the same cutover. Employer projects are outside this profile; personal scope requires explicit adoption.

Adoption leaves existing workflows unchanged. This repository runs its own policy check against candidate
source before merge.

## Work items and progress

Personal owns automatic work-item recording and progress policy for explicitly adopted personal projects.
Its [bounded policy](.agents/personal/policy/rules/resources/work-items.md) covers bugs, mistakes, debt,
features, stories and tasks. GitHub owns the shared `github:work-item`, `github:create-work-item` and
`github:address-work-item` operations, deterministic schemas, managed issue bodies, request receipts
and verified repository and owner board updates.

The affected source project's primary checkout selects the policy and tracker. An observation in another
repository does not move that project's defect or adopt Personal for the observing task. An eligible
tj-agents tooling defect uses its source routine even when demonstrated during employer work; Template
owns source repair authority and employer evidence boundaries still apply.

Work starting, blocking, resuming, handing off, entering review and reaching verified acceptance updates
the same canonical item and its boards. Recording and board maintenance do not dispatch ordinary backlog
implementation. Addressing reuses the existing owner under Workflow and its mapped Engineering operation.
A missing provider, policy or board option leaves the operation incomplete without selecting another queue.

## Agent GitHub identity

`personal:bot-identity` enrolls each trusted machine into the existing `tomjseery-bot` App.
Its published descriptor contains only public identity metadata. Setup verifies a newly issued key and
creates the protected local credential record; no JSON assembly or copying keys between machines is needed.
The plugin declares this setup step in its harness manifest for Core's setup and sync entry points.
Initial enrollment requires Tommy's authenticated GitHub key issuance through the local browser wizard;
ordinary setup and verification never prompt. See the [enrollment procedure](.agents/personal/utility/bot-identity/SKILL.md).

Readiness also requires `repository_creation:write` on the App and its `tj-agents` installation. Setup fails
closed if that creation capability is removed, or if `administration:write` is granted; it reports the specific
App or installation settings page for Tommy to correct and never changes GitHub permissions itself.

## Authoring and verification

```powershell
pwsh .agents/sync-generated.ps1
pwsh .agents/sync-generated.ps1 -Check
```

The layout, the vendored generator and CI come from [Template](https://github.com/tj-agents/template).
