<!--
Thanks for sending a PR. A few quick reminders before you hit submit:

- This project uses DCO sign-off. Run `git commit -s` for every commit, or
  amend with `git commit -s --amend`. The DCO check will block the PR
  until every commit has a `Signed-off-by:` trailer.
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`,
  etc.). See CONTRIBUTING.md.
- Never use `--no-verify` to skip pre-commit hooks. If a hook fails, fix
  the root cause.
- If your change touches a public API, the spec, or an absolute rule in
  CLAUDE.md, please call it out in "Notes for reviewers" below.

Security vulnerabilities should not be filed as PRs — see SECURITY.md.
-->

## Summary

<!-- 1–3 bullets. What does this change and why. -->

## Linked issues

<!-- e.g. `Closes #123`. If there is no issue, briefly say why. -->

## Type of change

<!-- Delete the ones that don't apply. -->

- feat (new capability)
- fix (bug fix)
- docs (documentation only)
- chore (tooling, deps, repo hygiene)
- refactor (no behavior change)
- test (adding or updating tests)
- ci / infra (build, deploy, hooks)

## Testing

<!--
What you ran locally. Examples:

- `make test-unit` — 412 passed
- `make test-contract` — 38 passed
- Re-ran `make seed-clusters && make seed-es` against a fresh `make up`
  stack; verified `/healthz` reports `subsystems.elasticsearch_clusters:
  registered=2, healthy=2`.
-->

## Notes for reviewers

<!--
Optional. Things you'd like a reviewer to look at extra-carefully:
schema decisions, prompt changes, anything that could affect production
behavior of operator-merged configs, follow-up items you deferred.
-->

## Checklist

- [ ] Commits are signed off (`git commit -s`) and follow Conventional Commits.
- [ ] New behavior has tests at every layer it touches (unit / integration / contract / E2E).
- [ ] Docs updated (`README.md`, `CLAUDE.md`, `state.md`, `architecture.md`, runbooks under `docs/03_runbooks/`) where applicable.
- [ ] If this changes the spec, the spec was updated first (and the change is referenced above).
