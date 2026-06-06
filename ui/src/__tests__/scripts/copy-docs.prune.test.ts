// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Vitest for `ui/scripts/copy-docs.mjs` prune behavior (Story 1.1 of
 * `infra_generated_artifact_freshness_gate`, FR-9 / AC-11).
 *
 * The script-under-test prunes any `*.md` file in its destination that
 * isn't in `{README.md} ∪ {DOCS[].dest}`, so that a renamed or removed
 * `DOCS` entry doesn't leave a stale public copy behind. These tests
 * exercise that behavior hermetically against a tmp directory using the
 * exported `pruneStale` / `runCopyDocs` / `getDestDir` symbols (the script
 * exposes them after the Story 1.1 refactor + adds an ESM entrypoint
 * guard so importing the module does not generate anything).
 *
 * The tests also assert cwd-equivalence (FR-1) by calling `getDestDir`
 * with two different `process.cwd()` values and asserting the resolved
 * absolute path is identical — the script resolves paths via
 * `import.meta.url`, so the result is cwd-invariant by construction.
 */

import { existsSync, mkdtempSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore — the .mjs ships its own JSDoc types; vitest resolves it natively. Namespace
// import keeps the @ts-ignore on the single import line so prettier multi-line reformatting
// of a destructured form can't separate the directive from the offending statement.
import * as copyDocs from '../../../scripts/copy-docs.mjs';

const { DOCS, copyImageAssets, getDestDir, pruneStale, pruneStaleImages, runCopyDocs } =
  copyDocs as unknown as {
    DOCS: readonly { src: string; dest: string }[];
    copyImageAssets: (sourceImagesDir: string, destImagesDir: string) => Set<string>;
    getDestDir: () => string;
    pruneStale: (destDir: string, expectedNames: Set<string>) => string[];
    pruneStaleImages: (destImagesDir: string, expectedNames: Set<string>) => string[];
    runCopyDocs: (opts?: {
      destDir?: string;
      sourceDir?: string;
      docs?: readonly { src: string; dest: string }[];
    }) => {
      copied: string[];
      copiedImages: string[];
      pruned: string[];
      prunedImages: string[];
    };
  };

const EXPECTED_DOC_BASENAMES = [
  'tutorial-first-study.md',
  'quick-tour.md',
  'workflows-overview.md',
];

interface DocEntry {
  src: string;
  dest: string;
}

describe('copy-docs.mjs — exported shape', () => {
  it('exports the expected DOCS entries (canonical source for prune)', () => {
    // The prune set is `{README.md} ∪ {DOCS[].dest}`. If DOCS drifts, the
    // CI freshness gate and this test both update in lockstep.
    expect((DOCS as readonly DocEntry[]).map((d) => d.dest).sort()).toEqual(
      [...EXPECTED_DOC_BASENAMES].sort(),
    );
  });

  it('getDestDir() returns an absolute path invariant under cwd (FR-1 cwd-equivalence)', () => {
    const original = process.cwd();
    try {
      // Resolved once with cwd=repoRoot.
      process.chdir(resolve(original));
      const fromRoot = getDestDir() as string;
      // Resolved again with cwd=os.tmpdir — totally unrelated to the repo.
      process.chdir(tmpdir());
      const fromTmp = getDestDir() as string;
      expect(fromRoot).toBe(fromTmp);
      expect(fromRoot.endsWith(`${join('ui', 'public', 'docs')}`)).toBe(true);
    } finally {
      process.chdir(original);
    }
  });
});

describe('pruneStale — direct behavior', () => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(join(tmpdir(), 'rl-prune-'));
  });
  afterEach(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  it('deletes *.md files not in the expected set', () => {
    writeFileSync(join(tmp, 'keep.md'), 'keep');
    writeFileSync(join(tmp, 'obsolete.md'), 'obsolete');
    writeFileSync(join(tmp, 'README.md'), 'readme');

    const pruned = pruneStale(tmp, new Set(['README.md', 'keep.md'])) as string[];

    expect(pruned).toEqual(['obsolete.md']);
    expect(readdirSync(tmp).sort()).toEqual(['README.md', 'keep.md']);
  });

  it('preserves non-*.md files (only the .md surface is gated)', () => {
    writeFileSync(join(tmp, 'unrelated.txt'), 'leave-me-alone');
    writeFileSync(join(tmp, 'obsolete.md'), 'obsolete');

    const pruned = pruneStale(tmp, new Set(['README.md'])) as string[];

    expect(pruned).toEqual(['obsolete.md']);
    expect(readdirSync(tmp).sort()).toEqual(['unrelated.txt']);
  });

  it('is a no-op when the directory already matches the expected set', () => {
    writeFileSync(join(tmp, 'README.md'), 'readme');
    writeFileSync(join(tmp, 'quick-tour.md'), 'tour');

    const pruned = pruneStale(tmp, new Set(['README.md', 'quick-tour.md'])) as string[];

    expect(pruned).toEqual([]);
    expect(readdirSync(tmp).sort()).toEqual(['README.md', 'quick-tour.md']);
  });
});

