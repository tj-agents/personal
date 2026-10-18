# personal

Mandatory standards for explicitly adopted personal projects.

Published as plugin `personal` from this repository's `personal-agents` marketplace.

## Skills

- Policies: `personal:current-solution`.
- Utilities: `personal:adopt`, `personal:work-item`.

## Adopt a personal project

Explicitly select `personal@tj-agents` through Core's `machine:plugin-selection` tool, then run the
shipped adoption utility. Its `--selection-tool` option performs both steps together. Use `--mode preview`
to inspect changes, `--mode write` to apply them and `--mode check` in CI. See the
[adoption procedure](.agents/personal/utility/adopt/SKILL.md) for the complete command.

The mandatory policy is generated into AGENTS.md from one authored body with a source hash. Claude reads
that block through its AGENTS.md import or an equal generated block in CLAUDE.md. This uses native project
instructions, so it does not depend on plugin hook activation. Adoption is complete only after a passing
check and fresh host verification; discovery, installation and version output are insufficient.

The check also rejects retained compatibility declarations. Remove obsolete bindings and migrate actual
callers in the same cutover. Employer projects are outside this profile; personal scope requires explicit adoption.

Adoption installs a dedicated CI check against the current published policy on Windows and Linux. Other
workflows remain unchanged. This repository runs that same check against its candidate source before merge.

## Personal Azure Boards

`personal:work-item` provides native Azure features, tasks, bugs, mistakes and debt, with parent/child
links and a repository identity on every record. Its shipped runtime also launches a separate personal
Azure DevOps MCP for Codex and Claude using the OS credential store. See the
[setup and record procedure](.agents/personal/utility/work-item/SKILL.md).

Live adoption requires a confirmed personal organization, provisioned process/project, secure PAT
and verified host tests. Keep an existing queue authoritative until its migration is reconciled.

## Authoring and verification

```powershell
pwsh .agents/sync-generated.ps1
pwsh .agents/sync-generated.ps1 -Check
```

The layout, the vendored generator and CI come from [Template](https://github.com/tj-agents/template).
