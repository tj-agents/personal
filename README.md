# personal

Mandatory standards for explicitly adopted personal projects.

Published as plugin `personal` from this repository's `personal-agents` marketplace.

## Skills

- Policies: `personal:current-solution`.
- Utilities: `personal:adopt`, `personal:bug`, `personal:debt`,
  `personal:mistake`, `personal:feature`, `personal:task`.
- Workflows: `personal:address-bug`, `personal:address-debt`,
  `personal:address-mistake`, `personal:address-feature`, `personal:address-task`.

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

Adoption installs a dedicated CI check against the current published policy on Windows and Linux. Other
workflows remain unchanged. This repository runs that same check against its candidate source before merge.

## Personal GitHub work items

Personal backlog records live in the GitHub provider shipped by Work Items. Select the Personal profile
explicitly, then adopt the GitHub tracker in each source repository through `work-items:manage`. Personal
never configures a cloud account, server, credential store or local backlog.

## Recording and addressing

When the kind is known, record it directly with `personal:bug`, `personal:debt`, `personal:mistake`,
`personal:feature` or `personal:task`. Recording preserves the request for later work and does not start
implementation. Each entry verifies explicit personal scope and delegates record facts, GitHub operations
and request receipts to Work Items.

Use the corresponding personal addressing workflow for an identified GitHub item. These entries reuse
Engineering's repair, feature and plan workflows; Work Items reads and updates the selected record.
Always qualify `personal:feature` when recording and `engineering:feature` when implementing.

Work Items owns provider-neutral record conventions and the shared GitHub tracker. Core owns reusable
diagnosis, repair, planning and delivery. Personal owns explicit personal scope and these typed entry
points. Its shipped harness injects Work Items alongside Engineering and Machine. A missing or different
provider blocks the operation without adopting another queue.

## Authoring and verification

```powershell
pwsh .agents/sync-generated.ps1
pwsh .agents/sync-generated.ps1 -Check
```

The layout, the vendored generator and CI come from [Template](https://github.com/tj-agents/template).
