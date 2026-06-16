# Corporate-network install troubleshooting

**For operators running `make up` from inside a corporate network** (HTTPS proxy, Artifactory or similar registry mirror, TLS interception). Symptom-first: paste your error block into the search, find the matching section, follow the fix.

If you'd rather understand the architecture before debugging a specific symptom, read [`docs/01_architecture/deployment.md` §"Corporate registry proxy support"](../01_architecture/deployment.md) first — it's the "why" doc; this is the "what error → what fix" doc.

---

## Quick decision tree

```
make up fails with...

  "403 Forbidden" / "401 Unauthorized" from registry-1.docker.io
  "failed to resolve source metadata for docker.io/..."
  "no such host: registry-1.docker.io" / "no such host: ghcr.io"
  ──→  Registry pull failures (§1)

  "SELF_SIGNED_CERT_IN_CHAIN" (npm/pnpm)
  "unable to get local issuer certificate" (curl/openssl)
  "x509: certificate signed by unknown authority" (Go)
  "CERTIFICATE_VERIFY_FAILED" (Python)
  ──→  TLS verification errors (§2)

  "Could not resolve host:" (curl)
  "Temporary failure resolving" (apt/curl)
  "Connection refused" / "Connection timed out"
  "ETIMEDOUT" / "ECONNREFUSED" (Node)
  ──→  Egress / DNS failures (§3)

make up succeeds, but...

  Worker stays "unhealthy" in `docker compose ps`
  ──→  Worker no_proxy missing (§4)

  Runtime calls to OpenAI / GitHub / clusters fail
  ──→  Runtime egress not proxied (§5)
```

If the wrapper around `docker compose build` ([`scripts/install.sh`](../../scripts/install.sh) `diagnose_build_failure`) detects a known signature, it prints a diagnostic block pointing at the right section here. Sections below have more detail than the inline diagnostic.

---

## §1 — Registry pull failures

### Symptom

```
ERROR [worker] resolve image config for docker-image://docker.io/library/python:3.14-slim@sha256:c845...
target worker: failed to solve: failed to resolve source metadata for
docker.io/library/python:3.14-slim: unexpected status from HEAD request to
https://registry-1.docker.io/v2/library/python/manifests/sha256:c845...: 403 Forbidden
```

Or `401 Unauthorized`, or `no such host: registry-1.docker.io`, or the same shape for `ghcr.io` (the uv image).

### Cause

Your corporate network blocks direct access to public container registries (`docker.io`, `ghcr.io`). All container image pulls have to go through an internal mirror (Artifactory, Nexus, Harbor, JFrog Container Registry, etc.).

### Fix

Set the two registry-prefix vars in `.env` (trailing slash required — they concatenate directly onto the image reference):

```bash
# In .env
BASE_REGISTRY=<your-proxy>/    # for python + node from Docker Hub
GHCR_REGISTRY=<your-proxy>/    # for ghcr.io/astral-sh/uv
```

The vars feed every service's `build.args` in `docker-compose.yml`, so the FROM lines in both Dockerfiles resolve through the proxy.

### Artifactory namespace layouts — pick the one your proxy uses

**Unified prefix (most common — single proxy hosts both Docker Hub + GHCR under the same URL):**

```bash
BASE_REGISTRY=artifactory.your-corp.com/
GHCR_REGISTRY=artifactory.your-corp.com/
```

**Split paths (separate virtual repos per upstream registry):**

```bash
BASE_REGISTRY=artifactory.your-corp.com/docker-virtual/
GHCR_REGISTRY=artifactory.your-corp.com/ghcr-virtual/
```

Ask your Artifactory admin which layout your proxy uses, or probe with `curl -fSL https://<proxy>/v2/library/python/manifests/3.14-slim` — if it returns a manifest, unified; if 404, try the split paths.

### Verify

```bash
docker compose config | grep -E "BASE_REGISTRY|GHCR_REGISTRY"
```

You should see all 4 service `build.args` blocks (migrate / api / worker / ui) with your proxy URL, and the 3 backend services' `GHCR_REGISTRY` too.

### Background

[`docs/01_architecture/deployment.md` §"Corporate registry proxy support"](../01_architecture/deployment.md) — full architectural rationale, the OSSF Scorecard pin posture, and why the digest stays literal on the FROM line.

