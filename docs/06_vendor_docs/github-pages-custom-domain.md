<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# GitHub Pages — custom domain + DNS (relyloop.com)

Distilled reference for publishing the MkDocs Material site (`website/`) to
**GitHub Pages** at the apex domain **relyloop.com**, with the DNS configured
at **GoDaddy**. Pinned to the actual relyloop.com configuration verified
2026-05-31. Upstream sources + access date at the bottom.

**Used by:** the `deploy-docs.yml` workflow (publishes `website/` to Pages on
push to `main` touching `website/**`); any operator wiring or debugging the
relyloop.com custom domain.

---

## TL;DR — the working relyloop.com configuration

| Layer | Setting | Value |
|---|---|---|
| Pages source | Settings → Pages → Build and deployment → **Source** | **GitHub Actions** (NOT "Deploy from a branch" — the workflow uses `actions/deploy-pages`) |
| Pages custom domain | Settings → Pages → **Custom domain** | `relyloop.com` (auto-populated from the `website/docs/CNAME` file in the build) |
| Repo CNAME file | `website/docs/CNAME` | `relyloop.com` (MkDocs copies it into the built site; do NOT delete it) |
| DNS — apex `A` (×4) | GoDaddy DNS, Name `@` | `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` |
| DNS — `www` | GoDaddy DNS, Name `www` | `CNAME` → `@` (follows the apex; `CNAME → soundmindsai.github.io.` is the GitHub-recommended alternative — both work) |
| HTTPS | Settings → Pages → **Enforce HTTPS** | tick **after** the Let's Encrypt cert provisions (can take up to ~1h after DNS is correct) |
| Default Pages URL | — | `https://soundmindsai.github.io/relyloop/` (301-redirects to the custom domain once set) |

The four apex `A` IPs are GitHub's published Pages IPs and are the **only**
IPv4 values an apex domain should point at. Do not keep any other apex `A`
record (e.g. a registrar parking IP) alongside them — see "GoDaddy gotchas".

---

## Apex vs. www vs. subdomain (GitHub's record-type rules)

GitHub Pages accepts `A`, `AAAA`, `ALIAS`, `ANAME`, or `CNAME` records for a
custom domain. Which you use depends on the domain shape:

- **Apex / root** (`relyloop.com`) — cannot be a `CNAME` (DNS forbids CNAME at
  a zone apex). Use **all four `A` records** (IPv4) and, optionally, **all four
  `AAAA` records** (IPv6). A registrar that supports `ALIAS`/`ANAME` may instead
  point the apex at `soundmindsai.github.io` — GoDaddy does **not** offer
  ALIAS/ANAME, so we use the four `A` records.
- **`www` subdomain** — a single `CNAME`. GitHub recommends
  `www → <user>.github.io.` (`soundmindsai.github.io.`). We use `www → @`
  (CNAME to the apex), which resolves to the same Pages IPs and is equally
  valid.
- **Any other subdomain** (e.g. `docs.relyloop.com`) — a single `CNAME` to
  `soundmindsai.github.io.`.

### Optional IPv6 (`AAAA`) — not currently set, not required

GitHub publishes IPv6 apex addresses; adding them lets IPv6-only clients reach
the site. They are **optional** — absence does not block the site or HTTPS.
If added, the Name is `@` and the four values are:

```
2606:50c0:8000::153
2606:50c0:8001::153
2606:50c0:8002::153
2606:50c0:8003::153
```

⚠️ A **wrong or stale `AAAA`** record (e.g. left pointing at a previous host) is
a top cause of "site unreachable over IPv6" / cert failures. If you don't add
the correct GitHub AAAA set, add none.

---

## HTTPS / TLS certificate

- GitHub auto-provisions a **Let's Encrypt** certificate once it detects the
  custom domain resolving to Pages. **It can take up to ~1 hour** (occasionally
  longer) after the DNS is correct.
- Until the cert is issued, **Settings → Pages shows "Enforce HTTPS —
  Unavailable for your site because your domain is not properly configured to
  support HTTPS."** This message is **also** shown during normal
  provisioning — it does not by itself mean the DNS is wrong. Verify the DNS
  independently (see "Verification") before assuming a misconfiguration.
- **To trigger / re-trigger provisioning** (GitHub's official remedy after a
  DNS change): Settings → Pages → **clear** the Custom domain field → **Save**
  → wait ~30s → **re-enter** `relyloop.com` → **Save**. This forces a fresh DNS
  check + cert request.
- Tick **Enforce HTTPS** only after the cert lands (the checkbox un-greys).

### CAA records (optional, conditional)

A `CAA` record is **not required**. GitHub's rule is conditional: *if* the
domain has any `CAA` records, at least one must authorize `letsencrypt.org`,
or cert issuance fails. With **no `CAA` records** (relyloop.com's current
state) any CA — including Let's Encrypt — may issue, which is fine. To be
explicit you may add: `@ CAA 0 issue "letsencrypt.org"`.

---

## Verification (works around local DNS caching)

