/**
 * Playwright globalSetup: clear stale cleanup artifacts before each run.
 *
 * The cleanup machinery (chore_e2e_test_rows_isolation Story 1.2) writes
 * three artifacts:
 *   - `test-results/.cleanup/worker-*.jsonl` — per-worker registries
 *     populated by `appendForCleanup` in `helpers/seed.ts`.
 *   - `test-results/cleanup-summary.json` — written by `global-teardown.ts`.
 *   - `test-results/cleanup-verification-failures.txt` — written by the
 *     reporter when invariants fail.
 *
 * If a prior run was hard-interrupted (Ctrl-C, OS kill, process crash
 * before globalTeardown ran), any/all of these files can persist on disk.
 * Without this clear-at-start hook:
 *   - Stale `worker-*.jsonl` lines would be drained by the next teardown,
 *     producing 404s for already-deleted rows.
 *   - A stale `cleanup-summary.json` would be read by the reporter if the
 *     current teardown crashed before writing — producing a false
 *     `cleanup-reporter: OK` reading.
 *   - A stale `cleanup-verification-failures.txt` would mislead developers.
 *
 * Per-run lifecycle: globalSetup clears → workers append → globalTeardown
 * drains + writes summary + removes `.cleanup/` directory.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

export default function globalSetup(): void {
  const testResults = path.join(process.cwd(), 'test-results');
  const cleanupDir = path.join(testResults, '.cleanup');
  const summaryPath = path.join(testResults, 'cleanup-summary.json');
  const failuresPath = path.join(testResults, 'cleanup-verification-failures.txt');

  // `force: true` suppresses ENOENT — calls are idempotent against a clean slate.
  fs.rmSync(cleanupDir, { recursive: true, force: true });
  fs.rmSync(summaryPath, { force: true });
  fs.rmSync(failuresPath, { force: true });
}
