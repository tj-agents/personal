---
name: bot-identity
description: Make agents push, open PRs and call GitHub as Tommy's GitHub App in his personal accounts, so only Tommy can approve and merge. Use when giving Tommy PRs to approve, setting up a machine for agents, when a push or gh call from an agent fails to authenticate, or when changing which accounts the App covers.
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

Run setup only for an explicitly adopted personal Git checkout: its `.agents/plugins.json` selects
`personal@tj-agents` from `tj-agents/marketplace` and selects neither `work@tj-agents` nor
`infonetica@tj-agents`. `--root <checkout>` selects that checkout explicitly; otherwise setup uses the current
directory. A machine without a valid enrollment fails closed with an exact onboarding action; normal setup and
checks never open a browser. With Tommy present, use the explicit local-browser wizard: it identifies the pinned
existing App and reuses a valid enrolled key. Only a missing or revoked key requires a newly generated App PEM,
verified against GitHub before protected local storage. It never prints the key or token. Remove any original
downloaded PEM through the browser or OS after successful enrollment.

```text
# From C:\Users\TommySeery\source\repos\personal-notes, an adopted personal checkout:
python -B <skill-directory>/scripts/bot_identity.py setup --onboard  # python3 on Linux/macOS
python -B <skill-directory>/scripts/bot_identity.py setup
python -B <skill-directory>/scripts/bot_identity.py setup --check

# From elsewhere, select that same checkout explicitly:
python -B <skill-directory>/scripts/bot_identity.py setup --root C:\Users\TommySeery\source\repos\personal-notes --check
```

The wizard checks current readiness immediately, links to the next App permission or installation settings step,
and rechecks while Tommy completes it. Install the same App for tomjseery, tj-agents and Concertable when requested,
then accept the required `tj-agents` permissions. Permission failures and transient API errors retain the enrolled
key and allow retry in the same page. Once readiness verifies, the same setup invocation continues automatically;
agent host settings remain untouched until then. Browser launch failure or the ten-minute deadline closes the
local wizard; rerun `setup --onboard` to continue.

Readiness requires `repository_creation:write` and `organization_projects:write` on the App and its accepted
`tj-agents` installation, for repository creation and organization Projects. It rejects `administration`
write access: creating repositories does not need authority to administer, delete, or transfer existing
repositories. A failed check identifies the exact App or
`tj-agents` installation settings page for Tommy to correct; setup never changes GitHub permissions itself.

It installs a `gh` wrapper in `~/.agents-state/bin/bot-identity/` (`gh.exe` on Windows, so PowerShell and
programs pass arguments intact), but writes agent identity settings only to
`<checkout>/.claude/settings.local.json` and `<checkout>/.codex/config.toml`; it never writes global Claude or
Codex identity settings. Those checkout settings give agent sessions (Claude `env`, Codex
`shell_environment_policy.set`) `PATH` with the wrapper first, `TJ_AGENT=1`, a dead `GH_TOKEN` with an empty
`GH_CONFIG_DIR`, so gh outside the wrapper has no login, and git config that clears every github.com credential
helper except the bot's. `PATH` is a snapshot, so re-run setup after changing it. Tommy's own terminals are
unchanged; setup removes the wrapper from the user PATH. It also denies the GitHub MCP write tools, which hold
Tommy's token.

Before every wrapper or credential-helper command, the tool rechecks that the current checkout is explicitly
personal. A checkout selecting `work@tj-agents` or `infonetica@tj-agents` is never personal: it uses Tommy's own
gh login or git helpers and never receives an App token. For a selected personal checkout, git takes the account
from the remote URL, and `gh` takes it first from explicit `-R`/`--repo`/`--owner`, GitHub URLs,
`repos|orgs|users/<owner>` API paths and `gh repo` arguments; only when none is explicit does it use the checkout's
`origin`. Commands naming multiple explicit owners are rejected. Only the three named accounts can receive an App
token; a missing installation for one stops the command and never falls back to Tommy. A command naming no account
runs unauthenticated, and agents may run only `gh auth status`. `token --owner <account>` prints a token. Restart
Claude and Codex after setup.

Every PR handed to Tommy for approval carries the `!` command he invokes in the agent terminal. It bypasses the
wrapper and approves each PR as `tomjseery`, stopping at the first failure; an agent never runs it. After a
successful `gh pr create` (not draft, `--web` or `--dry-run`) or `gh pr ready` in the App's accounts, the wrapper prints that PR's filled
command on stderr in every repository, whatever plugins it selects. For several PRs in one reply, give one command
from `approval <url>...`, which refuses PRs outside the App's accounts:

```text
python -B <skill-directory>/scripts/bot_identity.py approval https://github.com/<owner>/<repo>/pull/<number> ...
```

This is environment containment, not an OS boundary: an agent can still read Tommy's stores directly
(`gh auth token -u tomjseery`, `git credential-manager get`, `~/.git-credentials`). Only Tommy's credentials
being out of agent reach makes a required approval his alone.
