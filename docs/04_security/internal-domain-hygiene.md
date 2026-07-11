<!--
SPDX-FileCopyrightText: 2026 soundminds.ai
SPDX-License-Identifier: Apache-2.0
-->

# Internal-domain hygiene for narrative files

RelyLoop is a public repository. The narrative state files — [`state.md`](../../state.md)
and [`state_history.md`](../../state_history.md) — are written after every merge
by skills and by humans, in free-form prose. That makes them the highest-risk
place for an operator's internal infrastructure to leak into public view: an
internal hostname, a customer domain, or a private-network host IP written into
a merge narrative is, once pushed, effectively unrecallable (forks and clones
retain it, GitHub serves dangling commits by SHA, and public archives crawl the
repo).

This page is the policy. It is enforced by a two-layer gate so the invariant
holds even when a commit is made outside a hooked clone.

## The invariant

> No plain-text operator domain name, sub-domain name, or private-host IP
> appears in `state.md` / `state_history.md`.

## How to write narrative that satisfies it

Use **human-readable placeholders** instead of literal hosts:

| Instead of…                          | Write…                    |
| ------------------------------------ | ------------------------- |
| `es.prod.acme-corp.example-inc.com`  | `<operator-es-cluster>`   |
| `proxy.intra.customer.net`           | `<corp-proxy>`            |
| `search.bigco.com`                   | `<operator-domain>`       |
| `10.1.4.22` (a specific private host)| `<internal-host>`         |
| a fictional example host             | `foo.example` / `bar.test`|

Angle-bracket placeholders (`<…>`) are invisible to the scanner by
construction, and RFC 2606/6761 reserved names (`.example`, `.test`,
`.invalid`, `.localhost`) are always allowed — use them for illustrative
examples.

### No encoding, ever

Do **not** base64 / hex / hash / encrypt a real domain to "hide" it. Reversible
encoding is not redaction — the data is still there, one decode away — and it
also blinds the scanner (and gitleaks), so you lose detection while gaining
nothing. Scrub to a placeholder; keep the real name out of the file entirely.

### Optional operator-local alias mapping

If you want a durable record of what a placeholder maps to, keep it in the
**gitignored** file `secrets/domain_aliases.yaml` (covered by `secrets/*` in
[`.gitignore`](../../.gitignore)) — never in a tracked file. Suggested shape:

```yaml
# secrets/domain_aliases.yaml — operator-local, gitignored, never committed.
<operator-es-cluster>: es.prod.internal.example-inc.com
<corp-proxy>: proxy.intra.example-inc.com
```

The gate does **not** consult this file; it exists only so an operator can
resolve their own placeholders. Nothing in the repo depends on it.

## Enforcement (two layers)

Both layers run the same script, [`scripts/check_internal_domains.py`](../../scripts/check_internal_domains.py),
against the same allowlist, [`scripts/allowed_public_domains.txt`](../../scripts/allowed_public_domains.txt):

1. **Pre-commit hook** `internal-domains-guard` (`.pre-commit-config.yaml`) —
   the primary gate. Blocks the literal from ever entering a commit object,
   which is the only cheap enforcement point (see the "unrecallable" note
   above).
2. **CI job** `internal domains guard` in
   [`secrets-defense.yml`](../../.github/workflows/secrets-defense.yml) — the
   backstop for commits made outside a hooked clone (GitHub web UI, another
   machine, `--no-verify`). Lives in `secrets-defense.yml` (not `pr.yml`) so
   the `paths-ignore` filter can't skip it.

This mirrors the existing gitleaks + `.env`-filename guards exactly.

### The allowlist

[`scripts/allowed_public_domains.txt`](../../scripts/allowed_public_domains.txt)
lists domains that are, by definition, **public** (this project's own domains,
public services like `github.com` / `api.openai.com`, fictional demo brands).
An entry also covers its sub-domains (`github.com` allows `api.github.com`).
Adding an entry is a public act — the bar is "is this genuinely public
information?" If you are tempted to add an operator/internal hostname, use a
placeholder instead.

## How detection works (and its one blind spot)

A naive FQDN regex drowns in dotted code identifiers (`asyncio.gather`,
`vi.mock`). The scanner therefore only flags a dotted token when its final
label is a plausible real TLD (a curated list that deliberately excludes file
extensions) or an internal pseudo-TLD (`.internal`, `.corp`, `.local`, …). It
also flags RFC 1918 private-host IPv4 literals, while letting universal
constants through (loopback, RFC 5737 doc ranges, link-local incl. the
`169.254.169.254` cloud-metadata address, and `.0`/`.255` network/broadcast
addresses).

**Blind spots (both covered by the write-time placeholder discipline, not the
gate):**

1. A bare hostname with no dot (`es-prod-01`) is indistinguishable from an
   ordinary word and cannot be pattern-detected.
2. An allowlist entry passes **all** its sub-domains (`relyloop.com` passes
   `docs.relyloop.com`), so an internal host under an allowlisted apex would
   not be flagged. This is why the allowlist holds only genuinely-public
   sites and deliberately omits any apex whose sub-domains might be internal
   infrastructure — keep the allowlist minimal.

The gate is the backstop, not the whole defense.

## If a real internal domain has already been pushed

The gate prevents *future* leaks. If a genuinely-sensitive operator domain is
found in already-pushed history, scrubbing the working tree removes it going
forward but it remains in past commit objects — cleaning that requires history
surgery (`git filter-repo`) plus a force-push and cache invalidation, and forks
already have it. Treat that as an incident: scrub the working tree first (stops
the bleeding), then decide whether the exposure warrants a history rewrite.
