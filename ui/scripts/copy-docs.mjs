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
 */
import { copyFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, '..', '..');
const srcDir = join(repoRoot, 'docs', '08_guides');
const destDir = join(__dirname, '..', 'public', 'docs');

const DOCS = [
  { src: 'tutorial-first-study.md', dest: 'tutorial-first-study.md' },
  { src: 'quick-tour.md', dest: 'quick-tour.md' },
  { src: 'workflows-overview.md', dest: 'workflows-overview.md' },
];

mkdirSync(destDir, { recursive: true });

for (const { src, dest } of DOCS) {
  const fromPath = join(srcDir, src);
  const toPath = join(destDir, dest);
  if (!existsSync(fromPath)) {
    console.warn(`[copy-docs] WARNING: source file missing: ${fromPath}`);
    continue;
  }
  copyFileSync(fromPath, toPath);
  console.log(`[copy-docs] ${src} -> public/docs/${dest}`);
}

// Drop a tiny README into the dest dir so contributors who find these files
// in `ui/public/docs/` know they're generated.
writeFileSync(
  join(destDir, 'README.md'),
  `# ui/public/docs/ — GENERATED

These markdown files are copied from \`docs/08_guides/\` at build time by
\`ui/scripts/copy-docs.mjs\` (wired into the package.json \`prebuild\` hook).

DO NOT edit them here — your changes will be overwritten. Edit the source
files in \`docs/08_guides/\` instead.
`,
);
console.log(`[copy-docs] done`);
