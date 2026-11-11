---
name: approve
description: Approve the configured bot's open pull requests for the current agent session's work as the configured human reviewer. Use when those PRs await the user's approval; the user runs the command and an agent never runs it.
kind: utility
domain: personal
profile: core
applicability: machines configured through personal:bot-identity
requires: python, gh, agent-store, tj-item
provenance: house
---

# Approve

`tj approve` uses the human reviewer and GitHub App selected through
[personal:bot-identity](../bot-identity/SKILL.md). It uses that human's native
`gh` login and verifies the authenticated GitHub account before submitting any review. The App identity,
permitted accounts and human reviewer come from protected local configuration, not a shipped username.
The human needs their own native `gh` login on each computer; bot enrollment does not create that login.

```text
! tj approve
```

The user runs this command. It lists the pending PRs and approves them without another confirmation;
an agent never executes it on the user's behalf. When approval is required, put the command on the
user's clipboard with `cli:clip` and include it and the exact PR links in the reply.

For a separate human shell that does not inherit the conversation's session variables, give
`tj approve --session <host:id>` with the originating conversation's exact registered session handle.
Verify that registration and its linked work before the handoff. This selector takes precedence over
inherited launch and native session variables; an unknown explicit session fails without approving.
Do not create machine-specific helper scripts or ask the user to configure session environment variables.

The scope is the current agent session's work. It resolves the session in agent-store from
`--session` when supplied, else `TJ_RUN_LAUNCH_ID`, then `claude:<CLAUDE_CODE_SESSION_ID>` or
`codex:<CODEX_THREAD_ID>`. It takes the
session's linked items, its launch's item, and recursively the items and bound sessions of launches it
started. For each item, `tj item prs` supplies candidate PRs. Only open PRs authored by the configured
bot, in configured accounts, and awaiting the configured reviewer's approval at the current head are
eligible. A pending review request also makes a matching PR eligible. It never sweeps an account or
organization, and never approves a human-authored PR as a substitute for correct bot authorship.

After each approval it arms squash auto-merge pinned to the approved head, so the PR merges as soon as its
required checks pass and no session has to come back to merge it. A new push cancels it. The command
prints the approval and merge result for each PR and exits nonzero if any approval or auto-merge fails. Missing
or mismatched human sign-ins fail before review writes. No current session, no linked work or no
eligible PRs produces a short result and approves nothing.

Bot setup installs the launcher in the tj bin directory (`TJ_BIN_DIR`, default
`%LOCALAPPDATA%\Programs\tj` on Windows or `~/.local/bin` on Linux) and checks it with `setup --check`.
The launcher runs its managed script copy under `~/.agents-state/bin/bot-identity/`, which plugin refresh
converges. Setup also denies `tj approve` and `tj-approve` to Claude agents; those denials and command
guidance are environment controls, not an OS boundary around the human's account.
