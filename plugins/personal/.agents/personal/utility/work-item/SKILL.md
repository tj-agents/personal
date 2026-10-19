---
name: work-item
description: Manage personal Azure Boards features, tasks, bugs, mistakes and debt with repository-scoped records and isolated personal MCP credentials. Use when configuring the personal provider or reading, listing, recording and updating its managed Azure facts in an explicitly adopted personal project. For implementing an existing item, use personal:address-work-item.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: python, machine, engineering, work-items
provenance: house
---

# Personal work items

Own personal work records in Azure Boards. Use this skill when the primary checkout selects
`personal:work-item` in `.problem-records.json`. Preserve that repository's identity and existing
records. Reject employer paths, employer origins and the Infonetica organization. Work projects
continue to use their work-scoped Azure skills and MCP configuration.

## Personal entry points

Verify explicit `personal@tj-agents` adoption and use `doctor` to confirm the source repository selects
`personal:work-item` before recording or addressing. These entry points never adopt a repository,
replace its selected provider or select a personal organization automatically. Preserve pending facts
when selection, credentials or the provider is unavailable, then report the resolver and resume condition.

Choose the known kind directly. Each recording entry loads the matching Engineering recording convention
and uses this provider's commands; recording does not start implementation. An untyped recording request
uses `engineering:write-issue` to classify once. Personal addressing is an explicit execution request.

| Kind | Record the known kind | Address existing work |
| --- | --- | --- |
| Bug | `personal:bug` | `personal:address-bug` |
| Debt | `personal:debt` | `personal:address-debt` |
| Mistake | `personal:mistake` | `personal:address-mistake` |
| Feature | `personal:feature` | `personal:address-feature` |
| Task | `personal:task` | `personal:address-task` |

`personal:address-work-item` handles an existing item whose kind is not yet known. Read its persisted kind;
never infer it from the title or create another item. Always qualify `personal:feature` (recording) and
`engineering:feature` (implementation), and qualify the address workflows shared with Engineering.

## Install and configure

The runtime beside this file supplies personal scope, credentials and host configuration. It uses
`work-items:manage`'s installed shared runtime for schemas, Azure record operations and request receipts.
The package dependency installs that engine; its source digest must match the shipped personal manifest
before either credentials or Azure requests are used. Keep the selected Personal and Work Items packages
installed together. Install Python 3.12 or newer through uv,
then run `uv tool install <skill-directory>/runtime`. This installs `personal-work-item` and
`personal-work-item-mcp`; make the uv tool executable directory available to both hosts. Install the
pinned official server separately with `npm install --global @azure-devops/mcp@2.10.0` beside Node.js.
Neither launcher installs packages while holding a credential.

Explicitly adopt the personal profile through `personal:adopt` first. Obtain the confirmed personal
Azure organization slug and project; never infer either from a work login. With the owning checkout,
run `personal-work-item --root <project> configure --organization <slug> --project <name>
--repository <owner/repository> --mode preview`, inspect the listed paths, then use `--mode write`
and `--mode check`. These commands are one command line each. They create the selected-provider and
personal declarations, a project Codex MCP entry, a Claude `.mcp.json` entry and its local approval.
Host entries are installed in the primary and current worktree; the authoritative provider declaration
stays in the primary checkout. Run configuration when adding another existing worktree. Unrelated host
settings are preserved. A different existing provider requires a verified migration.

The project declarations contain identities and version/source pins, never tokens. Run
`personal-work-item --root <project> credentials store` in an interactive terminal to store the
personal PAT in Windows Credential Manager or Linux Secret Service (`secret-tool`). Do not ask for
or print a token in chat. Use the personal organization credential only; work sign-in is never a
fallback. `credentials delete` removes it. `doctor` checks selection and reports the runtime fingerprint;
it does not prove authentication or live Azure acceptance.

`personal-work-item --root <project> isolate --repository <owner/repository> --mode preview` previews
Claude project suppression of inherited `azure-devops` and `azure` servers. `--mode write` changes
only this explicitly named personal primary checkout/current worktree and existing aliases, with a
private backup. It preserves global registrations and all work project settings. Verify suppression
with a fresh actual Claude session before declaring isolation complete. Treat any unverified host
behavior as unfinished setup. Configure each host separately and retain exact native test evidence.

The MCP launcher checks the selected primary checkout, release/source pin and locally installed
server before retrieving the personal PAT. It forwards stdio to the official server, confined to the
personal organization. The official server's tools are organization-scoped; project/repository
checks below belong to this provider and do not imply all MCP tools enforce them.

## Record and reconcile

Use the CLI commands below for every managed record operation so structured facts, repository identity
and retry metadata stay consistent. The personal MCP remains available for native Azure navigation.

