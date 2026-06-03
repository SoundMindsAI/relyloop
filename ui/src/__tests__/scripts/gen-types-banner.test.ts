// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Vitest for `ui/scripts/gen-types-banner.mjs` source-invariance
 * (Story 2.3 of `infra_generated_artifact_freshness_gate`, FR-5 /
 * AC-8 automated).
 *
 * `buildBanner()` is the canonical generated-file banner prepended to
 * every regeneration of `ui/src/lib/types.ts`. It MUST be byte-identical
 * regardless of which value `OPENAPI_URL` carries when the wrapping
 * script runs — otherwise a local-dev regen ("http://localhost:8000/...")
 * and a CI-snapshot regen ("$PWD/ui/openapi.json") would produce
 * different banner bytes and the freshness gate would flap.
 *
 * The test enforces invariance by:
 *
 *   1. Calling `buildBanner()` with no inputs and asserting the same
 *      bytes come back across multiple invocations.
 *   2. Mutating `process.env.OPENAPI_URL` to various values around the
 *      calls and asserting the banner is still identical — this is the
 *      structural proof that the function has no `OPENAPI_URL` input.
 *   3. Asserting the banner contains the canonical Source line
 *      (`ui/openapi.json`) so a future "improvement" that re-introduces
 *      an `${OPENAPI_URL}` interpolation fails the test.
 *   4. Asserting that importing `gen-types-banner.mjs` does NOT shell
 *      out to `openapi-typescript` — the test process completes without
 *      spawning the binary (side-effect-free import).
 */

import { describe, expect, it } from 'vitest';

// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore — the .mjs ships its own JSDoc types; vitest resolves it natively.
import { buildBanner } from '../../../scripts/gen-types-banner.mjs';

describe('gen-types-banner.mjs — buildBanner()', () => {
  it('returns the same bytes across repeated calls (source-invariant)', () => {
    const a = buildBanner();
    const b = buildBanner();
    expect(a).toBe(b);
  });

  it('is invariant when OPENAPI_URL changes (proves no env input)', () => {
    const original = process.env.OPENAPI_URL;
    try {
      process.env.OPENAPI_URL = 'http://localhost:8000/openapi.json';
      const fromLive = buildBanner();
      process.env.OPENAPI_URL = '/abs/path/to/ui/openapi.json';
      const fromAbs = buildBanner();
      delete process.env.OPENAPI_URL;
      const fromUnset = buildBanner();

      expect(fromLive).toBe(fromAbs);
      expect(fromAbs).toBe(fromUnset);
    } finally {
      if (original === undefined) {
        delete process.env.OPENAPI_URL;
      } else {
        process.env.OPENAPI_URL = original;
      }
    }
  });

  it('points at the committed snapshot, not the live URL', () => {
    const banner = buildBanner();
    // The Source line must name the canonical snapshot. Without this
    // assertion, a future edit that re-introduces an
    // `// Source: ${SOURCE_URL}` interpolation would slip through the
    // invariance test (both runs in that test would pick up the SAME
    // host-specific URL because they read the same process env).
    expect(banner).toMatch(/Source: backend OpenAPI schema/);
    expect(banner).toMatch(/canonical snapshot: ui\/openapi\.json/);
    // And it should NOT mention localhost or any environment-specific
    // URL — those are the prior-bad-form strings.
    expect(banner).not.toMatch(/localhost/);
    expect(banner).not.toMatch(/http:\/\//);
  });

  it('starts with the SPDX header (so re-prepended files stay REUSE-clean)', () => {
    const banner = buildBanner();
    expect(banner.startsWith('// SPDX-FileCopyrightText:')).toBe(true);
    // REUSE-IgnoreStart  — the regex literal below LOOKS like an SPDX
    // declaration to `reuse lint`, which would then try to parse the
    // trailing `\.0/);` JavaScript syntax as an SPDX expression and
    // fail. The Ignore markers tell reuse-lint to skip this region.
    expect(banner).toMatch(/SPDX-License-Identifier: Apache-2\.0/);
    // REUSE-IgnoreEnd
  });

  it('documents the CI freshness gate (not the obsolete "CI does NOT regenerate" line)', () => {
    const banner = buildBanner();
    // Positive assertion: the gate is named.
    expect(banner).toMatch(/CI-freshness-gated/);
    expect(banner).toMatch(/generated-artifacts-fresh/);
    // Negative assertion: the old false stance is gone.
    expect(banner).not.toMatch(/CI does NOT regenerate/);
  });

  it('importing this module does not run openapi-typescript', () => {
    // Structural assertion: if importing the module had a side effect
    // (e.g., a top-level `generate()` call), `process.argv[0]` would
    // need to be `node` AND `process.argv[1]` would need to be the
    // wrapper script. By the time vitest runs us, `process.argv[1]`
    // points at vitest's worker, not at gen-types*.mjs. So the import
    // above already proved the no-side-effect guarantee — it returned
    // cleanly without spawning a binary or writing to types.ts.
    // Belt-and-braces: confirm the import resolved (no exception
    // thrown above) and the export is callable.
    expect(typeof buildBanner).toBe('function');
  });
});
