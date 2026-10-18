---
name: work-item
description: Manage personal Azure Boards features, tasks, bugs, mistakes and debt with repository-scoped records and isolated personal MCP credentials. Use when recording, listing, updating or addressing work in an explicitly adopted personal project, or setting up its personal work-item provider.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: python, machine
provenance: house
---

# Personal work items

Own personal work records in Azure Boards. Use this skill when the primary checkout selects
`personal:work-item` in `.problem-records.json`. Preserve that repository's identity and existing
records. Reject employer paths, employer origins and the Infonetica organization. Work projects
continue to use their work-scoped Azure skills and MCP configuration.

## Install and configure

The runtime beside this file is the shipped implementation. Install Python 3.12 or newer through uv,
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
structured schema with an arbitrary description.

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

The private Git-common-directory journal reserves request IDs before POST. An uncertain write is
reconciled through Azure's request-ID field before another create. A closed matching record stays
closed. Multiple matches or unavailable readback fail without another blind write. This prevents
unsafe retries in the same checkout; Azure does not provide a uniqueness constraint for the custom
field, so it does not establish cross-machine exactly-once creation.

Every managed operation validates `Custom.PersonalRepository` as well as the selected organization
and project. The Azure process must supply `Custom.PersonalRepository`, `Custom.PersonalRequestId`
and `Custom.PersonalRecord` on all five work-item types. Finish process/project provisioning and live
read/write tests before enabling this provider for an existing queue.

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
