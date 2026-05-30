// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Playwright Reporter: verify the cleanup-summary.json invariants in onEnd.
 *
 * Runs AFTER globalTeardown writes the summary artifact. Reads it,
 * checks the invariants from spec FR-7:
 *   - registered_deduped === attempted
 *   - attempted === deleted + failed + skipped_404
 *   - failed === 0 (parse_failures count toward `failed`)
 *
 * On failure, logs to stdout AND writes
 * `test-results/cleanup-verification-failures.txt` for CI/local
 * diagnostics. Does NOT alter the Playwright exit code in v1 — cleanup
 * is best-effort per the developer-ergonomics gate. Strict-mode env
 * var (`PLAYWRIGHT_CLEANUP_STRICT=1`) is deferred to a follow-up per
 * spec §19.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { FullResult, Reporter } from '@playwright/test/reporter';

interface CleanupSummary {
  registered: number;
  registered_deduped: number;
  attempted: number;
  deleted: number;
  failed: number;
  skipped_404: number;
  parse_failures: number;
  details: Array<unknown>;
}

class CleanupReporter implements Reporter {
  onEnd(_result: FullResult): void {
    const summaryPath = path.join(process.cwd(), 'test-results', 'cleanup-summary.json');
    if (!fs.existsSync(summaryPath)) {
      console.warn(
        'cleanup-reporter: cleanup-summary.json missing — globalTeardown did not run or write the artifact',
      );
      return;
    }
    let summary: CleanupSummary;
    try {
      summary = JSON.parse(fs.readFileSync(summaryPath, 'utf8')) as CleanupSummary;
    } catch (e) {
      console.error(
        `cleanup-reporter: failed to parse cleanup-summary.json — ${(e as Error).message}`,
      );
      return;
    }

    const invariantOk =
      summary.registered_deduped === summary.attempted &&
      summary.attempted === summary.deleted + summary.failed + summary.skipped_404 &&
      summary.failed === 0;

    if (invariantOk) {
      console.log(
        `cleanup-reporter: OK — ${summary.deleted} rows deleted, ` +
          `${summary.skipped_404} already-gone, ${summary.failed} failures`,
      );
      return;
    }

    console.error('cleanup-reporter: VERIFICATION FAILED');
    console.error(JSON.stringify(summary, null, 2));
    const failuresPath = path.join(
      process.cwd(),
      'test-results',
      'cleanup-verification-failures.txt',
    );
    try {
      fs.writeFileSync(failuresPath, JSON.stringify(summary, null, 2));
    } catch (e) {
      console.warn(
        `cleanup-reporter: failed to write failures artifact — ${(e as Error).message}`,
      );
    }
    // Do NOT throw — v1 is developer-ergonomics gate, not CI-strict.
  }
}

export default CleanupReporter;
