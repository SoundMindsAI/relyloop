#!/bin/sh

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Entrypoint for the bundled `ollama` Compose service (feat_bundled_local_llm
# Story 2). Starts `ollama serve` in the background, waits for the daemon to
# accept connections, pulls the requested model, then foregrounds the daemon.
#
# The model pull happens here (not in a separate init service) so a single
# profile-gated service owns serve + pull, and the Compose healthcheck
# (`ollama show "$OLLAMA_MODEL"`) only passes once the pull has completed —
# which is what makes `docker compose up -d --wait` block until the LLM is
# actually usable. Cached in the ./data/ollama volume, so subsequent starts
# skip the download and become healthy quickly.

set -eu

MODEL="${OLLAMA_MODEL:-qwen3.5:4b}"

# Start the server in the background.
ollama serve &
SERVE_PID="$!"

# Wait for the daemon to accept connections (up to ~60s) before pulling.
i=0
while [ "$i" -lt 60 ]; do
  if ollama list >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 1
done

# Pull the model if it isn't already present in the volume. `ollama pull` is a
# no-op refresh when the model is already cached, so this is safe on restart.
echo "ollama-entrypoint: ensuring model '${MODEL}' is present…"
ollama pull "${MODEL}"
echo "ollama-entrypoint: model '${MODEL}' ready; serving."

# Foreground the daemon for the rest of the container's life.
wait "${SERVE_PID}"
