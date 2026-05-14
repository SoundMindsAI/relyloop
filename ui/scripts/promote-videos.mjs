// @ts-check
/**
 * Promote walkthrough videos captured by `playwright test -c
 * playwright.demo.config.ts` into the canonical guide-assets directory,
 * so the in-app GuideViewer can serve them under /guides/<id>/walkthrough.webm.
 *
 * Wiring:
 *
 *   $ pnpm capture-guides
 *     ├── playwright test -c playwright.demo.config.ts   (writes screenshots
 *     │                                                   into ui/public/guides/
 *     │                                                   and videos into
 *     │                                                   test-results/demo-artifacts/)
 *     └── node scripts/promote-videos.mjs                (copies the videos
 *                                                         into ui/public/guides/
 *                                                         alongside the PNGs)
 *
 * Playwright names per-spec output directories like
 *   `<spec-base>--<hash>-<truncated-test-name>-chromium/video.webm`
 * For our 10 guide specs, `<spec-base>` is `NN_<slug>` which matches the
 * guide id under ui/public/guides/. Mapping is direct: strip the
 * `--<hash>-...-chromium` suffix.
 */
import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const uiRoot = resolve(__dirname, '..');
const srcRoot = join(uiRoot, 'test-results', 'demo-artifacts');
const destRoot = join(uiRoot, 'public', 'guides');

if (!existsSync(srcRoot)) {
  console.error(
    `[promote-videos] No test-results/demo-artifacts/ at ${srcRoot}. Run the demo capture first:\n` +
      `  pnpm playwright test -c playwright.demo.config.ts`,
  );
  process.exit(1);
}

// Build the set of known guide IDs from the destination directory — these
// are the canonical NN_slug names under ui/public/guides/. Match each
// Playwright output directory by prefix to extract the guide id reliably
// (Playwright uses either `--` or `-` as the spec/test separator depending
// on filename length, so naive `.split('--')` misses ~80% of guides).
const knownGuideIds = readdirSync(destRoot)
  .filter((d) => statSync(join(destRoot, d)).isDirectory())
  .filter((d) => /^\d+_/.test(d));

let promoted = 0;
const missing = [];

for (const entry of readdirSync(srcRoot)) {
  const entryPath = join(srcRoot, entry);
  if (!statSync(entryPath).isDirectory()) continue;
  const videoPath = join(entryPath, 'video.webm');
  if (!existsSync(videoPath)) continue;

  // Playwright sometimes truncates the spec basename mid-word (e.g.
  // `05_import_judgments_and_ca-...` for guide `05_import_judgments_and_calibrate`),
  // so we can't reliably match the full guide id by `startsWith`. Instead,
  // extract the `NN_` numeric prefix from the directory name and find the
  // known guide id with the same prefix — guide ids start with a unique
  // two-digit ordinal.
  const numPrefixMatch = entry.match(/^(\d+)_/);
  const guideId = numPrefixMatch
    ? knownGuideIds.find((id) => id.startsWith(`${numPrefixMatch[1]}_`))
    : undefined;

  if (!guideId) {
    missing.push(entry);
    continue;
  }

  const destPath = join(destRoot, guideId, 'walkthrough.webm');
  copyFileSync(videoPath, destPath);
  console.log(
    `[promote-videos] ${guideId}: ${videoPath} -> public/guides/${guideId}/walkthrough.webm`,
  );
  promoted += 1;
}

if (missing.length > 0) {
  console.warn(
    `[promote-videos] WARNING: ${missing.length} spec(s) had no matching guide directory: ${missing.join(', ')}`,
  );
}

if (promoted === 0) {
  console.error(
    '[promote-videos] No videos promoted. Either the demo capture has not run, or every video was for an audit-only spec.',
  );
  process.exit(2);
}

mkdirSync(destRoot, { recursive: true });
console.log(`[promote-videos] Promoted ${promoted} video(s).`);
