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

## Agent GitHub identity

`personal:bot-identity` enrolls each trusted machine into the existing `tomjseery-bot` App.
Its published descriptor contains only public identity metadata. Setup verifies a newly issued key and
creates the protected local credential record; no JSON assembly or copying keys between machines is needed.
The plugin declares this setup step in its harness manifest for Core's setup and sync entry points.
Initial enrollment requires Tommy's authenticated GitHub key issuance through the local browser wizard;
ordinary setup and verification never prompt. See the [enrollment procedure](.agents/personal/utility/bot-identity/SKILL.md).

The wrapper requires Python 3.12 or newer. CLI owns its shared PATH implementation in `tj_cli.paths`;
the locked `tj-cli` library ships with the plugin and setup copies it into the managed wrapper directory.
Neither the installed wrapper nor setup needs a CLI source checkout or a manual package installation.

Readiness also requires `repository_creation:write` on the App and its `tj-agents` installation. Setup fails
closed if that creation capability is removed, or if `administration:write` is granted; it reports the specific
App or installation settings page for Tommy to correct and never changes GitHub permissions itself.

## Authoring and verification

```powershell
pwsh .agents/sync-generated.ps1
pwsh .agents/sync-generated.ps1 -Check
uv sync --locked
uv run pytest
```

Run authored Python scripts with `uv run python` so they use the declared dependencies. Generated
repository-local skills and installed plugin entry points carry their libraries beside their scripts.

The layout, the vendored generator and CI come from [Template](https://github.com/tj-agents/template).
