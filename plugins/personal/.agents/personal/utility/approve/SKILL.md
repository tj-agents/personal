---
name: approve
description: Tommy's one command to approve, as tomjseery, the bot App's open pull requests for the current agent session's work. Use when PRs await Tommy's approval; Tommy runs it as `! tj approve`, an agent never runs it.
kind: utility
domain: personal
profile: core
applicability: Tommy's machines after `personal:bot-identity` setup
requires: python, gh, agent-store, tj-item
provenance: house
---

# Approve

`tj approve` covers only the current agent session's work, never an account-wide sweep. It resolves the session
in agent-store from `TJ_RUN_LAUNCH_ID`, else `claude:<CLAUDE_CODE_SESSION_ID>` or `codex:<CODEX_THREAD_ID>`, and
takes its linked items, its launch's item and, recursively, the items of the launches it started and their bound
sessions. For each item, `tj item prs` lists its pull requests; it keeps the open ones authored by
`app/tomjseery-bot` that lack tomjseery's approval at the current head or have a pending review request from him.

```text
! tj approve
```

Typing the command is the approval: it lists the PRs, then approves them without asking, whatever stdin is. It
approves with the real `gh` and tomjseery's own login, prints `approved <repo>#<n>` or
`failed <repo>#<n>: <reason>` per PR and exits non-zero if any failed. No session, nothing linked or nothing
waiting is reported in one line and approves nothing.

When PRs await Tommy, put the line `! tj approve` on his clipboard with `cli:clip` and include it and the PR links
in the reply. Never run it: `personal:bot-identity` setup denies it to Claude agents, installs it into the tj bin
directory (`TJ_BIN_DIR`, default `%LOCALAPPDATA%\Programs\tj` on Windows or `~/.local/bin` on Linux) and
`setup --check` verifies both. That launcher runs a copy of this script in `~/.agents-state/bin/bot-identity/`,
which every Claude and Codex session start replaces with the running plugin's when it differs.