Right after a DNS change the **local resolver** keeps the old answer until the
TTL (1h) expires. To check the real state, query public resolvers via
DNS-over-HTTPS and force-resolve curl to a Pages IP:

```bash
# Authoritative-ish view via public DoH resolvers (bypasses local cache):
curl -s "https://dns.google/resolve?name=relyloop.com&type=A" \
  | python3 -c "import sys,json;print([a['data'] for a in json.load(sys.stdin).get('Answer',[])])"
# Expect: the four 185.199.108-111.153 IPs.

# Confirm GitHub is serving the real site (HTTP needs no cert):
curl -s -o /dev/null -w "%{http_code} %header{server}\n" \
  --resolve relyloop.com:80:185.199.108.153 http://relyloop.com/
# Expect: 200 GitHub.com

# Real nav pages (not the placeholder) return 200, not 404:
for p in "" roadmap/ getting-started/install/ engines/solr/; do
  curl -s -o /dev/null -w "/$p -> %{http_code}\n" \
    --resolve "relyloop.com:80:185.199.108.153" "http://relyloop.com/$p"
done

# Cert state (null until provisioned):
gh api repos/SoundMindsAI/relyloop/pages \
  --jq '{cname, https_certificate: .https_certificate.state, https_enforced}'
```

A `server: GitHub.com` response with `200`s on real nav paths means the
domain + deploy are correct and only the cert is pending. A non-GitHub
`server` header (e.g. `DPS/…`) with a `200` home page but `404` subpages means
the apex is still pointing at the old host/parking page — fix the `A` records.

---

## GoDaddy gotchas

- **Parking / "coming soon" page.** Before the `A` records were set,
  relyloop.com resolved to GoDaddy parking IPs (`13.248.243.5`,
  `76.223.105.230`, served by `DPS/…`). GoDaddy serves this via a default
  parking `A` record and/or the **Domain Forwarding** feature (a separate
  section from DNS records). If the placeholder persists after adding the four
  GitHub `A` records, **delete any leftover apex `A` row** and **turn off
  Domain Forwarding**.
- **Name field for the apex** is `@` (the exported zone uses `@`; the web UI
  may show the full domain `relyloop.com`). Both denote the zone apex.
- **System records you cannot/should not delete:** the two `NS @ →
  ns59/ns60.domaincontrol.com.` and the `SOA @` records are GoDaddy-managed.
  Leave them.
- **Unrelated records are harmless:** `pay CNAME → paylinks.commerce.godaddy.com.`
  (GoDaddy commerce), `_domainconnect CNAME` (GoDaddy automation), and the
  `_dmarc TXT` (email policy) do not affect Pages.
- **Custom domain must be added in the repo first**, then DNS — adding DNS
  before the repo custom domain can leave the domain unverifiable for a cycle.

---

## Reference: the verified relyloop.com zone (2026-05-31)

The records that matter for Pages (full export lives with the domain at
GoDaddy; this is the Pages-relevant subset, confirmed correct):

```dns
$ORIGIN relyloop.com.
@      3600 IN A      185.199.108.153
@      3600 IN A      185.199.109.153
@      3600 IN A      185.199.110.153
@      3600 IN A      185.199.111.153
@      3600 IN NS     ns59.domaincontrol.com.
@      3600 IN NS     ns60.domaincontrol.com.
www    3600 IN CNAME  @
; unrelated-but-harmless: pay (CNAME), _domainconnect (CNAME), _dmarc (TXT), SOA
; not set (optional): AAAA ×4 (IPv6), CAA (letsencrypt.org)
```

**Verdict:** correct for GitHub Pages apex hosting. The only optional additions
are the four `AAAA` IPv6 records and an explicit `CAA` — neither is required
for HTTPS.

---

## Sources

Accessed 2026-05-31:

- [Managing a custom domain for your GitHub Pages site — GitHub Docs](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site) — apex `A`/`AAAA` IPs, `www`/subdomain `CNAME` rules, UI steps, propagation timing.
- [Troubleshooting custom domains and GitHub Pages — GitHub Docs](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/troubleshooting-custom-domains-and-github-pages) — "Enforce HTTPS" unavailability, up-to-1h cert timing, remove-and-re-add remedy, conditional CAA/`letsencrypt.org` rule.
- [About custom domains and GitHub Pages — GitHub Docs](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/about-custom-domains-and-github-pages) — apex vs. subdomain definitions, wildcard-record warning.
- GoDaddy ↔ GitHub Pages community guides (the parking-page / "coming soon" gotcha + where GoDaddy keeps DNS vs. Forwarding): [Carlos Roso](https://carlosroso.com/gh-pages-with-godaddy-domain/), [Medium (Heejin Sim)](https://medium.com/@nbblks/how-to-set-up-godaddy-domain-with-github-pages-eaa65f88a8ec). GoDaddy has no official single "connect to GitHub Pages" page; its generic [Add an A record](https://www.godaddy.com/help/add-an-a-record-19238) article covers the apex `A` record mechanics.

Refresh this doc if GitHub changes the published Pages IPs (they have been
stable at `185.199.108–111.153` for years) or if relyloop.com's DNS provider
changes away from GoDaddy.
