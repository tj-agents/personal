---
name: create-work-item
description: Find and refine a relevant existing personal GitHub work item, or classify and create one when none matches, without starting implementation. Use when a personal bug, mistake, debt, feature, Story or task must be captured.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: engineering, python
provenance: house
---

# Create a personal work item

This is the recording intent: find the relevant existing work and refine it, or create one record when
none matches. It does not start, assign or track execution.

The source primary checkout's `personal@tj-agents` selection selects this provider. Never adopt,
configure or replace a provider while recording. Creation places the issue on the repository and owner
boards; report a returned `boards.error` rather than retrying the issue.

## Find the right record

Resolve the repository that owns the affected behavior, not merely the current checkout or the last
item used. Search its existing issues and relevant linked or active PRs before writing. Read candidate
bodies, comments, acceptance criteria and resolution evidence; titles alone do not establish a match.
The helper lists managed Personal issues; GitHub inspection also covers unmanaged issues and PRs:

```text
python -B <skill-directory>/scripts/create_work_item.py list --root <owning-source-checkout> --state all
python -B <skill-directory>/scripts/create_work_item.py read --root <owning-source-checkout> --item owner/repository#42 --body --comments
gh issue list --repo owner/repository --state all --limit 100 --json number,title,state,url
gh issue view 42 --repo owner/repository --json body,comments,state
gh pr list --repo owner/repository --state all --limit 100 --json number,title,state,url
gh pr view 54 --repo owner/repository --json body,comments,state,closingIssuesReferences
```

Narrow or paginate searches when these results do not cover the relevant work. Match the affected
behavior, known cause, intended outcome and acceptance scope. Shared organization, profile, timing or
a generic agent-problem theme is not enough; an open umbrella is not a default destination.

For a true match, preserve its identity, kind, repair owner, existing requirements and evidence. Refine
the record when the new facts change its requirements, cause, outcome or acceptance criteria; append
a note when only recurrence evidence or repair state changes. An active PR may identify the existing
repair or its linked issue: reconcile that work rather than create a competing record. The helper
updates managed issues only; use the existing GitHub route for a matching PR or unmanaged issue.
For closed work, compare the recurrence with its actual resolution before choosing a follow-up; do
not automatically reopen it or take over its repair.

```text
Request: settings must work across machines.
Existing machine-independent settings work has the same outcome: refine that work and retain its owner.
An agent-productivity umbrella shares only the organization: do not append there.
If no matching settings work exists after searching, create a separate settings item.
```

## Record the result

Only when no relevant record exists, classify the supplied facts: faulty behavior is `bug`; an observed
agent or process error is `mistake`; a deliberate deferral is `debt`; changed product behavior is
`feature`; concrete work with a completion condition is `task`; a user-centered outcome is `story`.

Use `template`, `validate` and `preview` to prepare facts, then create with one stable request ID:

```text
python -B <skill-directory>/scripts/create_work_item.py template --kind story
python -B <skill-directory>/scripts/create_work_item.py validate --input facts.json
python -B <skill-directory>/scripts/create_work_item.py preview --input facts.json
python -B <skill-directory>/scripts/create_work_item.py create --root <owning-source-checkout> --input facts.json --request-id UNIQUE-STABLE-ID
```

For a managed issue refinement, prepare complete facts preserving the existing requirements and kind.
Read the issue immediately before updating and pass that read's `body_hash` as `--expected-hash`; a
changed hash means read and reconcile again, not overwrite with a guessed or stale value:

```text
python -B <skill-directory>/scripts/create_work_item.py read --root <owning-source-checkout> --item owner/repository#42 --body --comments
python -B <skill-directory>/scripts/create_work_item.py validate --input refined-facts.json
python -B <skill-directory>/scripts/create_work_item.py preview --input refined-facts.json
python -B <skill-directory>/scripts/create_work_item.py update --root <owning-source-checkout> --item owner/repository#42 --input refined-facts.json --expected-hash BODY_HASH_FROM_FRESH_READ
```

For evidence-only additions, append material new recurrence facts, the known cause and current repair
state with a stable request ID:

```text
python -B <skill-directory>/scripts/create_work_item.py note --root <owning-source-checkout> --item owner/repository#42 --request-id UNIQUE-STABLE-ID --text-file recurrence.txt
```

Read the changed body or comments back to verify remote persistence before claiming it was recorded.
Recording does not enter execution;
`personal:address-work-item` owns an authorized request to implement its repair.
After an uncertain create or note response, retain the request ID and reconcile with the same command
and `--reconcile-only` before another submission. After an uncertain update, read the issue and
reconcile its current content before another update.
