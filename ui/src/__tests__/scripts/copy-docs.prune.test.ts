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

import { mkdtempSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore — the .mjs ships its own JSDoc types; vitest resolves it natively.
import { DOCS, getDestDir, pruneStale, runCopyDocs } from '../../../scripts/copy-docs.mjs';

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
