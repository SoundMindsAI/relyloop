#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Bash mirror of ENGINE_VERSION_MATRIX from
# backend/app/core/engine_versions.py. Sourced by
# scripts/lib/relyloop_engine_versions.sh to validate the
# RELYLOOP_ES_VERSION / RELYLOOP_OS_VERSION / RELYLOOP_SOLR_VERSION env vars
# before any `docker compose` invocation in scripts/install.sh.
#
# feat_engine_version_selection Story 1.3.
#
# THE PYTHON CONSTANT IS THE SOURCE OF TRUTH. When you update the matrix:
#   1. Edit backend/app/core/engine_versions.py first.
#   2. Mirror the change here, value-for-value.
#   3. If the [0] element changed for any engine, also bump the matching
#      ${X_IMAGE_TAG:-<default>} literal in docker-compose.yml.
#
# CI guard scripts/ci/verify_engine_version_matrix_parity.sh enforces
# sync between this file, the Python constant, and the Compose defaults
# on every PR.
#
# Bash 3.2 on macOS does NOT have associative arrays, hence three
# space-separated variables instead of one map. Whitespace between values
# is the canonical separator (matches the shell convention for word-split
# lists).

# Order within each variable matches the Python tuple order: index 0 is
# the latest patch of the latest supported major (also the Compose
# default), index 1 is the latest patch of the older supported major.

ES_VERSIONS="9.4.1 8.15.3"
OS_VERSIONS="3.6.0 2.18.0"
SOLR_VERSIONS="10.0 9.7"
