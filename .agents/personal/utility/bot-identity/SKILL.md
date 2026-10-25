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

Agents act on the pinned existing `tomjseery-bot` GitHub App (ID `5397553`) recorded in
`~/.agents-state/github-app/tomjseery-bot.json`, with its private key beside it, in tomjseery, tj-agents and
Concertable. GitHub never lets
an author approve its own PR. [github-actions:merge-policy](https://github.com/tj-agents/github-actions/blob/main/.agents/github-actions/utility/merge-policy/SKILL.md)
owns Tommy's human approval requirement. Infonetica never gets the App; there agents keep Tommy's credentials.

Tommy runs setup once per machine because it edits his host settings. A machine without a valid enrollment fails
closed with an exact onboarding action; normal setup and checks never open a browser. With Tommy present, use the
explicit local-browser wizard: it identifies the pinned existing App, accepts one newly generated App PEM, verifies
it against GitHub before storing protected local state, and never prints the key or token. The original downloaded
PEM remains in the browser/OS download location; remove it there after successful enrollment.

```text
python -B <skill-directory>/scripts/bot_identity.py setup --onboard  # python3 on Linux/macOS
python -B <skill-directory>/scripts/bot_identity.py setup
python -B <skill-directory>/scripts/bot_identity.py setup --check
```

If the wizard reports a missing account, Tommy installs the same App at
`https://github.com/apps/tomjseery-bot/installations/new` for tomjseery, tj-agents and Concertable, then re-runs
setup. The key enrollment is retained, but setup does not claim readiness or alter agent host settings until all
three installations verify.

Readiness also requires `repository_creation:write` on the App and its `tj-agents` installation, so agents can
create repositories there. It deliberately rejects `administration:write`: creating repositories does not need
authority to administer, delete, or transfer existing repositories. A failed check identifies the exact App or
`tj-agents` installation settings page for Tommy to correct; setup never changes GitHub permissions itself.

It installs a `gh` wrapper in `~/.agents-state/bin/bot-identity/` (`gh.exe` on Windows, so PowerShell and
programs pass arguments intact) and gives agent sessions only (Claude `env`, Codex `shell_environment_policy.set`):
`PATH` with the wrapper first, `TJ_AGENT=1`, a dead `GH_TOKEN` with an empty `GH_CONFIG_DIR`, so gh outside the
wrapper has no login, and git config that clears every github.com credential helper except the bot's. `PATH` is a
snapshot, so re-run setup after changing it. Tommy's own terminals are unchanged; setup removes the wrapper from
the user PATH. It also denies the GitHub MCP write tools, which hold Tommy's token.

For an agent, git takes the account from the remote URL, and `gh` from `-R`/`--repo`/`--owner`, GitHub URLs,
`repos|orgs|users/<owner>` API paths, `gh repo` arguments and the checkout's `origin`. Only the three named accounts
can receive an App token; a missing installation for one stops the command and never falls back to Tommy. If all
are other accounts, such
as Infonetica, the call uses Tommy's own gh login or git helpers: an agent can act as Tommy there, and that
token also works in the App's accounts. A command naming no account runs unauthenticated, and agents may run only
`gh auth status`. `token --owner <account>` prints a token. Restart Claude and Codex after setup.

This is environment containment, not an OS boundary: an agent can still read Tommy's stores directly
(`gh auth token -u tomjseery`, `git credential-manager get`, `~/.git-credentials`). Only Tommy's credentials
being out of agent reach makes a required approval his alone.
