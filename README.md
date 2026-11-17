# personal

Personal means personal projects only. An organization plugin's source repository and every worktree of it
are work scope: never select or inject this profile there. See
[Plugin kinds](https://github.com/tj-agents/docs/blob/main/PLUGINS.md#plugin-kinds).
GitHub ownership, a publisher account or a checkout location does not establish personal scope; read the
target project's README.md and AGENTS.md before adoption.

Mandatory standards for explicitly adopted personal projects.

Published as plugin `tj-agents/personal` from the `tj-agents` marketplace.

## Skills

- Policies: `personal:rules`.
- Conventions: `personal:revision`.
- Utilities: `personal:use`, `personal:work-item`, `personal:create-work-item`.
- Workflow: `personal:address-work-item`.

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

## Personal GitHub work items

Personal owns its GitHub tracker. Selecting `personal@tj-agents` in a repository's `.agents/plugins.json`
selects `personal:work-item`; no other declaration exists. The tracker resolves the source primary checkout
and records issues in its GitHub origin. A created issue is placed on the owner's board named after the
repository and on the owner-wide board named after the owner, created on first use; that needs `gh` with the
`project` scope. Personal never infers scope, selects a provider during read or create,
or configures a cloud account, server, credential store or local backlog.

## Recording and addressing

Use `personal:create-work-item` to classify and record a bug, mistake, debt, feature, Story or task. Recording
preserves the request for later work and does not start implementation. The shipped helper owns deterministic
schemas, rendered bodies, GitHub CRUD and durable request receipts.

Use `personal:work-item` to read, list or view an identified item. Use `personal:address-work-item` for an
existing item after reconciling its identity and repair owner; Workflow owns the goal and execution, and the
mapped Engineering operation owns bounded software delivery. The address helper records factual updates and
closure evidence. A missing or different provider blocks the operation without adopting another queue.

## GitHub App access

A personal project may let its agents act as a GitHub App bot. The bot is optional, and Personal ships
no GitHub access or approval tooling of its own: the [GitHub](https://github.com/tj-agents/github)
plugin's access gate supplies `app` access, and its `tj approve` is how the human approves the bot's
pull requests.

The bot is switched on per GitHub owner by committing this file as `.agents/github-access.json` in the
owner's `.github` repository:

```json
{"schema_version": 1, "method": "app", "app": "<github-app-slug>"}
```

A repository overrides its owner's choice by committing the same file itself. For example,
`{"schema_version": 1, "method": "human"}` keeps one repository on the human's own GitHub login. With
neither file, agents use the human's login. Work and other non-personal owners never declare the bot.

Machine setup, App key enrolment and `tj approve` are documented in the
[GitHub README](https://github.com/tj-agents/github#github-access-gate).

## Authoring and verification

```powershell
pwsh .agents/sync-generated.ps1
pwsh .agents/sync-generated.ps1 -Check
```

The layout, the vendored generator and CI come from [Template](https://github.com/tj-agents/template).
