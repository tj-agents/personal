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

It installs a `gh` wrapper in `~/.agents-state/bin/bot-identity/` (`gh.exe` on Windows, so PowerShell and
programs pass arguments intact) and gives agent sessions only (Claude `env`, Codex `shell_environment_policy.set`):
`PATH` with the wrapper first, `TJ_AGENT=1`, a dead `GH_TOKEN` with an empty `GH_CONFIG_DIR`, so gh outside the
wrapper has no login, and git config that clears every github.com credential helper except the bot's. `PATH` is a
snapshot, so re-run setup after changing it. Tommy's own terminals are unchanged; setup removes the wrapper from
the user PATH. It also denies the GitHub MCP write tools, which hold Tommy's token.

For an agent, git takes the account from the remote URL, and `gh` from `-R`/`--repo`/`--owner`, GitHub URLs,
`repos|orgs|users/<owner>` API paths, `gh repo` arguments and the checkout's `origin`. If any has the App, it gets a one-hour installation
token, cached until five minutes before expiry; a failed mint stops the command. If all are other accounts, such
as Infonetica, the call uses Tommy's own gh login or git helpers: an agent can act as Tommy there, and that
token also works in the App's accounts. A command naming no account runs unauthenticated, and agents may run only
`gh auth status`. `token --owner <account>` prints a token. Restart Claude and Codex after setup.

This is environment containment, not an OS boundary: an agent can still read Tommy's stores directly
(`gh auth token -u tomjseery`, `git credential-manager get`, `~/.git-credentials`). Only Tommy's credentials
being out of agent reach makes a required approval his alone.
