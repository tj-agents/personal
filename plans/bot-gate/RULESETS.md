# Bot gate rulesets (draft, not applied)

Status: draft for Tommy's review. Nothing here has been applied; no GitHub writes were made.

## Mechanism

The existing schema is `.github/merge-policy.json`, owned by
`tj-agents/github-actions` `.agents/github-actions/utility/merge-policy/scripts/merge_policy.py`. Core's
`machine_events.py` notices a committed change to that file on a default branch and runs
`merge_policy.py reconcile --repo OWNER/NAME` as Tommy, which writes the repository ruleset `merge-policy`.
So the draft is a policy file per repository, not hand-written rulesets.

`{"agents_may_merge": false, "required_checks": [...]}` renders this ruleset (`merge_policy.py render`):

```json
{
  "name": "merge-policy",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}],
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 1,
      "dismiss_stale_reviews_on_push": true,
      "require_code_owner_review": false,
      "require_last_push_approval": true,
      "required_review_thread_resolution": false}},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": false,
      "required_status_checks": [{"context": "<each required check>"}]}}
  ]
}
```

That is: PR required, one approval of the latest push, stale approvals dismissed, required checks, no
deletion or force-push. The only bypass actor is the repository admin role, through a PR only, so this means
"Tommy only" while Tommy is the only admin. The bot must never be one, nor the App hold Administration write.

## Proposed policy files

Required checks come from the check runs on each repository's latest PR head (read 2026-10-23). None of
these repositories has a `merge-policy.json` or any ruleset today. Path-filtered and post-merge-only jobs
(`publish`, `regenerate`, dotnet `scaffold.yml`) are excluded, because a required check must run on every PR.

| Repository | `required_checks` |
| --- | --- |
| tj-agents/core | `ci-required` |
| tj-agents/template, dotnet, react, nvim, rust, work, work-items, python, personal, github | `verify / hosts`, `verify / verify (ubuntu-latest)`, `verify / verify (windows-latest)` |
| tj-agents/nvim (also) | `policy / check (ubuntu-latest, python3)`, `policy / check (windows-latest, python)` |
| tj-agents/github-actions | the three `verify / ...` checks, `Verify the portable workflow writer (ubuntu-latest)`, `Verify the portable workflow writer (windows-latest)` |
| tj-agents/azure | the three `verify / ...` checks, `Actions Lint`, `Scaffold (ubuntu-latest)`, `Scaffold (windows-latest)` |
| tj-agents/cpp | `generated`, `isolated-resolution (ubuntu-latest)`, `isolated-resolution (windows-latest)`, `repository-binding` |
| tj-agents/marketplace | `verify (ubuntu-latest)`, `verify (windows-latest)`, `policy / check (ubuntu-latest, python3)`, `policy / check (windows-latest, python)` |
| tj-agents/cli | `test (ubuntu-latest)`, `test (windows-latest)`, `policy / check (ubuntu-latest, python3)`, `policy / check (windows-latest, python)` |
| tomjseery/* public, non-archived (16 repos) | `[]`: none has any check run |

Example, `tj-agents/personal/.github/merge-policy.json`:

```json
{
  "agents_may_merge": false,
  "required_checks": ["verify / hosts", "verify / verify (ubuntu-latest)", "verify / verify (windows-latest)"]
}
```

Decision needed: core and template push generated files to `main` after merge (`git push origin HEAD:main`).
Under this ruleset that push fails unless the policy sets `"ci_pushes_default_branch": true`, which adds a
second bypass actor (GitHub Actions, always). Either accept that bypass for those two repositories, or move
regeneration into the PR.

Not covered: Concertable has the App too and is inside the policy owners, but is outside this draft.

## Private repositories

`tj-agents/infonetica` and `tj-agents/docs` are private. `GET repos/<repo>/rulesets` returns 403: "Upgrade
to GitHub Pro or make this repository public to enable this feature." A ruleset there needs a paid plan
(GitHub Team for the tj-agents organization; Pro covers user-owned repositories) or the repository made
public. Until then nothing on GitHub stops an agent merging there, and `merge_policy.py sync` skips them.

## Apply checklist (Tommy)

1. Confirm Tommy is the only tj-agents owner and the only admin on each repository, and that the App has no
   Administration write and is not a bypass actor.
2. Decide the core/template Actions bypass.
3. Add each `.github/merge-policy.json` by PR and merge it. A policy that names a check its PRs never report
   blocks every merge, so compare `required_checks` with the PR's checks first.
4. Let the machine listener reconcile, or run as Tommy from his own terminal, not an agent session:
   `python -B <machine skill>/scripts/machine_events.py --repo OWNER/NAME`. For a one-off:
   `merge_policy.py apply --repo OWNER/NAME --policy <file> --dry-run`, then without `--dry-run`.
5. Verify with `merge_policy.py check --repo OWNER/NAME --policy <file>`. On one repository, check that a bot
   PR cannot merge without Tommy's approval and that a bot approval of a Tommy push does not count.
6. Re-run `bot_identity.py setup` and restart Claude and Codex, so agents push as the bot. The rulesets only
   gate merges if Tommy's own credentials are out of agent reach; see the bot-identity skill's limits.
