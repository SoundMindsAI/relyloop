# Runbook — Git-history audit before going public (or a major release)

**Owner:** maintainers (see [`MAINTAINERS.md`](../../MAINTAINERS.md))
**When to run:**

- **Before flipping the repository from private to public** (mandatory — git
  history is permanent once pushed to a public remote).
- Before any **major release** that significantly widens distribution.
- After onboarding a contributor whose commits you haven't audited.

**Why:** `gitleaks` runs as a pre-commit hook and in
[`secrets-defense.yml`](../../.github/workflows/secrets-defense.yml), so *new*
commits are scanned. This runbook covers the **full historical commit graph** —
anything committed before the hooks existed, on any branch, in any commit that's
still reachable. Once the repo is public, history is forever; rewriting it after
the fact invalidates every clone and fork.

This is an **operator decision task**, not a code change: it produces findings
the maintainer team must adjudicate. Record the outcome in the "Audit log"
section at the bottom each time you run it.

---

## 1. Secret scan — full history (`gitleaks`)

`gitleaks` is not a project dependency; run the official image via Docker so you
don't need a local install. The `--log-opts="--all"` flag scans **every commit
on every ref**, not just `HEAD`.

```bash
# From the repo root. --redact keeps any finding's secret value out of the
# terminal + report (so the audit itself doesn't leak).
docker run --rm -v "$PWD:/repo" -w /repo zricethezav/gitleaks:latest \
  detect --source /repo --log-opts="--all" --redact -v \
  --report-path /tmp/gitleaks_history_report.json
echo "exit=$?"   # 0 = no leaks; non-zero = findings (inspect the report)
rm -f /tmp/gitleaks_history_report.json   # scratch artifact — never commit it
```

Interpreting the result:

- **exit 0 / "no leaks found"** → no secrets in any reachable commit. Done with
  this step.
- **non-zero** → open the report. Each finding has a `RuleID`, `File`, `Commit`,
  and `StartLine`. **Inspect each one** — gitleaks' generic rules produce false
  positives (e.g. the `generic-api-key` rule firing on a config-key string like
  `judgment.rating.0` because the surrounding text contains "keys:"). If every
  finding is a verified false positive, record it in the audit log and proceed.
  If any is a real credential, **stop and go to §4 (decision tree).**

> Write the report to `/tmp`, not the repo root —
> `gitleaks_history_report.json` is not in `.gitignore`, and a stray report
> committed into a "secrets audit" PR would be ironic. (See the repo's
> local-stub-hygiene rule.)

## 2. Non-secret leakage scan (manual)

Secrets are not the only thing you don't want public. Sweep history for
customer/partner data, internal infrastructure, and personal data. The
`git log -G<regex>` "pickaxe" searches every commit's diff across all refs.

```bash
# Live credential prefixes (belt-and-suspenders alongside gitleaks)
for pat in 'sk-[a-zA-Z0-9]\{20\}' 'ghp_[a-zA-Z0-9]' 'github_pat_' \
           'AKIA[0-9A-Z]\{16\}' 'xoxb-' 'AIza[0-9A-Za-z]'; do
  echo "$pat: $(git log --all -G"$pat" --oneline | wc -l) commit(s)"
done

# Internal infrastructure hostnames
git log --all -G'soundminds\.(internal|local|corp|priv)' --oneline

# Customer / engagement indicators (case-insensitive)
for term in acme confidential 'do not distribute' proprietary NDA 'design partner'; do
  echo "$term: $(git log --all -i -G"$term" --oneline | wc -l) commit(s)"
done

# Every author/committer email that has ever touched the repo
git log --all --format='%ae%n%ce' | sort -u
```

What to look for:

- **Credential prefixes / internal hostnames** → treat as a secret finding (§4).
- **Customer or "design partner" names, NDA/confidential markers** → these often
  aren't secrets per se but may breach an agreement. Adjudicate with the
  relevant stakeholder before the flip.
