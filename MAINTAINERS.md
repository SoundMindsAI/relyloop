# Maintainers

This file lists the people with commit and merge rights on the `main`
branch of this repository.

Last updated: 2026-05-27.

| Name | GitHub | Contact | Role | Affiliation | Areas |
|---|---|---|---|---|---|
| Eric Starr | [@SoundMindsAI](https://github.com/SoundMindsAI) | `eric.starr@soundminds.ai` · [@Starrman777 on X](https://x.com/Starrman777) · [LinkedIn](https://www.linkedin.com/in/starrman/) | Project lead, maintainer | soundminds.ai | All subsystems |

**Note on contact channels:** the email and socials above are for casual outreach, design conversations, and "is RelyLoop right for my team?" questions. They are **not** for security disclosures (use [SECURITY.md](SECURITY.md)) or bug reports (use [GitHub Issues](https://github.com/SoundMindsAI/relyloop/issues)).

At v0.1, the project has a single active maintainer, employed by
soundminds.ai. This is stated openly so that contributors and downstream
users can size the bus factor honestly. Operationally this means the
project lead self-merges their own PRs after CI is green; the governance
rules that would normally require multi-maintainer `+1` quorum are
suspended under the transitional rule documented in
[GOVERNANCE.md](GOVERNANCE.md#how-decisions-are-made). The plan to grow
the maintainer set across organizations is in
[GOVERNANCE.md](GOVERNANCE.md) ("Transition plan").

## Responsibilities

Maintainers are expected to:

- Review pull requests in their areas of ownership within a few business
  days (US Eastern Time).
- Triage incoming issues — label, ask for missing info, route to the right
  template, close as appropriate.
- Follow the contribution norms in [CONTRIBUTING.md](CONTRIBUTING.md):
  Conventional Commits, DCO sign-off on every commit, no force-push to
  `main`, squash-merge.
- Adhere to the decision-making rules in [GOVERNANCE.md](GOVERNANCE.md):
  lazy consensus for routine work, explicit `+1`s for substantive
  changes.
- Handle security reports per [SECURITY.md](SECURITY.md) when assigned.

## Becoming a maintainer

See [GOVERNANCE.md](GOVERNANCE.md#how-to-become-a-maintainer) for the
nomination flow and the realistic bar.

## Branch protection (operator setup notes)

These notes apply to whoever administers the GitHub repository. They are
intentionally kept in the repo (not in a maintainer's head) so the setup
survives a maintainer transition.

**At v0.1 with N=1 maintainer**, the safe branch-protection configuration
on `main` is:

- ✅ Require a pull request before merging.
- ✅ Require status checks to pass before merging — mark these as required:
  `DCO sign-off check`, `secrets-defense`, and the `pr.yml` job names
  (backend, frontend, docker-build).
- ✅ Require conversation resolution before merging.
- ✅ Require linear history (matches the squash-merge convention).
- ❌ Do **not** "Require approvals" (≥1). GitHub forbids a user from
  approving their own PR; with N=1 maintainer this toggle deadlocks the
  project lead's ability to merge their own work.
- ❌ Do **not** "Require review from Code Owners" while N=1, for the same
  reason — CODEOWNERS routes everything to the lone maintainer.
- ❌ Do **not** "Include administrators" while N=1 with the above
  approval/CODEOWNERS toggles enabled, otherwise the lead cannot bypass
  their own deadlock.

**When N≥2**, flip the three ❌ toggles to ✅ in the same PR that adds the
second maintainer, and update this section.

The matching configuration in the operator's own checkout (DCO sign-off
hook locally, etc.) is in [CONTRIBUTING.md](CONTRIBUTING.md).

## Emeritus

None yet. When a maintainer steps back, we will move their row to an
**Emeritus** section below and update CODEOWNERS in the same PR.
