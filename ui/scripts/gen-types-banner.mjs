// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// @ts-check

/**
 * Pure, side-effect-free `buildBanner()` for `ui/src/lib/types.ts`.
 *
 * Story 2.3 of `infra_generated_artifact_freshness_gate` (FR-5).
 *
 * Why a separate module:
 *
 * 1. **Source-invariance** — the banner MUST be byte-identical regardless
 *    of which value `OPENAPI_URL` carries when the script runs. The
 *    previous embedded form `// Source: ${SOURCE_URL}` differed between
 *    a local-dev run (`http://localhost:8000/openapi.json`) and the
 *    CI-snapshot run (`$PWD/ui/openapi.json`), so the freshness gate
 *    would have flapped depending on developer environment. By making
 *    the banner a pure function of *no* inputs, the same bytes land
 *    every time.
 *
 * 2. **Testability** — `gen-types-banner.test.ts` imports this module
 *    directly and asserts the banner is byte-identical across multiple
 *    invocations. Importing `gen-types.mjs` itself would trigger
 *    generation (it shells out to `openapi-typescript`), which the
 *    entry-point guard in `gen-types.mjs` now prevents — but extracting
 *    the banner to its own pure module is the belt-and-braces version
 *    of that guarantee.
 */

/**
 * The canonical banner prepended to every regeneration of
 * `ui/src/lib/types.ts`. Carries the SPDX header (the reuse-lint
 * pre-commit hook rejects any tracked file without one;
 * `openapi-typescript` strips the inline SPDX on every regen, so this
 * wrapper re-prepends it). The "Source" line names the COMMITTED
 * snapshot path (`ui/openapi.json`), not the live `OPENAPI_URL` value,
 * so the banner is host-invariant.
 *
 * @returns {string}
 */
export function buildBanner() {
  return `// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// GENERATED FILE — do not edit. Regenerate via: cd ui && pnpm types:gen
// Source: backend OpenAPI schema (canonical snapshot: ui/openapi.json)
//
// This file is CI-freshness-gated by the \`generated-artifacts-fresh\`
// job in \`.github/workflows/pr.yml\`. CI regenerates it from the
// committed \`ui/openapi.json\` snapshot and fails the PR if the
// committed bytes drift. Run \`scripts/regen-generated-artifacts.sh\`
// locally to refresh \`ui/openapi.json\` + \`ui/src/lib/types.ts\`
// in lockstep.

`;
}