Run `personal-work-item schema <kind>` for the required JSON facts, fill them from evidence, and save
the JSON to a durable unsent input file. Kinds are `feature`, `task`, `bug`, `mistake` and `debt`.
Validate with `personal-work-item validate --input <file>`. Do not invent evidence or replace the
structured schema with an arbitrary description. For example, a task input can contain:

```json
{
  "kind": "task",
  "title": "Verify Feature parent links",
  "summary": "Confirm that Azure preserves a task under its owning Feature.",
  "action": "Create a pilot task with the Feature URL and read its parent relation back.",
  "done_when": "The returned parent identity matches the Feature and the Azure UI shows the link."
}
```

Create with `personal-work-item --root <project> create --input <file> --request-id <stable-id>`.
Retain the same request ID and same facts across retries. An optional `--parent <feature-url>` adds
Azure's native parent relation after validating the same project/repository and Feature type. Creation
reads the persisted record back before reporting success. Preserve the unsent file until verified.

Use `list [--kind <kind>] [--include-closed]`, `read --record <url>`,
`update --record <url> --input <file>`, `state --record <url> open|closed`, and
`parent --record <url> --parent <feature-url>` with the same global `--root <project>` argument.
Updates compare Azure revisions and preserve conflicting human edits by failing for reconciliation.
Report the verified Azure URL, kind, state and parent after a write. Features and tasks are native
Azure work items; Azure stores their parent/child relationship. Confirm the chosen skipped-level
hierarchy in the Azure UI during the live pilot before promising a particular board view.

The shared journal preserves the existing personal-work-items/requests namespace in the private
Git common directory and reserves request IDs before POST. An uncertain write is
reconciled through Azure's request-ID field before another create. A closed matching record stays
closed. Multiple matches or unavailable readback fail without another blind write. This prevents
unsafe retries in the same checkout; Azure does not provide a uniqueness constraint for the custom
field, so it does not establish cross-machine exactly-once creation.

Every managed operation validates `Custom.PersonalRepository` as well as the selected organization
and project. The Azure process must supply `Custom.PersonalRepository`, `Custom.PersonalRequestId`
and `Custom.PersonalRecord` on all five work-item types. Finish process/project provisioning and live
read/write tests before enabling this provider for an existing queue.

## Address an existing item

This section is the personal storage/identity boundary for all personal addressing entries. The typed
entry supplies an expected kind; the generic entry accepts any supported persisted kind.

1. Apply the Personal entry points prerequisites. Read the named full Azure URL with this provider's
   `read` command. If no item was named, use `list` with the expected kind when supplied and select one
   actionable item within the user's requested scope. If choosing among materially different outcomes
   needs a user decision, preserve the candidates until resolved. A foreign URL, kind mismatch,
   stale structured facts, missing credential or unavailable read fails visibly; do not reclassify,
   overwrite or recreate the item.
2. Reconcile the exact canonical identity, source owner, dependencies, Feature parent and existing
   goal/session/branch/PR before editing or dispatching. Pass the selected identity into the lifecycle;
   it must not independently select another record. A Closed or Removed item retains its history;
   report its current state instead of reopening it without an explicit request. Another active repair
   owner receives the evidence/link through the existing coordination contract; do not create a second writer.
3. Resume an existing authorized plan through `engineering:plan-execution`. Otherwise use the following
   shared lifecycle for the persisted kind. These workflows own diagnosis, implementation, review,
   verification and authorized delivery; keep Azure operations in this provider.

   | Persisted kind | Shared lifecycle |
   | --- | --- |
   | Bug | `engineering:address-bug` |
   | Debt | `engineering:address-debt` |
   | Mistake | `engineering:address-mistake` |
   | Feature | `engineering:feature` |
   | Task | The task's declared workflow; use `engineering:feature` for an authorized scoped new or changed behavior |

4. Keep the same record current with factual progress, repair links and actual evidence using this
   provider's read/update/state commands and concurrency checks. Before closure, read the record again,
   verify its own acceptance/resolution condition and attach the observed evidence. Follow the requested
   lifecycle's authorization gates; item creation or a recording-only request grants no repair authority.
   For a blocked repair, retain its reason, resolver and observable resume condition and leave it outstanding.

## Core problem reader and cutover

`scripts/read_problem_record.py` is the shipped Python 3.9-compatible Core adapter. It verifies the
installed runtime against this skill's version/source before delegating. It returns only the exact
requested record, kind, open state and factual body for a current bug, mistake or debt record.
Features, tasks, closed, foreign and unavailable records fail admission. Lifecycle policy stays with
Core's existing skills.

Keep an existing provider authoritative until all records, identifiers, states, evidence and native
relationships have been compared against Azure, both hosts pass a live pilot, and the migration owner
performs one verified selection switch. Preserve old links/history. Do not create a competing active
queue, silently fall back to GitHub/local storage, or overwrite another owner's migration artifacts.
