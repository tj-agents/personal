---
name: bot-identity
description: Configure agent GitHub access through the user's own GitHub App. Use when setting up a new or existing bot on a machine, repairing agent authentication, or changing the accounts the bot may access.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal projects using GitHub App authorship
requires: python
provenance: house
---

# Bot identity

The user selects their GitHub App, human reviewer and permitted GitHub accounts during onboarding. The
protected local record is `~/.agents-state/github-app/identity.json`; it contains that configuration and
the local key location. The plugin ships no personal App, account roster or reviewer identity. Project
adoption determines Personal scope; account ownership and checkout location do not establish it.

Use the existing setup check before changing enrollment. Ordinary setup converges local wrappers and
host settings; `--check` reports readiness without writing. Neither opens a browser. With the user
present and enrollment explicitly authorized, `--onboard` opens the local setup page.

```text
python3 -B <skill-directory>/scripts/bot_identity.py setup --check
python3 -B <skill-directory>/scripts/bot_identity.py setup --onboard
python3 -B <skill-directory>/scripts/bot_identity.py setup
```

Use `python` instead of `python3` on Windows. Runtime prerequisites are Python 3.12+, OpenSSL and `gh`.

For an existing bot on a new computer, public details can prefill the same page. This example uses
fictitious identities; repeat `--account` for each intended account. Omit `--reviewer` to detect the
human's native `gh` username.

```text
python3 -B <skill-directory>/scripts/bot_identity.py setup --onboard --app sample-dev-bot --reviewer sample-dev --account sample-dev --account sample-projects
```

The page offers two paths. **Existing App** selects the user's App by its public name or URL and accepts
an existing or newly issued PEM directly in the browser. A second computer enrolls into that same App;
it does not create another App or repeat existing GitHub installations. **New App** uses GitHub's
manifest flow to prefill registration; the user reviews and creates their App on GitHub, then the local
callback exchanges the one-time code and protects the resulting key. The user completes credential entry
and GitHub security approvals in the supported UI. Never request, print or paste keys or tokens in chat.
After key enrollment, the user can explicitly select discovered existing installations; discovery does
not authorize every account automatically.

A new computer still needs a trusted key or signer for the selected App. A human GitHub login does not
authenticate as the bot. Valid local enrollment is reused, including after a partial setup: missing
installations resume at the installation step, while accepted configuration and keys survive cancellation.
A one-use manifest key interrupted before verification is retained as protected `<slug>.pending.pem`.
A Verify retry or ordinary setup verifies and promotes it; it cannot authenticate commands while pending.
Connection and permission failures do not authorize creating another App or replacing a key. If the user
selects a downloaded PEM, the source file remains in its browser/OS location after enrollment.

Readiness verifies the selected App and its installations for the configured accounts, plus required
permissions declared for each account. Write access to `administration` is rejected. Failures identify the relevant
App or installation settings; setup does not silently change GitHub permissions. Agent host settings are
written only after readiness succeeds.

Setup installs the `gh` wrapper and `personal:approve` launcher under the managed local runtime. Plugin
refresh converges their shipped code without replacing the user's identity record. The wrapper resolves
the target account from explicit `gh` arguments or Git's remote, using the checkout's `origin` only when
no explicit account is supplied. Multiple target accounts, unconfigured accounts and missing installations
fail closed; agent commands never fall back to the human's credentials. Agents may run only `gh auth status`
from the `gh auth` command family. The low-level `token` command prints a secret and is not a diagnostic.

The current host integration writes user-level `~/.claude/settings.json` and `~/.codex/config.toml`.
It gives agent sessions the wrapper-first `PATH`, `TJ_AGENT=1`, an unauthenticated default `GH_TOKEN`, a
separate `GH_CONFIG_DIR`, and Git helpers that use the selected bot. This environment can affect every
agent session using those host settings; it is not checkout-local or an OS credential boundary. Ordinary
human terminals keep their native `gh` login. Re-run setup after changing `PATH` and restart Claude and
Codex to load changed settings.

Setup installs and checks the human approval command and the Claude agent denials for `tj approve` and
`tj-approve`. When the user's approval is required, follow [personal:approve](../approve/SKILL.md): give
the user the command and PR links; an agent never runs it. A required review must come from the configured
human, not the App that authored the PR. GitHub approval policy remains with the adopting repository.

After the App creates or readies a PR, the wrapper resolves the agent session's own work item the way
`tj approve` does and runs `tj item link <ref> <url>`, then prints the approval reminder. When the session
has no linked item, several items, no agent-store registration, or the link fails, it prints that the PR is
not reachable by `tj approve` instead. Link the session (`agent-store link --session <host:id> --item <ref>`)
and the PR (`tj item link <ref> <url>`) before handing it over.
