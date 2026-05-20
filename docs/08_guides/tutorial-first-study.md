# Tutorial — your first relevance study with RelyLoop

In this tutorial you'll go from `git clone` to "PR opened in GitHub" in under
30 minutes on a fresh laptop. You'll register a local Elasticsearch cluster,
generate LLM relevance judgments against 1,000 sample products, run a 10-trial
Optuna study to tune `multi_match` field boosts, read the LLM-generated
digest, and (optionally) open a PR against the public
[`SoundMindsAI/relyloop-test-configs`](https://github.com/SoundMindsAI/relyloop-test-configs)
config repo with the recommended parameters.

This is the same operator path the [smoke
test](../../backend/tests/smoke/test_tutorial_path.py) exercises in CI on
every PR — if you hit a step that doesn't work, file an issue and link
this guide.

---

## Step 0 — Prerequisites

| Requirement | Details |
|---|---|
| Docker (incl. `docker compose` v2) | 24+ — `make up` orchestrates 7 containers |
| 16 GB RAM | Elasticsearch + OpenSearch each consume ~1 GB; 8 GB will OOM |
| One LLM provider (see below) | Required for judgment generation + digest narrative |
| `git` and `make` | Standard host tooling |
| GitHub Personal Access Token (PAT) | **Optional** — only needed for Step 10 ("Open PR") |

You need **one** of these LLM provider paths:

### Path A — Hosted OpenAI

```bash
echo "sk-..." > ./secrets/openai_key   # the file is git-ignored
```

Default model is `gpt-4o-mini`. Cost ceiling for the full tutorial:
**~$0.05** (5-query judgment generation + 10-trial study + digest narrative).

### Path B — Local LLM (Ollama / LM Studio / vLLM / TGI)

Set `OPENAI_BASE_URL` and `OPENAI_MODEL` in `.env` before `make up`. Example
for Ollama:

```bash
echo 'OPENAI_BASE_URL=http://host.docker.internal:11434/v1' >> .env
echo 'OPENAI_MODEL=llama3.1:70b-instruct' >> .env
echo 'placeholder' > ./secrets/openai_key   # local servers don't validate the key
```

The startup capability check probes your local endpoint and surfaces missing
capabilities (chat / function-calling / structured-output) in `/healthz`.
**Important:** judgment generation needs structured-output support — pick a
model from the tested matrix in
[`docs/01_architecture/llm-orchestration.md` §"OpenAI-compatible endpoints"](../01_architecture/llm-orchestration.md).

If your local model lacks structured output, judgment generation will surface
`LLM_PROVIDER_INCAPABLE` and you'll need to use Path A or a different model.

> Both paths are first-class. The rest of the tutorial is identical regardless
> of which one you pick.

---

## Step 1 — Clone + `make up`

```bash
git clone https://github.com/SoundMindsAI/relyloop.git
cd relyloop
make up
```

`make up` runs `scripts/install.sh` (auto-generates required secrets +
placeholder optional ones), then `docker compose up -d`. First-run cold time:
~90 seconds. Brings up 7 containers: `postgres`, `redis`, `api`, `worker`,
`elasticsearch`, `opensearch`, `ui`. The first run also builds the `ui`
image locally (~3–5 min cold; cached on subsequent runs).

Wait until the API is healthy:

```bash
curl -s http://localhost:8000/healthz | jq .status
# → "ok"
```

If `/healthz` shows `subsystems.openai = missing_key`, you skipped Step 0
Path A or Path B — go back and configure one before continuing.

**If something went wrong:** check `docker compose ps` for any container in
`Restarting`. If Elasticsearch keeps crashing, your host probably needs more
RAM allocated to Docker Desktop (Settings → Resources → at least 8 GB).
`make logs` tails the api + worker logs.

---

## Step 2 — `make migrate`

```bash
make migrate
```

Applies the Alembic chain to the head revision (currently
`0007_conversations_messages`) and initializes the Optuna RDB schema. Without
this, every API call returns 500 with `relation "..." does not exist`.

**If something went wrong:** if `make migrate` errors with
`api container is not running`, the API container failed Step 1 — re-run
`make up` and check `make logs`.

---

## Step 3 — `make seed-clusters`

```bash
make seed-clusters
```

Registers two cluster rows: `local-es` (Elasticsearch 9 at
`http://elasticsearch:9200`) and `local-opensearch` (OpenSearch 2 at
`http://opensearch:9200`). Idempotent — safe to re-run.

You can also register a cluster via the UI at
[`http://localhost:3000/clusters`](http://localhost:3000/clusters), but the
seed script saves you the form-filling.

**Must run before Step 4** because `seed_es.py` resolves the cluster URL via
`cluster_repo.get_active_cluster_by_name("local-es")`.

**If something went wrong:** if both clusters fail with `ClusterUnreachable`,
your Elasticsearch / OpenSearch containers haven't finished their healthchecks
yet. Wait 30 seconds and try again.

---

## Step 4 — `make seed-es`

```bash
make seed-es
```

Wraps `docker compose exec api python -m backend.app.scripts.seed_es`. Loads
1,000 sample products (Amazon ESCI subset, CC-BY-4.0) from
`samples/products.json` into the local-es `products` index. Idempotent —
DELETE+recreates the index every run, so re-running with edited samples
cleanly removes orphans.

Verify the count:

```bash
curl -s http://localhost:9200/products/_count | jq .count
# → 1000
```

**If something went wrong:** if the script reports `local-es cluster not
registered`, you skipped Step 3.

---

## Step 5 — Create a query set from `samples/queries.csv`

Open the UI:

```bash
open http://localhost:3000/query-sets
```

Click **"Create query set"** and fill the form:

- **Name:** `tutorial_queries`
- **Cluster:** pick `local-es` from the dropdown — no UUID typing required;
  the field is a searchable list of every cluster the API knows about,
  with health-status dots so you can see at a glance which clusters are
  reachable
- **Description:** anything (e.g. "Tutorial queries from ESCI")

Submit. On the query-set detail page, click **"Add queries"** and
upload `samples/queries.csv` — the dialog accepts JSON or CSV with the
file's `query_id,query_text` shape directly.

48 queries should now be attached to the query set.

You can do the same via the API. The example below resolves the
cluster's UUIDv7 from the registry first, then posts the query set
using a shell variable — no manual UUID copy-paste:

```bash
# Resolve the cluster UUID from its name (no copy-paste, no typos).
LOCAL_ES_ID=$(curl -s http://localhost:8000/api/v1/clusters \
  | jq -r '.data[] | select(.name=="local-es") | .id')

QS_ID=$(curl -s -X POST http://localhost:8000/api/v1/query-sets \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"tutorial_queries\",\"cluster_id\":\"$LOCAL_ES_ID\",\"description\":\"ESCI tutorial\"}" \
  | jq -r .id)

curl -X POST http://localhost:8000/api/v1/query-sets/$QS_ID/queries \
  -H "Content-Type: application/json" \
  -d "$(jq -Rsn --rawfile csv samples/queries.csv \
        '{queries: ($csv | split("\n") | .[1:] | map(select(length>0)) | map(split(",") | {query_text: .[1]}))}')"
```

**If something went wrong:** if `LOCAL_ES_ID` came back empty, the
cluster wasn't registered — re-run Step 4 first.

---

## Step 6 — Generate judgments via LLM

This is the only LLM round-trip the tutorial walks you through. Cost is
~$0.01–$0.05 with `gpt-4o-mini` against a 5-query subset (or all 48).

In the UI, open the query-set detail page you created in Step 5 (e.g.
`http://localhost:3000/query-sets/<id>`) and click **"Generate judgments"**
in the associated-judgment-lists card. Fill in:

- **Cluster:** `local-es`
- **Target index:** `products`
- **Current template:** create one in Step 7 first if needed (or use the
  smoke template in `samples/templates/product_search.j2`)
- **Rubric:** `Rate 0-3 by relevance to the query.`

Click **Generate**. The judgment-list status moves through
`generating` → `complete` (~30–60s).

**If you see `OPENAI_NOT_CONFIGURED`:** you skipped Step 0 — populate
`./secrets/openai_key` (or `OPENAI_BASE_URL` for local LLM) and
`make down && make up`.

**If you see `LLM_PROVIDER_INCAPABLE`:** your local model doesn't support
structured output. Switch to a model from the tested matrix in
[`llm-orchestration.md`](../01_architecture/llm-orchestration.md).

---

## Step 7 — Create a query template

Open:

```bash
open http://localhost:3000/templates
```

Click **"Create template"**. Paste the contents of
`samples/templates/product_search.j2` into the **Body**
field. The template renders an Elasticsearch `multi_match` query with
three declared params:

| Param | Type | Range |
|---|---|---|
| `title_boost` | float | 0.5 – 10 |
| `description_boost` | float | 0.5 – 10 |
| `bullet_points_boost` | float | 0.5 – 10 |

`tie_breaker` and `fuzziness` are intentionally hard-coded in the template so
the search-space stays under the platform's `10^6` cardinality cap on a
10-trial budget. To tune them too, switch to a 30-trial study and pull them
into the search-space.

Submit. Note the template ID for Step 8.

---

## Step 8 — Open `/chat` and ask the agent to tune

```bash
open http://localhost:3000/chat
```

Send a message like:

> Tune `product_search v1` against `tutorial_queries` on `local-es:products`,
> max 10 trials.

The agent will introspect the cluster + judgment list, propose a
`create_study` tool call with a search-space, and ask you to confirm.
Reply **"yes"**. The study queues immediately.

The chat agent is one of two ways to create a study; you can also click
**"Create study"** on [`/studies`](http://localhost:3000/studies) directly.
The 5-step wizard auto-fills Step 4 ("Search space") from the selected
template's declared params, so you only need to tweak the JSON if the
defaults don't match the ranges you want to tune — no paste-from-file
step required.

---

## Step 9 — Watch the study run + read the digest

Open:

```bash
open http://localhost:3000/studies
```

Click the study you just created. The detail page shows trials filling in
real-time (10 total, ~30 seconds each). Once `status = completed`, the
digest tab renders:

- **Narrative summary** — 2–3 sentences describing what won and why
- **Recommended config** — `*.params.json` shape, ready to paste into your
  search-config repo
- **Parameter importance** — bar chart from Optuna's importance evaluator

If the digest narrative is empty or you see `OPENAI_NOT_CONFIGURED` in the
worker logs, your LLM provider is misconfigured — re-do Step 0.

> **Stop here if you don't have a GitHub PAT.** You've completed the
> Karpathy loop end-to-end. Step 10 is the optional "ship it" path.

---

## Step 10 — (Optional) Click "Open PR"

In the study's digest, click the **"Promote to proposal"** button on the
recommended config. You're routed to the proposal detail page; click
**"Open PR"** in the top-right.

This opens a Pull Request against the public
[`SoundMindsAI/relyloop-test-configs`](https://github.com/SoundMindsAI/relyloop-test-configs)
repo with the recommended params written into the corresponding
`*.params.json` file. GitHub PATs are registered per `config_repo`: drop
the PAT at `./secrets/<auth_ref>` (the same `auth_ref` you provided when
registering the config repo via `POST /api/v1/config-repos`). Without
the per-repo PAT file the button surfaces a configuration error —
that's the only step that needs write access to the repo.

To use your own config repo: register it via the API (no UI form ships in
MVP1) with your fork's URL + an `auth_ref` value, drop the PAT at
`./secrets/<auth_ref>`, then re-run from Step 8.

```bash
curl -X POST http://localhost:8000/api/v1/config-repos \
  -H "Content-Type: application/json" \
  -d '{"name":"my-config-fork","provider":"github","repo_url":"https://github.com/<you>/<repo>","config_path":"params/","auth_ref":"my_pat"}'
```

---

## Where to next

- The full feature set is in [`docs/02_product/mvp1-user-stories.md`](../02_product/mvp1-user-stories.md).
- The architectural decisions are in
  [`docs/01_architecture/`](../01_architecture/) — start with
  [`system-overview.md`](../01_architecture/system-overview.md).
- The umbrella product spec is at
  [`docs/00_overview/product/relevance-copilot-spec.md`](../00_overview/product/relevance-copilot-spec.md).
- File feedback or bug reports at
  [GitHub Discussions](https://github.com/SoundMindsAI/relyloop/discussions).

Welcome to RelyLoop.
