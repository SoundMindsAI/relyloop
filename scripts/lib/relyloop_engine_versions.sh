#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Sourceable helper for RELYLOOP_{ES,OS,SOLR}_VERSION → *_IMAGE_TAG
# translation. Pins each engine to a maintainer-curated supported version
# at install time (or leaves it at the Compose `${X_IMAGE_TAG:-<default>}`
# default when the env var is unset / empty).
#
# feat_engine_version_selection Story 1.3.
#
# Defines `parse_relyloop_engine_versions` — sources the bash mirror of
# the matrix at scripts/lib/relyloop_engine_versions_matrix.sh, validates
# each set RELYLOOP_*_VERSION input against the corresponding allowed-
# values list, and exports the validated value as the matching *_IMAGE_TAG.
# Unknown values exit 1 with a clear stderr message BEFORE any
# `docker compose pull` so the operator never starts an unauthorized
# registry call.
#
# Multiple version errors short-circuit at the first failure — the
# `|| return 1` chain stops the helper as soon as one engine's value is
# rejected. This matches the discipline of `parse_relyloop_engines` and
# is documented in the bash test at
# scripts/ci/test_parse_relyloop_engine_versions.sh case
# `mixed_one_unknown`.
#
# Sourced from scripts/install.sh AFTER `parse_relyloop_engines` (so
# engine selection is resolved first, then version selection); also
# sourced from scripts/ci/test_parse_relyloop_engine_versions.sh so the
# function is testable in isolation.

# `set -e` / `set -u` are inherited from the caller (install.sh runs
# `set -euo pipefail`). This file is sourced, never executed directly.

parse_relyloop_engine_versions() {
  # Locate the repo root from the caller's perspective. install.sh sets
  # REPO_ROOT before sourcing this helper; the bash test sets it too.
  # Fall back to a derivation from this file's path in case neither set
  # it (defensive — both known callers set it explicitly).
  local repo_root="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

  # shellcheck source=relyloop_engine_versions_matrix.sh
  source "${repo_root}/scripts/lib/relyloop_engine_versions_matrix.sh"

  _validate_one_engine_version() {
    # Args:
    #   $1 — env var name to read (e.g. "RELYLOOP_ES_VERSION")
    #   $2 — engine label for the error message (e.g. "elasticsearch")
    #   $3 — space-separated allowed values (e.g. "$ES_VERSIONS")
    #   $4 — env var name to export (e.g. "ES_IMAGE_TAG")
    local var_name="$1"
    local engine_label="$2"
    local allowed_list="$3"
    local export_var="$4"

    # Indirect read of the input var — bash 3.2-safe via `${!var_name}`.
    local input="${!var_name:-}"
    # Empty / unset → no export, Compose `${X_IMAGE_TAG:-<default>}` applies.
    [[ -z "$input" ]] && return 0

    local v
    for v in $allowed_list; do
      if [[ "$input" == "$v" ]]; then
        export "$export_var"="$input"
        echo "RelyLoop: pinning $engine_label to $input"
        return 0
      fi
    done

    # Build a comma-separated allowed list for the error message
    # (space-separated in the bash mirror, comma-separated for human
    # readability).
    local pretty_list="${allowed_list// /, }"
    echo "Unknown $engine_label version '$input'. Allowed: ${pretty_list}." >&2
    return 1
  }

  _validate_one_engine_version RELYLOOP_ES_VERSION   elasticsearch "$ES_VERSIONS"   ES_IMAGE_TAG   || return 1
  _validate_one_engine_version RELYLOOP_OS_VERSION   opensearch    "$OS_VERSIONS"   OS_IMAGE_TAG   || return 1
  _validate_one_engine_version RELYLOOP_SOLR_VERSION solr          "$SOLR_VERSIONS" SOLR_IMAGE_TAG || return 1
}