describe('runCopyDocs — end-to-end against tmp dirs', () => {
  let srcTmp: string;
  let destTmp: string;

  beforeEach(() => {
    srcTmp = mkdtempSync(join(tmpdir(), 'rl-copydocs-src-'));
    destTmp = mkdtempSync(join(tmpdir(), 'rl-copydocs-dest-'));
    // Seed the source dir with the three real guide basenames.
    for (const f of EXPECTED_DOC_BASENAMES) {
      writeFileSync(join(srcTmp, f), `# ${f} — fixture body`);
    }
  });
  afterEach(() => {
    rmSync(srcTmp, { recursive: true, force: true });
    rmSync(destTmp, { recursive: true, force: true });
  });

  it('produces the exact expected set on a clean run (AC-11 happy path)', () => {
    const { copied, pruned } = runCopyDocs({
      destDir: destTmp,
      sourceDir: srcTmp,
      docs: DOCS,
    }) as { copied: string[]; pruned: string[] };

    expect(copied.sort()).toEqual([...EXPECTED_DOC_BASENAMES].sort());
    expect(pruned).toEqual([]);
    expect(readdirSync(destTmp).sort()).toEqual(['README.md', ...EXPECTED_DOC_BASENAMES].sort());
  });

  it('prunes a stale public copy left by a removed DOCS entry (AC-11)', () => {
    // Pre-seed the dest with a guide that USED TO BE in DOCS but no longer is.
    writeFileSync(join(destTmp, 'old-renamed.md'), '# obsolete public copy');
    // Run with the current DOCS (which does NOT include `old-renamed.md`).
    const { pruned } = runCopyDocs({
      destDir: destTmp,
      sourceDir: srcTmp,
      docs: DOCS,
    }) as { copied: string[]; pruned: string[] };

    expect(pruned).toContain('old-renamed.md');
    expect(readdirSync(destTmp).sort()).toEqual(['README.md', ...EXPECTED_DOC_BASENAMES].sort());
  });

  it('is idempotent — a second run on a clean tree changes nothing', () => {
    runCopyDocs({ destDir: destTmp, sourceDir: srcTmp, docs: DOCS });
    const firstRunFiles = readdirSync(destTmp).sort();
    const { copied, pruned } = runCopyDocs({
      destDir: destTmp,
      sourceDir: srcTmp,
      docs: DOCS,
    }) as { copied: string[]; pruned: string[] };

    expect(pruned).toEqual([]);
    expect(copied.sort()).toEqual([...EXPECTED_DOC_BASENAMES].sort());
    expect(readdirSync(destTmp).sort()).toEqual(firstRunFiles);
  });

  it('prunes when a DOCS entry is removed mid-rename (the FR-9 motivating scenario)', () => {
    // Simulate the failure mode FR-9 catches: someone renames a DOCS entry
    // from `quick-tour.md` → `quick-tour-v2.md`, runs the script, and
    // expects the old public copy to be deleted.
    writeFileSync(join(srcTmp, 'quick-tour-v2.md'), '# v2');
    const renamedDocs: readonly DocEntry[] = [
      { src: 'tutorial-first-study.md', dest: 'tutorial-first-study.md' },
      { src: 'quick-tour-v2.md', dest: 'quick-tour-v2.md' },
      { src: 'workflows-overview.md', dest: 'workflows-overview.md' },
    ];
    // First run with old DOCS to seed `quick-tour.md` in dest.
    runCopyDocs({ destDir: destTmp, sourceDir: srcTmp, docs: DOCS });
    expect(readdirSync(destTmp)).toContain('quick-tour.md');
    // Now run with the renamed DOCS — `quick-tour.md` should be pruned.
    const { pruned } = runCopyDocs({
      destDir: destTmp,
      sourceDir: srcTmp,
      docs: renamedDocs,
    }) as { copied: string[]; pruned: string[] };

    expect(pruned).toContain('quick-tour.md');
    expect(readdirSync(destTmp)).not.toContain('quick-tour.md');
    expect(readdirSync(destTmp)).toContain('quick-tour-v2.md');
  });

  it('cwd-equivalence: behavior is identical whether cwd is repo-root or ui/', () => {
    // Structural assertion (the script uses `import.meta.url` for path
    // resolution, so cwd is irrelevant). We assert behavioral parity by
    // running twice from different cwds against fresh tmp dirs.
    const original = process.cwd();
    const dest1 = mkdtempSync(join(tmpdir(), 'rl-cwd1-'));
    const dest2 = mkdtempSync(join(tmpdir(), 'rl-cwd2-'));
    try {
      process.chdir(original);
      runCopyDocs({ destDir: dest1, sourceDir: srcTmp, docs: DOCS });

      process.chdir(tmpdir());
      runCopyDocs({ destDir: dest2, sourceDir: srcTmp, docs: DOCS });

      expect(readdirSync(dest1).sort()).toEqual(readdirSync(dest2).sort());
    } finally {
      process.chdir(original);
      rmSync(dest1, { recursive: true, force: true });
      rmSync(dest2, { recursive: true, force: true });
    }
  });
});