---

## §2 — TLS verification errors

### Symptom

The errors look different depending on which tool fails first, but they all mean the same thing:

```
# npm / pnpm
npm error code SELF_SIGNED_CERT_IN_CHAIN
npm error errno SELF_SIGNED_CERT_IN_CHAIN
npm error request to https://registry.npmjs.org/pnpm failed, reason:
self-signed certificate in certificate chain

# curl / openssl
curl: (60) SSL certificate problem: unable to get local issuer certificate

# Python (requests / httpx / openai SDK)
ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: unable to get local issuer certificate

# Go (alembic via psycopg's libpq, future agents, etc.)
x509: certificate signed by unknown authority
```

### Cause

Your corporate HTTPS proxy performs **TLS interception** (sometimes called "SSL inspection" or "MITM proxy"): it terminates the TLS connection, inspects the traffic, then re-encrypts it with a corp-internal CA. Your laptop trusts that internal CA — it's been pre-installed by IT. **But the container doesn't.** Its trust store has only the public CAs that ship in `python:3.14-slim` (Debian's standard `ca-certificates`) and `node:26-bookworm-slim`. So every HTTPS handshake inside the container fails verification.

> **Why dropping the cert in `./secrets/corp_ca.crt` isn't, by itself, enough — and what the images do about it.** The build copies your cert into `/usr/local/share/ca-certificates/` and runs `update-ca-certificates`, which rebuilds the **OpenSSL** system bundle at `/etc/ssl/certs/ca-certificates.crt`. `curl`, `openssl`, and the Python runtime (httpx/requests/openai SDK, via `certifi`-or-system fallback) honor that bundle. **But two of the build's tools maintain their OWN trust stores and ignore the system bundle:**
>
> - **Node.js (npm + pnpm)** uses a CA list compiled into the binary. This is the classic `make corp-ca-extract` succeeded **but `npm install -g pnpm@9` still fails with `SELF_SIGNED_CERT_IN_CHAIN`** symptom. Fixed by `NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt` (set in `ui/Dockerfile`), which makes Node ADD the system bundle's certs to its built-in roots.
> - **uv** ships bundled `webpki-roots` and ignores the OS store unless told otherwise. Fixed by `UV_NATIVE_TLS=1` (set in the backend `Dockerfile`), which switches uv to the platform trust store.
>
> Both env vars are wired into the Dockerfiles already, so you don't set them by hand — but if you see an npm/pnpm or uv TLS failure **after** confirming the cert is installed (the Verify step below passes), this is why, and a stale image is the usual culprit: rebuild with `make up` (or `docker compose build --no-cache ui` to force a clean rebuild).

### Fix — recommended: `make corp-ca-extract`

The corp CA cert that's MITM-ing your traffic is **literally in the TLS chain** every time you make an HTTPS connection through the proxy. Instead of finding the cert file on disk or extracting it from a keychain, just read it off the wire:

```bash
make corp-ca-extract    # probes the live chain, saves the corp root to ./secrets/corp_ca.crt
make up                 # cert gets installed into the image trust store during build
```

The target runs [`scripts/corp-ca-extract.sh`](../../scripts/corp-ca-extract.sh), which:

1. Probes `https://www.google.com:443` (override with `PROBE_HOST=…`) via `openssl s_client -showcerts`.
2. Walks the returned cert chain and identifies the LAST cert (typically the root used to sign the chain).
3. Compares it against ~27 known public roots (DigiCert, ISRG / Let's Encrypt, Google Trust Services, GlobalSign, etc.).
4. If the last cert is a public root → "No corporate TLS interception detected" — your network isn't MITM-ing, no cert needed.
5. If the last cert is NOT a known public root → saves it to `./secrets/corp_ca.crt`. Print the cert's Subject so you can verify.

If the script picks the wrong cert (e.g., your proxy doesn't include the root in the chain it serves), fall back to the manual path below.

### Fix — manual fallback

Drop your corporate CA certificate (PEM format) at `./secrets/corp_ca.crt` directly:

```bash
cp /path/to/corp-ca.crt ./secrets/corp_ca.crt
make up
```

Common sources for the cert file, in increasing operator-friction order:

1. **Ask IT** — most corporate IT departments publish the root CA cert at a known internal URL (`https://it.your-corp.com/certs/root-ca.pem` or similar).
2. **Linux trust store** — `ls /usr/local/share/ca-certificates/` (Debian/Ubuntu) or `ls /etc/pki/ca-trust/source/anchors/` (RHEL/Fedora) usually contains exactly the corp-installed CAs.
3. **macOS keychain** — extract by name:

   ```bash
   # Omits the keychain path so the search covers both login + system keychains
   # (corp IT often installs CAs into the user's login keychain, not System).
   security find-certificate -p -c "Acme Corp Root CA" > ~/corp-ca.pem
   ```

4. **Chrome / Edge** — Settings → Privacy & Security → Security → Manage certificates → find the corp CA → Export as PEM.
5. **Firefox** — Preferences → Privacy & Security → View Certificates → Authorities → find the corp CA → Export.
6. **Direct probe** (manual version of `make corp-ca-extract`) — useful when the auto-extract picks the wrong cert:

   ```bash
   openssl s_client -showcerts -connect any-proxied-https-host:443 < /dev/null \
     | awk '/BEGIN CERT/,/END CERT/' > /tmp/chain.pem
   # The last certificate in /tmp/chain.pem is typically the corp root CA.
   # Split and pick the right one, save as ./secrets/corp_ca.crt.
   ```

### Verify

```bash
# Confirm the cert landed in the image trust store
docker run --rm relyloop/api:dev \
  openssl x509 -in /usr/local/share/ca-certificates/corp_ca.crt -noout -subject -issuer

# Confirm the bundle includes the cert content
docker run --rm relyloop/api:dev \
  awk '/BEGIN CERT/{c++} END {print c, "certs in bundle"}' /etc/ssl/certs/ca-certificates.crt
```

The first command should print the subject and issuer of your corp CA. The second tells you how many CAs the bundle holds — should be roughly `(default count) + 1`.

### Background

[`docs/01_architecture/deployment.md` §"Corporate TLS interception"](../01_architecture/deployment.md) — error signatures table, mechanism, why we use a BuildKit secret instead of bare COPY.

---

## §3 — Egress / DNS failures

### Symptom

The build can pull base images (so §1 is fixed), but `RUN` steps that fetch from public package repos fail:

```
# apt (Debian mirrors)
Err:1 http://deb.debian.org/debian bookworm/main amd64 ca-certificates
  Temporary failure resolving 'deb.debian.org'

# pip / uv (PyPI)
Could not fetch URL https://pypi.org/simple/numpy/: There was a problem confirming
the ssl certificate: ... ConnectTimeoutError

# npm / pnpm (npmjs)
npm error code ETIMEDOUT
npm error errno ETIMEDOUT
npm error network request to https://registry.npmjs.org/pnpm failed
```

Or curl errors like `Could not resolve host: registry.npmjs.org` or `Connection refused`.

### Cause

Your corporate network doesn't allow direct outbound HTTP to the public internet — all external HTTP has to go through an HTTP proxy.

### Fix

Set the three proxy vars in `.env`:

```bash
http_proxy=http://<proxy-host>:<port>
https_proxy=http://<proxy-host>:<port>
no_proxy=<your-corp-domains>,localhost,127.0.0.1,10.0.0.0/8,169.254.169.254,host.docker.internal,postgres,redis,elasticsearch,opensearch,solr,api,worker,migrate
```

These are passed to BuildKit as **predefined ARGs** — BuildKit auto-forwards them into every `RUN` step's environment without requiring `ARG` declarations in the Dockerfile, AND intentionally excludes them from `docker history`, so the proxy URL never gets baked into the image.

### The `no_proxy` checklist — three categories you must include

1. **Compose service names** (`postgres,redis,elasticsearch,opensearch,solr,api,worker,migrate`). Without these, the worker's call to `http://elasticsearch:9200` gets routed through the corp proxy, which has no path to those Compose-internal hostnames. The worker stays unhealthy. See §4.
2. **`host.docker.internal`**. Without it, local-LLM dev (`OPENAI_BASE_URL=http://host.docker.internal:11434` for Ollama, LM Studio, vLLM) breaks — the corp proxy intercepts the local-machine call.
3. **Cloud metadata + VPC** (`169.254.169.254,10.0.0.0/8`). EC2 / cloud metadata + internal VPC ranges must skip the proxy or cloud-deployed installs misbehave.

### Background

[`docs/01_architecture/deployment.md` §"Corporate HTTP proxy"](../01_architecture/deployment.md) — full architecture, the build-time vs runtime split, the predefined-ARG mechanism.

---

## §4 — Worker stays "unhealthy" after `make up` succeeds

### Symptom

```
$ docker compose ps
NAME           STATUS
relyloop-api-1     Up (healthy)
relyloop-worker-1  Up (unhealthy)
```

Worker logs may show silent timeouts on calls to `http://elasticsearch:9200`, `http://redis:6379`, or `http://postgres:5432`.

### Cause

You set `http_proxy` / `https_proxy` in `.env` for §3, but `no_proxy` is either empty or doesn't include the Compose service names. Result: the worker tries to call `http://elasticsearch:9200`, the Linux HTTP libraries see "matches `http_proxy`, no exemption", and route the call to the corp proxy — which has no DNS for `elasticsearch` (a Compose-internal hostname).

### Fix

Add the Compose service names to `no_proxy` in `.env` (see §3 for the full recommended value):

```bash
no_proxy=...,postgres,redis,elasticsearch,opensearch,solr,api,worker,migrate
```

Then `docker compose restart worker` to pick up the new env var (no rebuild needed — proxy vars come from Compose's `environment:` block at runtime).

### Verify

```bash
docker compose exec worker env | grep -i proxy
```

You should see `no_proxy` with all the service names.

---

## §5 — Runtime calls to OpenAI / GitHub fail after `make up` succeeds

### Symptom

Build succeeded, containers are healthy, but API logs show OpenAI / GitHub / cluster HTTP timeouts. Inside the api container:

```bash
docker compose exec api curl -fsSL https://api.openai.com/v1/models
# Connection timed out / SSL error / 403
```

### Cause

Two possibilities:

**A.** You set `http_proxy` etc. as host env vars when running `make up`, but they're not in `.env` — so the build picked them up but Compose's runtime `environment:` block reads `${http_proxy:-}` and gets empty.

**B.** TLS interception (§2) is happening on the runtime path. The image has the public CA bundle but not the corp CA, so the openai SDK / httpx / requests rejects the proxy's cert.

### Fix

For **A**: move the vars from your shell into `.env`. Both layers read `${VAR:-}` from `.env` at compose time.

For **B**: drop the corp CA cert at `./secrets/corp_ca.crt` and run `make up` to rebuild the image with the cert installed. After the image rebuild, runtime egress will trust the corp CA.

### Verify

```bash
# Check both build-time and runtime proxy resolution
docker compose config | grep -E "http_proxy|https_proxy|no_proxy" | head -20

# Test outbound HTTPS from inside the api container
docker compose exec api python -c \
  "import httpx; print(httpx.get('https://api.openai.com/v1/models', timeout=5).status_code)"
```

The first command should show non-empty values in BOTH `build.args` and `environment:` blocks for each service. The second should print `401` (no API key) — anything else (timeout, SSL error) means the runtime egress path is misconfigured.

---

## Verifying your full config in one shot

```bash
# All proxy/registry vars compose actually sees
docker compose config | grep -E "BASE_REGISTRY|GHCR_REGISTRY|http_proxy|https_proxy|no_proxy"

# Compose secret file states
ls -la ./secrets/

# CA cert in the built image
docker run --rm relyloop/api:dev \
  openssl x509 -in /usr/local/share/ca-certificates/corp_ca.crt -noout -subject 2>&1
```

If the third command returns `Could not read certificate` or the file isn't there, the `./secrets/corp_ca.crt` file is empty (the default placeholder) — drop your corp CA cert into it and rerun `make up`.

---

## See also

- [`docs/01_architecture/deployment.md` §"Corporate registry proxy support"](../01_architecture/deployment.md) — the architecture (why these env vars exist, what they feed, the build-time vs runtime split).
- [`docs/03_runbooks/local-dev.md` §"Stack will not start"](local-dev.md) — general (not corp-network-specific) troubleshooting.
- [`CLAUDE.md`](../../CLAUDE.md) §"Key Runbooks" — index of all RelyLoop runbooks.
