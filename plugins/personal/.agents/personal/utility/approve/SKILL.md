---
name: approve
description: Tommy's one command to approve, as tomjseery, the open tj-agents pull requests the bot App authored. Use when handing Tommy PRs to approve; only Tommy runs it, in his own terminal, never an agent.
kind: utility
domain: personal
profile: core
applicability: Tommy's machines after `personal:bot-identity` setup
requires: python, gh
provenance: house
---

# Approve

`tj approve [<repo>]` lists every open `tj-agents` pull request authored by `app/tomjseery-bot` that lacks
tomjseery's approval at its current head or has a pending review request from him, optionally only in
`tj-agents/<repo>`. After one confirmation it approves each as tomjseery with the real `gh` and his own login, then
prints `approved <repo>#<n>` or `failed <repo>#<n>: <reason>` per PR and exits non-zero if any failed.

Only Tommy runs it, in his own terminal. It refuses without an interactive terminal or in an agent session
(`TJ_AGENT` set). Agents hand Tommy the PR links and tell him to run `tj approve`; they never run it.

`personal:bot-identity` setup installs it into the tj bin directory (`TJ_BIN_DIR`, default
`%LOCALAPPDATA%\Programs\tj` on Windows or `~/.local/bin` on Linux) and `setup --check` verifies it.
