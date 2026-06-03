#!/usr/bin/env node

// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Wraps `openapi-typescript` so the GENERATED-FILE banner survives every
 * regeneration. Without this wrapper, running `pnpm types:gen` (or the
 * underlying openapi-typescript binary) would strip the banner.
 *
 * Usage (from ui/): node scripts/gen-types.mjs
 * Or via the package script: pnpm types:gen
 */

import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const UI_ROOT = resolve(__dirname, '..');
const OUTPUT = resolve(UI_ROOT, 'src/lib/types.ts');
const SOURCE_URL = process.env.OPENAPI_URL ?? 'http://localhost:8000/openapi.json';

// SPDX header first so the file stays REUSE-compliant (the reuse-lint
// pre-commit hook rejects any tracked file without it); openapi-typescript
// strips it on every regen, so the wrapper re-prepends it here.
const BANNER = `// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// GENERATED FILE — do not edit. Regenerate via: cd ui && pnpm types:gen
// Source: ${SOURCE_URL}
//
// Prerequisite: the backend must be running (make up) so /openapi.json is reachable.
// CI does NOT regenerate this file — the committed version is the source of truth
// for the PR. If you need a fresh schema, run \`cd ui && pnpm types:gen\` locally.

`;

console.log(`Generating ${OUTPUT} from ${SOURCE_URL}…`);
// execFileSync (no shell) instead of execSync with an interpolated string:
// SOURCE_URL comes from the OPENAPI_URL env var, and an interpolated shell
// command would let a crafted value inject. Passing args as an array runs the
// binary directly with no shell, so there is nothing to inject into. On Windows
// the launcher is `npx.cmd` (no shell to resolve the `.cmd` extension), so pick
// the platform-correct executable name.
const NPX = process.platform === 'win32' ? 'npx.cmd' : 'npx';
execFileSync(NPX, ['openapi-typescript', SOURCE_URL, '-o', OUTPUT], {
  stdio: 'inherit',
  cwd: UI_ROOT,
});

const generated = readFileSync(OUTPUT, 'utf8');
if (generated.startsWith('// SPDX-FileCopyrightText')) {
  // Banner already present (shouldn't happen, but be idempotent).
  console.log('Banner already present; skipping prepend.');
} else {
  writeFileSync(OUTPUT, BANNER + generated, 'utf8');
  console.log('Banner prepended.');
}