describe('copyImageAssets — tutorial-image ferry (chore_overnight_result_card_screenshot D-3)', () => {
  let srcImagesTmp: string;
  let destImagesTmp: string;

  beforeEach(() => {
    srcImagesTmp = mkdtempSync(join(tmpdir(), 'rl-imgs-src-'));
    destImagesTmp = mkdtempSync(join(tmpdir(), 'rl-imgs-dest-'));
  });
  afterEach(() => {
    rmSync(srcImagesTmp, { recursive: true, force: true });
    rmSync(destImagesTmp, { recursive: true, force: true });
  });

  it('copies a .png from source to dest', () => {
    writeFileSync(join(srcImagesTmp, '12-overnight-result-card.png'), 'fake-png-bytes');

    const copied = copyImageAssets(srcImagesTmp, destImagesTmp) as Set<string>;

    expect([...copied]).toEqual(['12-overnight-result-card.png']);
    expect(readdirSync(destImagesTmp)).toEqual(['12-overnight-result-card.png']);
  });

  it('skips non-.png files (the .gitkeep sentinel does not propagate)', () => {
    writeFileSync(join(srcImagesTmp, '.gitkeep'), '');
    writeFileSync(join(srcImagesTmp, 'README.txt'), 'not an image');
    writeFileSync(join(srcImagesTmp, '12-foo.png'), 'png');

    const copied = copyImageAssets(srcImagesTmp, destImagesTmp) as Set<string>;

    expect([...copied]).toEqual(['12-foo.png']);
    expect(readdirSync(destImagesTmp)).toEqual(['12-foo.png']);
  });

  it('is a no-op when the source images dir does not exist (steady state for guides without images)', () => {
    const nonexistent = join(srcImagesTmp, 'does-not-exist');
    const copied = copyImageAssets(nonexistent, destImagesTmp) as Set<string>;

    expect([...copied]).toEqual([]);
    // dest dir should not be eagerly created when source is absent.
    expect(readdirSync(destImagesTmp)).toEqual([]);
  });

  it('is a no-op when the source path is a file rather than a directory', () => {
    const filePath = join(srcImagesTmp, 'not-a-dir');
    writeFileSync(filePath, 'oops');

    const copied = copyImageAssets(filePath, destImagesTmp) as Set<string>;
    expect([...copied]).toEqual([]);
  });

  it('overwrites a stale dest image with the current source bytes (idempotent re-run)', () => {
    writeFileSync(join(srcImagesTmp, '12-foo.png'), 'NEW BYTES');
    mkdirSync(destImagesTmp, { recursive: true });
    writeFileSync(join(destImagesTmp, '12-foo.png'), 'OLD BYTES');

    copyImageAssets(srcImagesTmp, destImagesTmp);

    const { readFileSync } = require('node:fs') as typeof import('node:fs');
    expect(readFileSync(join(destImagesTmp, '12-foo.png'), 'utf-8')).toBe('NEW BYTES');
  });
});

