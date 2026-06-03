#!/usr/bin/env node

// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// @ts-check

/**
 * Wraps `openapi-typescript` so the GENERATED-FILE banner survives every
 * regeneration. Without this wrapper, running `pnpm types:gen` (or the
 * underlying openapi-typescript binary) would strip the banner.
 *
 * Usage (from ui/): node scripts/gen-types.mjs
 * Or via the package script: pnpm types:gen
 *
 * Story 2.3 of `infra_generated_artifact_freshness_gate` (FR-5):
 *
 * 1. **Pinned binary, not `npx`.** Invokes the lockfile-pinned
 *    `node_modules/.bin/openapi-typescript[.cmd]` directly. Fails loudly
 *    if the binary is absent — no implicit `npx` download path that
 *    could pull a different version at runtime, and no network
 *    dependency to flake against. The dependency is pinned by
 *    `ui/pnpm-lock.yaml` (`openapi-typescript@7.x` in
 *    `ui/package.json`), so the version is reproducible.
 *
 * 2. **Source-invariant banner.** The banner is produced by
 *    `buildBanner()` in `gen-types-banner.mjs`, a pure module that
 *    takes no inputs. The banner names the COMMITTED snapshot path
 *    (`ui/openapi.json`), not the live `OPENAPI_URL` value, so a
 *    local-dev run + a CI-snapshot run produce byte-identical banners.
 *    Without this, the previous form `// Source: ${SOURCE_URL}` would
 *    cause the freshness gate to flap between environments.
 *
 * 3. **Entry-point guard.** Generation runs only when this module is
 *    invoked as the main script. Importing `gen-types.mjs` (e.g., from
 *    a vitest) does not shell out to `openapi-typescript` and does not
 *    mutate `ui/src/lib/types.ts`. The `buildBanner` test lives in
 *    `gen-types-banner.mjs`, which is genuinely side-effect-free; the
 *    guard here is belt-and-braces.
 */

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { buildBanner } from './gen-types-banner.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const UI_ROOT = resolve(__dirname, '..');
const OUTPUT = resolve(UI_ROOT, 'src/lib/types.ts');
// Default to the committed snapshot — CI uses this path, and a local
// regen against the snapshot produces byte-identical output. To
// regenerate from a running backend's live `/openapi.json` instead,
// export `OPENAPI_URL=http://localhost:8000/openapi.json`.
const DEFAULT_OPENAPI_PATH = resolve(UI_ROOT, 'openapi.json');
const SOURCE_URL = process.env.OPENAPI_URL ?? DEFAULT_OPENAPI_PATH;

/**
 * Path to the lockfile-pinned openapi-typescript binary. Windows
 * pnpm installs `.cmd` shims; POSIX uses bare names. Fail loudly if
 * the binary is missing — that signals `pnpm install --frozen-lockfile`
 * was skipped, which would otherwise let `npx` pull a different version
 * at runtime (the FR-5 bug this story fixes).
 *
 * @returns {string}
 */
function resolvePinnedBinary() {
  const binDir = resolve(UI_ROOT, 'node_modules', '.bin');
  const candidates =
    process.platform === 'win32'
      ? ['openapi-typescript.cmd', 'openapi-typescript']
      : ['openapi-typescript'];
  for (const candidate of candidates) {
    const p = join(binDir, candidate);
    if (existsSync(p)) {
      return p;
    }
  }
  throw new Error(
    `gen-types.mjs: pinned openapi-typescript binary not found under ${binDir}.\n` +
      `Run \`pnpm --dir ui install --frozen-lockfile\` first. We intentionally do NOT fall ` +
      `back to npx — npx can resolve/download a different version at runtime, defeating the ` +
      `lockfile pin (FR-5 of infra_generated_artifact_freshness_gate).`,
  );
}

/**
 * Run openapi-typescript via the pinned binary against SOURCE_URL,
 * then prepend the canonical banner if it isn't already there.
 */
function generate() {
  const bin = resolvePinnedBinary();
  // execFileSync (no shell on POSIX) — SOURCE_URL comes from
  // OPENAPI_URL env var, and a shell-interpolated command would let a
  // crafted value inject. Array argv is shell-free.
  //
  // On Windows the pinned binary is a `.cmd` shim, which Node's
  // execFileSync cannot invoke without `shell: true` (Windows requires
  // cmd.exe to interpret batch files; see
  // https://nodejs.org/api/child_process.html#spawning-bat-and-cmd-files).
  // We gate `shell: true` to win32 only so POSIX stays shell-free
  // (Gemini Code Assist review finding #3 on PR #433).
  console.log(`Generating ${OUTPUT} from ${SOURCE_URL}…`);
  execFileSync(bin, [SOURCE_URL, '-o', OUTPUT], {
    stdio: 'inherit',
    cwd: UI_ROOT,
    shell: process.platform === 'win32',
  });

  const generated = readFileSync(OUTPUT, 'utf8');
  if (generated.startsWith('// SPDX-FileCopyrightText')) {
    // Banner already present (shouldn't happen — openapi-typescript
    // strips inline headers on every regen — but be idempotent).
    console.log('Banner already present; skipping prepend.');
  } else {
    writeFileSync(OUTPUT, buildBanner() + generated, 'utf8');
    console.log('Banner prepended.');
  }
}

// Entry-point guard: run generation only when invoked as the main
// script. Importing the module (e.g., from a vitest) is a no-op.
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  generate();
}
