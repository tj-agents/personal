# personal

Personal means personal projects only. Infonetica is work scope, including the `tj-agents/infonetica`
plugin source repository and every worktree. Never select or inject this profile there. GitHub ownership,
a publisher account or a checkout location does not establish personal scope; read the target project's
README.md and AGENTS.md before adoption.

Mandatory standards for explicitly adopted personal projects.

Published as plugin `personal` from this repository's `personal-agents` marketplace.

## Skills

- Policies: `personal:current-solution`.
- Utilities: `personal:adopt`, `personal:work-item`, `personal:create-work-item`.
- Workflow: `personal:address-work-item`.

## Adopt a personal project

Explicitly select `personal@tj-agents` through Core's `machine:plugin-selection` tool, then run the
shipped adoption utility. Its `--selection-tool` option performs both steps together. Use `--mode preview`
to inspect changes, `--mode write` to apply them and `--mode check` in CI. See the
[adoption procedure](.agents/personal/utility/adopt/SKILL.md) for the complete command.

The mandatory policy is generated into AGENTS.md from one authored body with a source hash. Adoption merges
distinct CLAUDE.md instructions into AGENTS.md and leaves CLAUDE.md as its exact import pointer. This uses
native project instructions, so it does not depend on plugin hook activation. Adoption is complete only after
a passing check and fresh host verification; discovery, installation and version output are insufficient.

The check also rejects retained compatibility declarations. Remove obsolete bindings and migrate actual
callers in the same cutover. Employer projects are outside this profile; personal scope requires explicit adoption.

Adoption leaves existing workflows unchanged. This repository runs its own policy check against candidate
source before merge.

## Personal GitHub work items

Personal owns its GitHub tracker. A source repository must explicitly adopt `personal@tj-agents` and select
`personal:work-item` in `.problem-records.json`; the tracker then resolves its source primary checkout and
uses only the matching GitHub origin. Personal never infers scope, selects a provider during read or create,
or configures a cloud account, server, credential store or local backlog.

## Recording and addressing

Use `personal:create-work-item` to classify and record a bug, mistake, debt, feature, Story or task. Recording
preserves the request for later work and does not start implementation. The shipped helper owns deterministic
schemas, rendered bodies, GitHub CRUD and durable request receipts.

Use `personal:work-item` to read, list or view an identified item. Use `personal:address-work-item` for an
existing item after reconciling its identity and repair owner; Workflow owns the goal and execution, and the
mapped Engineering operation owns bounded software delivery. The address helper records factual updates and
closure evidence. A missing or different provider blocks the operation without adopting another queue.

## Authoring and verification

```powershell
pwsh .agents/sync-generated.ps1
pwsh .agents/sync-generated.ps1 -Check
```

The layout, the vendored generator and CI come from [Template](https://github.com/tj-agents/template).