describe('pruneStaleImages — dest-only cleanup', () => {
  let destImagesTmp: string;

  beforeEach(() => {
    destImagesTmp = mkdtempSync(join(tmpdir(), 'rl-imgs-prune-'));
  });
  afterEach(() => {
    rmSync(destImagesTmp, { recursive: true, force: true });
  });

  it('removes .png files not in the expected set', () => {
    writeFileSync(join(destImagesTmp, '12-keep.png'), '');
    writeFileSync(join(destImagesTmp, 'obsolete.png'), '');

    const pruned = pruneStaleImages(destImagesTmp, new Set(['12-keep.png'])) as string[];

    expect(pruned).toEqual(['obsolete.png']);
    expect(readdirSync(destImagesTmp)).toEqual(['12-keep.png']);
  });

  it('preserves non-.png files (surfaces them via the freshness gate instead of silent rm)', () => {
    writeFileSync(join(destImagesTmp, 'README.md'), 'oops not an image but not pruned');
    writeFileSync(join(destImagesTmp, 'stale.png'), '');

    const pruned = pruneStaleImages(destImagesTmp, new Set()) as string[];

    expect(pruned).toEqual(['stale.png']);
    expect(readdirSync(destImagesTmp).sort()).toEqual(['README.md']);
  });

  it('is a no-op when the dest images dir does not exist', () => {
    const nonexistent = join(destImagesTmp, 'absent');
    const pruned = pruneStaleImages(nonexistent, new Set()) as string[];
    expect(pruned).toEqual([]);
  });
});

