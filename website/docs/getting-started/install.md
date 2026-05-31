# Install

!!! abstract "Summary"
    RelyLoop installs as a Docker Compose stack — clone the repo, run
    `make up`, and the whole system (API, worker, Postgres, Redis,
    Elasticsearch, OpenSearch) comes up on one machine. There is no `pip
    install`; RelyLoop is a deployed stack, not a library.

## System requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| Docker | 24+ with Compose v2 | latest stable |
| RAM | 16 GB | 32 GB |
| Free disk | ~16 GB | 32 GB+ |
| OS | Linux or macOS (x86-64 / arm64) | — |

Elasticsearch and OpenSearch each take ~1 GB of heap by default. If you index
a large corpus, bump `ES_HEAP_SIZE` in `.env`.

## Supported engine versions

| Engine | Versions | Status |
|---|---|---|
| Elasticsearch | 8.11+ / 9.x | shipped (MVP1) |
| OpenSearch | 2.x / 3.x | shipped (MVP1) |
| Apache Solr | 9.x / 10.x | shipped (MVP2) |

All three are reached through a single `SearchAdapter` Protocol — the same
study workflow runs unchanged across engines.

## Install

```bash
git clone https://github.com/SoundMindsAI/relyloop.git
cd relyloop

make up          # generates secrets, builds images, brings up the stack (~90s cold)
make migrate     # apply the Alembic migration chain
```

`make up` runs `scripts/install.sh`, which auto-generates the required local
secrets as mounted files (never bare environment variables) and then runs
`docker compose up -d`. When it finishes, the UI is at
[http://localhost:3000](http://localhost:3000) and the API at
[http://localhost:8000](http://localhost:8000).

!!! tip "An OpenAI key is optional to boot"
    RelyLoop starts without an LLM key — `/healthz` simply reports
    `openai: missing_key` and the LLM-dependent features (judgment
    generation, digests, the chat agent) wait until you configure one. Only
    the Postgres password is boot-blocking.

## Configure an LLM endpoint

The entire LLM integration surface is one environment variable,
`OPENAI_BASE_URL`, pointing the `openai` SDK at any OpenAI-compatible
endpoint:

=== "OpenAI cloud"

    ```bash
    # .env
    OPENAI_BASE_URL=https://api.openai.com/v1
    # plus an API key mounted as a Docker secret (see the tutorial)
    ```

=== "Ollama (air-gapped)"

    ```bash
    # .env — nothing leaves the host
    OPENAI_BASE_URL=http://host.docker.internal:11434/v1
    OPENAI_MODEL=llama3.1
    ```

=== "vLLM / LM Studio / TGI"

    ```bash
    # .env — any OpenAI-compatible server
    OPENAI_BASE_URL=http://your-host:8000/v1
    ```

For Bedrock, Vertex, or Anthropic-native, put a LiteLLM proxy or OpenRouter in
front and point `OPENAI_BASE_URL` at it. Full matrix:
[`docs/08_guides/llm-endpoint-setup.md`](https://github.com/SoundMindsAI/relyloop/blob/main/docs/08_guides/llm-endpoint-setup.md).

## Next step

Head to the [Quickstart](quickstart.md) to seed sample data and open the chat
agent, then walk a full study end-to-end in [Your First Optimization
Loop](first-loop.md).
