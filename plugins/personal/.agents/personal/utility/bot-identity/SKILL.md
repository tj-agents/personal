---
name: bot-identity
description: Make agents push, open PRs and call GitHub as Tommy's GitHub App in his personal accounts, so only Tommy can approve and merge. Use when setting up a machine for agents, when a push or gh call from an agent fails to authenticate, or when changing which accounts the App covers.
kind: utility
domain: personal
profile: core
applicability: Tommy's machines; GitHub accounts where the App is installed
requires: python
provenance: house
---

# Bot identity

Agents act on GitHub as the App recorded in `~/.agents-state/github-app/<slug>.json` (with its private key
beside it) in every account the App is installed on: tomjseery, tj-agents and Concertable. GitHub never lets
an author approve its own PR, so a ruleset needing one approval of the latest push is satisfied only by
Tommy. Infonetica never gets the App; there agents keep Tommy's credentials.

Run once per machine, after the App record exists; Tommy runs it, because it edits his host settings:

```text
python -B <skill-directory>/scripts/bot_identity.py setup     # python3 on Linux/macOS
```

It installs a `gh` wrapper in `~/.agents-state/bin/bot-identity/` at the front of the user PATH, and gives
agent sessions only (Claude `env`, Codex `shell_environment_policy.set`) `TJ_AGENT=1` plus a git
credential helper for github.com. Tommy's own terminals are unchanged: without `TJ_AGENT` the wrapper runs
the real `gh` untouched. It also denies the GitHub MCP write tools, which hold Tommy's token.

For an agent, `gh` and `git push` pick the account from `-R`/`--repo`, a `repos/<owner>/` API path, or the
checkout's `origin`. An installed account gets a one-hour installation token, cached until five minutes
before expiry; any other account falls through to Tommy's normal credentials. `token --owner <account>`
prints a token. Restart Claude and Codex after setup.