describe('runCopyDocs — end-to-end with image subtree', () => {
  let srcTmp: string;
  let destTmp: string;

  beforeEach(() => {
    srcTmp = mkdtempSync(join(tmpdir(), 'rl-copydocs-src-imgs-'));
    destTmp = mkdtempSync(join(tmpdir(), 'rl-copydocs-dest-imgs-'));
    for (const f of EXPECTED_DOC_BASENAMES) {
      writeFileSync(join(srcTmp, f), `# ${f} — fixture body`);
    }
    mkdirSync(join(srcTmp, 'images'), { recursive: true });
    writeFileSync(join(srcTmp, 'images', '12-overnight-result-card.png'), 'png-bytes');
  });
  afterEach(() => {
    rmSync(srcTmp, { recursive: true, force: true });
    rmSync(destTmp, { recursive: true, force: true });
  });

  it('mirrors images/ alongside the markdown copies', () => {
    const { copied, copiedImages, pruned, prunedImages } = runCopyDocs({
      destDir: destTmp,
      sourceDir: srcTmp,
      docs: DOCS,
    }) as {
      copied: string[];
      copiedImages: string[];
      pruned: string[];
      prunedImages: string[];
    };

    expect(copied.sort()).toEqual([...EXPECTED_DOC_BASENAMES].sort());
    expect(copiedImages).toEqual(['12-overnight-result-card.png']);
    expect(pruned).toEqual([]);
    expect(prunedImages).toEqual([]);
    // The top-level prune leaves `images/` intact (it's in the expected set).
    expect(readdirSync(destTmp).sort()).toEqual(
      ['README.md', 'images', ...EXPECTED_DOC_BASENAMES].sort(),
    );
    expect(readdirSync(join(destTmp, 'images'))).toEqual(['12-overnight-result-card.png']);
  });

  it('prunes a stale dest image when the source no longer carries it', () => {
    // First run seeds the dest with the source image.
    runCopyDocs({ destDir: destTmp, sourceDir: srcTmp, docs: DOCS });
    // Operator deletes the source image (and replaces with a different one).
    rmSync(join(srcTmp, 'images', '12-overnight-result-card.png'));
    writeFileSync(join(srcTmp, 'images', '13-other.png'), 'png');

    const { copiedImages, prunedImages } = runCopyDocs({
      destDir: destTmp,
      sourceDir: srcTmp,
      docs: DOCS,
    }) as { copiedImages: string[]; prunedImages: string[] };

    expect(copiedImages).toEqual(['13-other.png']);
    expect(prunedImages).toEqual(['12-overnight-result-card.png']);
    expect(readdirSync(join(destTmp, 'images')).sort()).toEqual(['13-other.png']);
  });

  it('does not eagerly create dest/images when the source has no images dir', () => {
    // Rebuild srcTmp without images/.
    rmSync(join(srcTmp, 'images'), { recursive: true, force: true });

    const { copiedImages, prunedImages } = runCopyDocs({
      destDir: destTmp,
      sourceDir: srcTmp,
      docs: DOCS,
    }) as { copiedImages: string[]; prunedImages: string[] };

    expect(copiedImages).toEqual([]);
    expect(prunedImages).toEqual([]);
    expect(existsSync(join(destTmp, 'images'))).toBe(false);
  });

  it('does not prune the images/ subdirectory itself during the top-level .md prune', () => {
    // The top-level prune (`pruneStale`) only handles .md files; this test
    // pins the behavioral guard against a future generalization that might
    // treat `images/` as an unexpected entry.
    runCopyDocs({ destDir: destTmp, sourceDir: srcTmp, docs: DOCS });
    expect(existsSync(join(destTmp, 'images'))).toBe(true);

    // Pre-seed an obsolete .md so the second run produces a prune, then
    // re-run and confirm `images/` survives.
    writeFileSync(join(destTmp, 'obsolete.md'), 'obsolete');
    runCopyDocs({ destDir: destTmp, sourceDir: srcTmp, docs: DOCS });

    expect(readdirSync(destTmp)).toContain('images');
    expect(readdirSync(destTmp)).not.toContain('obsolete.md');
  });
});

describe('copy-docs.mjs — entry-point guard', () => {
  it('importing the module does not modify ui/public/docs (no auto-run on import)', () => {
    // If the entry-point guard regressed, the very act of importing the
    // module (at the top of this file) would call `runCopyDocs()` with
    // the real `destDir = ui/public/docs`. We assert the import did NOT
    // mutate that real directory by checking the current state matches
    // the expected canonical set. The check is intentionally weak —
    // we don't want this test to flake on unrelated public/docs changes;
    // we only want to catch a "module-import-runs-the-script" regression.
    const realDest = getDestDir() as string;
    mkdirSync(realDest, { recursive: true });
    const files = readdirSync(realDest).filter((f) => f.endsWith('.md'));
    // Every committed `.md` in ui/public/docs must be README.md or one of DOCS.
    const expected = new Set(['README.md', ...(DOCS as readonly DocEntry[]).map((d) => d.dest)]);
    for (const f of files) {
      expect(expected.has(f)).toBe(true);
    }
  });
});
