# personal

Personal means personal projects only. Infonetica is work scope, including the `tj-agents/infonetica`
plugin source repository and every worktree. Never select or inject this profile there. GitHub ownership,
a publisher account or a checkout location does not establish personal scope; read the target project's
README.md and AGENTS.md before adoption.

Mandatory standards for explicitly adopted personal projects.

Published as plugin `tj-agents/personal` from the `tj-agents` marketplace.

## Skills

- Policies: `personal:rules`.
- Conventions: `personal:revision`.
- Utilities: `personal:use`, `personal:work-item`, `personal:create-work-item`, `personal:bot-identity`,
  `personal:approve`.
- Workflow: `personal:address-work-item`.

## Adopt a personal project

Explicitly select `personal@tj-agents` through `agent:plugins`, then run the
shipped adoption utility. Its `--selection-tool` option performs both steps together. Use `--mode preview`
to inspect changes, `--mode write` to apply them and `--mode check` in CI. See the
[adoption procedure](.agents/personal/utility/use/SKILL.md) for the complete command.

The mandatory policy is generated into AGENTS.md from one authored body with a source hash. Adoption merges
distinct CLAUDE.md instructions into AGENTS.md and leaves CLAUDE.md as its exact import pointer. This uses
native project instructions, so it does not depend on plugin hook activation. Adoption is complete only after
a passing check and fresh host verification; discovery, installation and version output are insufficient.

The check also rejects retained compatibility declarations. Remove obsolete bindings and migrate actual
callers in the same cutover. Employer projects are outside this profile; personal scope requires explicit adoption.

Adoption leaves existing workflows unchanged. This repository runs its own policy check against candidate
source before merge.

## Personal GitHub work items

Personal owns its GitHub tracker. Selecting `personal@tj-agents` in a repository's `.agents/plugins.json`
selects `personal:work-item`; no other declaration exists. The tracker resolves the source primary checkout
and records issues in its GitHub origin. A created issue is placed on the owner's board named after the
repository and on the owner-wide board named after the owner, created on first use; that needs `gh` with the
`project` scope. Personal never infers scope, selects a provider during read or create,
or configures a cloud account, server, credential store or local backlog.

## Recording and addressing

Use `personal:create-work-item` to classify and record a bug, mistake, debt, feature, Story or task. Recording
preserves the request for later work and does not start implementation. The shipped helper owns deterministic
schemas, rendered bodies, GitHub CRUD and durable request receipts.

Use `personal:work-item` to read, list or view an identified item. Use `personal:address-work-item` for an
existing item after reconciling its identity and repair owner; Workflow owns the goal and execution, and the
mapped Engineering operation owns bounded software delivery. The address helper records factual updates and
closure evidence. A missing or different provider blocks the operation without adopting another queue.

## Agent GitHub identity

`personal:bot-identity` configures a machine for the user's own GitHub App and human reviewer. Its
onboarding page supports creating a new App or enrolling an existing App on another computer. The
plugin contains no preset personal App or account roster. Accepted configuration and keys are retained
through partial setup, and repeat setup reuses valid enrollment. The plugin declares this setup step
for Agent's installer and refresh. See the
[enrollment procedure](.agents/personal/utility/bot-identity/SKILL.md) for commands, credential handling,
required permissions and recovery.

The current integration writes machine-specific identity settings to the user's Claude and Codex
configuration. It is not checkout-local; agent sessions using those settings share that environment.
Repository adoption remains the source of Personal scope, and the wrapper only authorizes configured
GitHub accounts. Human terminals retain their native login.

## Approving the bot's pull requests

[personal:approve](.agents/personal/utility/approve/SKILL.md) (`! tj approve`) is the user's human
approval command. It uses the configured reviewer's native login, verifies that identity, and approves
only the configured bot's eligible PRs in the current session's linked work. It never performs an
account-wide approval sweep or runs as the bot. An agent gives the user the command and PR links;
the user executes it.

## Authoring and verification

```powershell
pwsh .agents/sync-generated.ps1
pwsh .agents/sync-generated.ps1 -Check
```

The layout, the vendored generator and CI come from [Template](https://github.com/tj-agents/template).

Run the onboarding browser acceptance check with an installed Chromium executable:

```sh
uv run python .agents/tests/onboarding_browser.py --browser /usr/bin/chromium --artifacts /var/tmp/personal-onboarding
```

Use `--headed` to observe the browser in the desktop session. The runner exercises the real local page
with synthetic GitHub responses and blocks external requests. Each rendered transition has a bounded
wait; a failure saves a screenshot, rendered state, expected step and browser errors in the artifact
directory. This fixture check complements live enrollment; it does not prove GitHub authentication or
installation readiness. Playwright is a development dependency; the setup runtime uses the standard library.
