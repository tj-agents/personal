---
name: create-work-item
description: Find and refine a relevant existing personal GitHub work item, or classify and create one when none matches, without starting implementation. Use when a personal bug, mistake, debt, feature, Story or task must be captured.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal GitHub repositories
requires: tj-item, gh
provenance: house
---

# Create a personal work item

This is the recording intent: find the relevant existing work and refine it, or create one record when
none matches. It does not start, assign or track execution.

The source primary checkout's `personal@tj-agents` selection and its GitHub origin select the GitHub tracker.
Creation places the issue on the repository's GitHub Project with status To Do.

## Find the right record

Resolve the repository that owns the affected behavior, not merely the current checkout or the last
item used. Search its existing issues and relevant linked or active PRs before writing. Read candidate
bodies, comments, acceptance criteria and resolution evidence; titles alone do not establish a match.

```text
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
repair or its linked issue: reconcile that work rather than create a competing record.
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

Write the title as the outcome or defect, and a body with the facts, cause when known, and verifiable
acceptance criteria. Create it, label it with its kind, and place it on the board:

```text
gh issue create --repo owner/repository --title "<title>" --body-file body.md --label <kind>
gh project item-add <project-number> --owner <owner> --url <issue-url>
tj item progress <issue-url> --state "To Do"
```

Create a missing kind label with `gh label create <kind> --repo owner/repository` first. Before creating, search
open issues for the same title so a retried request never makes a duplicate.

To refine an issue, read it immediately before editing and rewrite the body with every existing requirement
preserved: `gh issue edit 42 --repo owner/repository --body-file refined.md`. For evidence-only additions, append
the new recurrence facts, known cause and repair state: `tj item comment <issue-url> --body-file recurrence.md`.

Read the changed body or comments back with `tj item resolve <issue-url> --body` before claiming it was
recorded. Recording does not enter execution; `personal:address-work-item` owns an authorized request to
implement its repair.
