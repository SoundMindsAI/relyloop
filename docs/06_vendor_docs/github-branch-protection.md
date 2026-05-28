# GitHub — Branch Protection / Required Status Checks (vendor reference)

Distilled from <https://docs.github.com> on 2026-05-09 (Rulesets path is GitHub's recommended modern API; classic Branch Protection Rules still supported but flagged as having ordering / overlap issues when multiple rules target the same branch). Procedure-only; consult upstream for ACL details, RBAC nuances, and enterprise-specific knobs.

## Why we need this for RelyLoop

`infra_foundation` adds a CI workflow ([`.github/workflows/pr.yml`](../../.github/workflows/pr.yml)) with three jobs that gate every PR. Until those jobs are marked **required** in the GitHub repo settings, a PR with red CI can still be force-merged through the UI — which would defeat the purpose of the workflow.

The plan ([`infra_foundation/implementation_plan.md` §7.5 manual handoff #3](../00_overview/planned_features/infra_foundation/implementation_plan.md)) defers this to a repo-admin manual step because GitHub's branch-protection API requires admin permissions the agent never holds.

## Plan-tier asymmetry — read this before upgrading

GitHub gates rulesets enforcement on plan tier × repo visibility:

| Plan tier | Public repo | Private repo |
|---|---|---|
| **Free** (individual or org) | ✅ Rulesets enforced | ⚠ Rulesets configurable but **NOT enforced** ("Your rulesets won't be enforced on this private repository until you move to GitHub Team organization account") |
| **Pro** (individual, $4/mo) | ✅ Enforced | ✅ Enforced |
| **Team** (org, $4/user/mo) | ✅ Enforced | ✅ Enforced |
| **Enterprise** | ✅ Enforced | ✅ Enforced |

For RelyLoop today: SoundMindsAI is on the Free org plan, the repo is private, so creating the ruleset is informational-only — the rules sit dormant. **The moment the repo flips to public** (planned for MVP1 ship), enforcement activates automatically, no plan change required. Until then, lean on:

- CLAUDE.md Absolute Rule #1 ("Never commit directly to `main`") — the agent refuses to do this.
- CI status visible in the PR UI — humans can see red checks even without the merge being blocked.
- Solo-maintainer discipline (low-risk threat model while no contributors are on the keyboard).

**When to actually upgrade to Team** (in priority order):

1. A second human contributor joins while the repo is still private.
2. You stay private through MVP4 (audit/compliance surfaces appear).
3. You need org-level features (SAML SSO, audit logs, IP allow-lists).

Until one of those triggers, the $4/user/month is buying enforcement of a rule the agent already enforces.

## The three checks to require for `relyloop`

These are the exact strings GitHub will autocomplete in the Rulesets UI (verified via `gh api repos/SoundMindsAI/relyloop/commits/<sha>/check-runs`):

| Check name (paste verbatim) | Source |
|---|---|
| `backend (lint + typecheck + tests + coverage)` | `.github/workflows/pr.yml` `jobs.backend.name` |
| `frontend (lint + typecheck + tests + build)` | `.github/workflows/pr.yml` `jobs.frontend.name` |
| `docker buildx (relyloop/api)` | `.github/workflows/pr.yml` `jobs.docker.name` |

**Note:** GitHub matches by check `name`, not job ID. If a workflow's `name` field changes (e.g., a future PR renames the backend job), the rule silently stops matching and PRs merge without enforcement. After any rename, return to Rulesets and re-add the new name.

---

## Procedure A — Rulesets (RECOMMENDED, modern API)

GitHub's note in the Branch Protection Rules docs flags rulesets as the alternative to use when multiple rules might overlap on the same branch. We use rulesets.

1. Open <https://github.com/SoundMindsAI/relyloop> in a browser. You must be a repo admin.
2. Click the **Settings** tab (top of the page; if you don't see it, you don't have admin).
3. In the left sidebar, under **Code and automation**, click **Rules** → **Rulesets**.
4. Click **New ruleset** → **New branch ruleset**.
5. Fill in the form:
   - **Ruleset Name:** `protect-main-require-pr-ci`
   - **Enforcement status:** **Active** (default — leave it).
6. Under **Target branches**, click **Add a target** → **Include default branch**. (Default = `main` for this repo.)
7. Under **Branch protections**, check **Require a pull request before merging**.
   - Sub-option: **Required approvals** — set to your preference (0 acceptable for solo-maintainer; bump to 1+ when contributors join).
   - Sub-option: **Dismiss stale pull request approvals when new commits are pushed** — recommended.
8. Under **Branch protections**, check **Require status checks to pass**.
   - Sub-option: **Require branches to be up to date before merging** — recommended.
   - **Add the three required checks one at a time:**
     1. Type `backend` in the search box. The full name `backend (lint + typecheck + tests + coverage)` should autocomplete. Click it. **Click the `+` icon to confirm** (this is the canonical gotcha — typing the name without clicking the `+` does NOT add it).
     2. Repeat for `frontend (lint + typecheck + tests + build)`.
     3. Repeat for `docker buildx (relyloop/api)`.
   - You should see all three listed under "Required status checks" before proceeding.
9. (Optional, recommended for production-style hygiene) Also check **Block force pushes** under Branch protections.
10. Scroll to the bottom and click **Create**.

**Verify it took:**

```bash
gh api repos/SoundMindsAI/relyloop/rules/branches/main --jq '.[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context'
```

Expected output (3 lines, in any order):
```
backend (lint + typecheck + tests + coverage)
frontend (lint + typecheck + tests + build)
docker buildx (relyloop/api)
```

---

## Procedure B — Classic Branch Protection Rules (LEGACY, still works)

Use this only if your repo already has classic branch protection rules and you don't want to migrate, or if you're scripting against an older `gh` / API version.

1. **Settings** → **Code and automation** → **Branches**.
2. Under **Branch protection rules**, click **Add classic branch protection rule**.
3. **Branch name pattern:** `main`.
4. Check **Require a pull request before merging** (sub-options as above).
5. Check **Require status checks to pass before merging**.
6. Check **Require branches to be up to date before merging**.
7. In the search box under that, add the three checks listed in the table above (same `+`-icon gotcha applies).
8. Optionally: **Do not allow bypassing the above settings** (so even admins can't merge red PRs).
9. Click **Create** (or **Save changes**).

**Verify:**

```bash
gh api repos/SoundMindsAI/relyloop/branches/main/protection --jq '.required_status_checks.contexts'
```

---

## Common gotchas

| Symptom | Cause | Fix |
|---|---|---|
| Check name doesn't autocomplete in the search box | The check has never run on a branch GitHub has indexed. | Push a commit to a feature branch; wait for CI to start; the name then becomes searchable. |
| You typed the name but it's not in "Required status checks" | Forgot to click the `+` icon. | Click `+` after typing. The list below should populate. |
| Rule shows as configured but red PRs still merge | "Require status checks to pass" is unchecked, OR the bypass list includes you, OR the check name has drifted from `pr.yml`. | Re-open the ruleset; confirm the toggle + the bypass list; compare check names to the workflow file's `name:` field. |
| `gh api ... required_status_checks` returns empty array | The rule wasn't saved (you backed out before clicking Create), or you're looking at the wrong rule type (classic vs ruleset have different endpoints). | Use Procedure A's verification command for rulesets, Procedure B's for classic. |
| Workflow renamed but enforcement silently lapsed | Check name is matched literally; GitHub doesn't follow renames. | After renaming a job, return to the ruleset and add the new name (delete the old). |

## Permissions reminder

Branch protection / rulesets require **Admin** role on the repo. Reads of the rule state work with **Maintain** or higher. The agent never holds admin and cannot perform either procedure — this is always a human step.

## When this needs to change later

- **MVP3** introduces the staging deploy workflow. When `deploy-staging.yml` lands, add its job's check name to the same ruleset.
- **MVP4** introduces SSO + tenant scoping; the bypass list should be tightened to exclude individual users in favor of role-based bypass.
- **GA v1** introduces the release workflow + image-publish workflow; same pattern — add their check names.

## Upstream references

- Rulesets overview: <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets>
- Creating a ruleset: <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository>
- Classic branch protection: <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule>
- `gh api` reference for branches: <https://docs.github.com/en/rest/branches/branch-protection>
