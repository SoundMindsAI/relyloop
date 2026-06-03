// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// @ts-check
/**
 * Copy curated long-form guides from `docs/08_guides/` into `ui/public/docs/`
 * at build time. This lets Next.js serve the markdown as a static asset
 * (`/docs/<slug>.md`) which the in-app `<MarkdownDoc>` component fetches and
 * renders with `react-markdown` under the /guide menu.
 *
 * Run automatically via the package.json `prebuild` hook; also runnable
 * directly for local development:
 *
 *   cd ui && node scripts/copy-docs.mjs
 *
 * Single-direction sync — the source of truth is `docs/08_guides/`. Editors
 * should NOT modify `ui/public/docs/` directly; their changes will be
 * overwritten on the next build.
 *
 * The script also PRUNES the destination dir to exactly
 * `{README.md} ∪ {DOCS[].dest}` so that a removed or renamed `DOCS` entry
 * does not leave a stale public copy behind (FR-9 of
 * `infra_generated_artifact_freshness_gate`). Anything outside the expected
 * set with a `.md` suffix is deleted.
 *
 * Module shape: the file exposes `DOCS`, `pruneStale`, `getDestDir`, and
 * `runCopyDocs` as named exports so the vitest at
 * `ui/src/__tests__/scripts/copy-docs.prune.test.ts` can exercise the prune
 * logic hermetically against a tmp directory. Importing the module does NOT
 * trigger generation — the bottom-of-file ESM entrypoint check
 * (`import.meta.url === pathToFileURL(process.argv[1]).href`) gates the
 * actual run, mirroring the `ui/scripts/gen-types.mjs` pattern.
 */
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..', '..');
const srcDir = join(repoRoot, 'docs', '08_guides');

/**
 * The canonical destination directory (`ui/public/docs/`). Exported as a
 * function so callers always get the absolute path regardless of `cwd` —
 * see the `import.meta.url` resolution above. The vitest uses this to
 * assert cwd-equivalence (FR-1 cwd-robustness).
 * @returns {string}
 */
export function getDestDir() {
  return join(__dirname, '..', 'public', 'docs');
}

/**
 * @typedef {Object} DocEntry
 * @property {string} src   - basename under `docs/08_guides/`
 * @property {string} dest  - basename under `ui/public/docs/`
 */

/** @type {readonly DocEntry[]} */
export const DOCS = Object.freeze([
  { src: 'tutorial-first-study.md', dest: 'tutorial-first-study.md' },
  { src: 'quick-tour.md', dest: 'quick-tour.md' },
  { src: 'workflows-overview.md', dest: 'workflows-overview.md' },
]);

const README_CONTENT = `# ui/public/docs/ — GENERATED

These markdown files are copied from \`docs/08_guides/\` at build time by
\`ui/scripts/copy-docs.mjs\` (wired into the package.json \`prebuild\` hook).

DO NOT edit them here — your changes will be overwritten. Edit the source
files in \`docs/08_guides/\` instead.
`;

/**
 * Delete any `*.md` file in `destDir` whose basename is not in
 * `expectedNames`. README.md is preserved because callers include it in
 * the expected set. Returns the basenames that were pruned (for logging
 * and test assertions). Non-`.md` files are left alone.
 *
 * @param {string} destDir
 * @param {Set<string>} expectedNames
 * @returns {string[]}
 */
export function pruneStale(destDir, expectedNames) {
  const pruned = [];
  for (const f of readdirSync(destDir)) {
    if (f.endsWith('.md') && !expectedNames.has(f)) {
      unlinkSync(join(destDir, f));
      pruned.push(f);
    }
  }
  return pruned;
}

/**
 * Full sync: ensure dest dir exists, copy every entry in DOCS, write the
 * README, then prune any obsolete `*.md`. Idempotent — a second call on
 * an up-to-date tree is a no-op as far as `git status` is concerned.
 *
 * @param {Object} [opts]
 * @param {string} [opts.destDir]    - override (defaults to `getDestDir()`)
 * @param {string} [opts.sourceDir]  - override (defaults to `docs/08_guides/`)
 * @param {readonly DocEntry[]} [opts.docs] - override (defaults to `DOCS`)
 * @returns {{copied: string[], pruned: string[]}}
 */
export function runCopyDocs(opts = {}) {
  const destDirResolved = opts.destDir ?? getDestDir();
  const sourceDirResolved = opts.sourceDir ?? srcDir;
  const docs = opts.docs ?? DOCS;
  const copied = [];

  mkdirSync(destDirResolved, { recursive: true });

  for (const { src, dest } of docs) {
    const fromPath = join(sourceDirResolved, src);
    const toPath = join(destDirResolved, dest);
    if (!existsSync(fromPath)) {
      console.warn(`[copy-docs] WARNING: source file missing: ${fromPath}`);
      continue;
    }
    copyFileSync(fromPath, toPath);
    copied.push(dest);
    console.log(`[copy-docs] ${src} -> public/docs/${dest}`);
  }

  writeFileSync(join(destDirResolved, 'README.md'), README_CONTENT);

  const expected = new Set(['README.md', ...docs.map((d) => d.dest)]);
  const pruned = pruneStale(destDirResolved, expected);
  for (const f of pruned) {
    console.log(`[copy-docs] pruned obsolete public/docs/${f}`);
  }
  console.log(`[copy-docs] done`);
  return { copied, pruned };
}

// Entry-point guard: run only when invoked as the main script (not when
// imported by tests). Mirrors the `ui/scripts/gen-types.mjs` pattern.
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  runCopyDocs();
}