- **Author emails** → expect only maintainers' addresses (plus bot `noreply`
  addresses). A stray contributor's *personal* email is usually fine — it's how
  DCO attribution works — but flag any address that shouldn't be public.
  Scrubbing an email from history is a rewrite (§4) and rarely worth it for an
  address the author already uses publicly on GitHub.

## 3. Binary / media review (manual)

Screenshots and screen-recordings can show on-screen data that grep can't see.

```bash
# Sample data + tutorial assets
git ls-files samples/ ui/public/

# Walkthrough recordings (generated from the local demo stack)
git ls-files 'ui/public/guides/**/*.webm'
```

The walkthrough `.webm` files and `samples/*.json` are generated from the
**synthetic demo dataset** (see `scripts/seed_meaningful_demos.py`), so they
should contain no real data. Still: **open one or two** and confirm no real
cluster URL, customer index name, or watermark is visible before the flip.

## 4. Decision tree — when something is found

If §1–§3 surface anything sensitive, **do not flip the repo public yet.**
Choose one:

| Situation | Action |
|---|---|
| A live secret (API key, PAT, password) is in history | **Rotate it immediately** (it's already compromised the moment it was committed), *then* decide whether to also rewrite history. Rotation is non-negotiable; rewrite is optional cleanup. |
| Sensitive non-secret data (customer name, NDA material) that must not be public | **Rewrite history** to remove it before the flip — there's no "rotate" equivalent. |
| The finding is a false positive (example key, version number that looks like an IP, netmask) | Document it in the audit log below and proceed. |

**Rewriting history** (only if you've decided it's necessary) uses
[`git-filter-repo`](https://github.com/newren/git-filter-repo) (the modern
replacement for BFG):

```bash
# Example: purge a file that should never have been committed, from all history
git filter-repo --path secrets/leaked.txt --invert-paths
# Or replace a string everywhere:
#   git filter-repo --replace-text <(echo 'SENSITIVE==>REDACTED')
```

⚠️ **A history rewrite invalidates every existing clone and fork.** Every
collaborator must re-clone. Coordinate it; never do it silently. If the repo is
still private with few clones, this is cheap. After public launch it is
extremely disruptive — which is exactly why this audit runs *before* the flip.

## 5. The flip itself

Changing repository visibility (private → public) is an **operator action** in
GitHub settings, outside this runbook and outside any automation. Only do it
once §1–§3 are clean (or every finding is adjudicated + resolved per §4).

---

## Audit log

Record each run here so the next maintainer has provenance.

| Date | Run by | gitleaks (full history) | Manual scans | Outcome |
|---|---|---|---|---|
| 2026-05-30 | @SoundMindsAI | **1 finding, adjudicated false positive.** `generic-api-key` rule fired on `keys: \`judgment.rating.0\`` in `docs/.../feat_contextual_help/phase2_idea.md` (commit `5671ca1f`) — the literal config-key string `judgment.rating.0`, not a credential. 377 commits scanned. | Credential prefixes: `ghp_` (2 commits) + `github_pat_` (4 commits) — **all false positives**: the token-**redaction** feature's own regex patterns (`backend/app/domain/git/redaction.py`), test fixtures (`ghp_abcdef`), and sentinels (`ghp_TESTTOKENSENTINEL…`). `sk-`/`AKIA`/`xoxb-`/`AIza`: 0. Internal hostname `*.soundminds.internal` (1): only inside the punchlist `idea.md`'s own scan-instruction text — not a real host. `acme` (110): `acme.com` example domain + `acme-products-rich` synthetic demo slug. `NDA`/`design partner`/`proprietary`: substring/concept noise, no real names. IPs: only localhost/private + `192.0.2.1` (RFC 5737 TEST-NET-1 doc range). Author/committer emails: `eric.starr@soundminds.ai` + GitHub/dependabot/Anthropic bot `noreply` only. | **CLEAN.** The single gitleaks finding and all pickaxe hits are confirmed false positives — no real secret, customer datum, or internal host in history. `.webm`/`samples` are synthetic-demo-derived; cleared for the visibility flip pending the maintainer's final media spot-check (§3). |
