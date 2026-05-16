/**
 * Source-of-truth lint guard test (feat_data_table_primitive Story 2.13 / FR-17 / AC-16).
 *
 * Scans every `*.column-config.ts` (or `*.column-config.tsx`) under
 * `ui/src/components/**` and asserts:
 *
 *  1. Each `filter: { kind: 'enum', ... }` column references `wireValues` via
 *     an identifier (not an inline literal) that is imported from
 *     `'@/lib/enums'`. The identifier's declaration in `enums.ts` must be
 *     immediately preceded (line N-1 or N-2) by the canonical
 *     `// Values must match backend/...py <Symbol>` comment.
 *  2. Each `filter: { kind: 'enum' | 'fk-select', ... }` column carries a
 *     non-empty `sourceOfTruth: '...'` field starting with `backend/`.
 *
 * In Epic 2 (this story), no `*.column-config.ts` files exist yet, so the
 * scan passes vacuously. Epic 3 stories add one column config per migrated
 * table; this test then fires fully. The regression test below pins the
 * failure-message contract by validating synthetic malformed content.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const COMPONENTS_ROOT = join(process.cwd(), 'src', 'components');
const ENUMS_PATH = join(process.cwd(), 'src', 'lib', 'enums.ts');

// Matches a `filter: { … }` block — captures everything between the braces
// (greedy, but bounded to a single filter block since we anchor on the
// closing `}` before the next column-config field). `[\s\S]` accepts newlines.
const FILTER_BLOCK_RE = /filter:\s*(\{[\s\S]*?\})/g;
const ENUMS_IMPORT_BLOCK_RE = /import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['"]@\/lib\/enums['"]/g;
const UPPER_IDENT_RE = /\b([A-Z][A-Z0-9_]*)\b/g;

function walkColumnConfigs(dir: string): string[] {
  const out: string[] = [];
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const name of entries) {
    const full = join(dir, name);
    const stats = statSync(full);
    if (stats.isDirectory()) {
      out.push(...walkColumnConfigs(full));
    } else if (
      stats.isFile() &&
      (name.endsWith('.column-config.ts') || name.endsWith('.column-config.tsx'))
    ) {
      out.push(full);
    }
  }
  return out;
}

interface ValidationError {
  file: string;
  message: string;
}

/**
 * Validate a single column-config file. Pure: takes the file path (for
 * error messages), the file content, and the canonical `enums.ts` content.
 * Returns the list of errors found; empty array = pass.
 */
export function validateColumnConfig(
  filePath: string,
  content: string,
  enumsContent: string,
): ValidationError[] {
  const errors: ValidationError[] = [];

  // Collect every UPPER_SNAKE identifier in any `import { ... } from '@/lib/enums'`
  // statement so multi-name imports like `import { A, B } from '@/lib/enums'`
  // register both names, not just the first.
  const importedFromEnums = new Set<string>();
  for (const blockMatch of content.matchAll(ENUMS_IMPORT_BLOCK_RE)) {
    const block = blockMatch[1]!;
    for (const identMatch of block.matchAll(UPPER_IDENT_RE)) {
      importedFromEnums.add(identMatch[1]!);
    }
  }
  const enumLines = enumsContent.split('\n');
  const canonicalCommentRe = /^\s*\/\/\s*Values must match\s+backend\//;

  // Parse each filter block individually so per-filter assertions fire
  // independently (a file with two filters where only one has a valid
  // `sourceOfTruth` still fails).
  for (const blockMatch of content.matchAll(FILTER_BLOCK_RE)) {
    const block = blockMatch[1]!;
    const kindMatch = block.match(/kind:\s*['"]([^'"]+)['"]/);
    if (!kindMatch) continue;
    const kind = kindMatch[1]!;

    // sourceOfTruth assertions apply to every filter kind.
    const sotMatch = block.match(/sourceOfTruth:\s*['"]([^'"]*)['"]/);
    if (!sotMatch) {
      errors.push({
        file: filePath,
        message: `filter block (kind: '${kind}') is missing a \`sourceOfTruth: '...'\` field. Every filter column must cite the backend allowlist (e.g., 'backend/app/api/v1/schemas.py StudyStatusWire').`,
      });
    } else {
      const value = sotMatch[1]!;
      if (value.trim() === '') {
        errors.push({
          file: filePath,
          message: `filter block (kind: '${kind}') has an empty \`sourceOfTruth\`. Cite the backend allowlist.`,
        });
      } else if (!value.startsWith('backend/')) {
        errors.push({
          file: filePath,
          message: `filter block (kind: '${kind}') \`sourceOfTruth\` value \`${value}\` does not start with 'backend/'. Filter values must be grounded in a backend file, not a frontend path.`,
        });
      }
    }

    if (kind !== 'enum') continue;

    // For enum filters: wireValues must be an identifier imported from
    // '@/lib/enums', not an inline literal. Match `wireValues: <expr>`
    // where <expr> ends at the next `,` or `}` (not inside quotes/brackets).
    const wireMatch = block.match(/wireValues:\s*([^,}\n]+?)(?=\s*[,}])/);
    if (!wireMatch) {
      errors.push({
        file: filePath,
        message: `enum filter is missing a \`wireValues\` field.`,
      });
      continue;
    }
    const wireExpr = wireMatch[1]!.trim();
    // Allowed: a single UPPER_SNAKE identifier (re-export of enums.ts).
    // Forbidden: inline arrays (`['a', 'b']`), object expressions, function calls.
    if (!/^[A-Z][A-Z0-9_]*$/.test(wireExpr)) {
      errors.push({
        file: filePath,
        message: `enum filter \`wireValues\` is not a single identifier (\`${wireExpr}\`). Inline arrays are forbidden — define the array in src/lib/enums.ts with a 'Values must match backend/...' comment and import it.`,
      });
      continue;
    }
    const ident = wireExpr;
    if (!importedFromEnums.has(ident)) {
      errors.push({
        file: filePath,
        message: `enum filter references \`${ident}\` but it is not imported from '@/lib/enums'.`,
      });
      continue;
    }
    // Verify the enums.ts declaration is preceded by the canonical comment.
    const declRe = new RegExp(`^\\s*export\\s+const\\s+${ident}\\b`);
    const declLineIdx = enumLines.findIndex((line) => declRe.test(line));
    if (declLineIdx === -1) {
      errors.push({
        file: filePath,
        message: `enum filter references \`${ident}\` but no \`export const ${ident}\` declaration found in src/lib/enums.ts.`,
      });
      continue;
    }
    const precedingLines = [enumLines[declLineIdx - 1] ?? '', enumLines[declLineIdx - 2] ?? ''];
    if (!precedingLines.some((line) => canonicalCommentRe.test(line))) {
      errors.push({
        file: filePath,
        message: `\`${ident}\` declaration in src/lib/enums.ts is missing the canonical \`// Values must match backend/...py <Symbol>\` source-of-truth comment on the preceding line.`,
      });
    }
  }

  return errors;
}

describe('Column-config source-of-truth discipline (Story 2.13)', () => {
  it('scans every *.column-config.ts under ui/src/components — all pass', () => {
    const files = walkColumnConfigs(COMPONENTS_ROOT);
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const allErrors: ValidationError[] = [];
    for (const file of files) {
      const content = readFileSync(file, 'utf8');
      allErrors.push(...validateColumnConfig(file, content, enumsContent));
    }
    if (allErrors.length > 0) {
      const summary = allErrors.map((e) => `  ${e.file}: ${e.message}`).join('\n');
      throw new Error(`Column-config discipline violations:\n${summary}`);
    }
  });

  it('regression: enum filter without sourceOfTruth fails with a clear message', () => {
    const synthetic = `
import { STUDY_STATUS_VALUES } from '@/lib/enums';

export const cols = [
  {
    id: 'status',
    filter: { kind: 'enum', wireValues: STUDY_STATUS_VALUES },
  },
];
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateColumnConfig('synthetic.column-config.ts', synthetic, enumsContent);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]!.message).toMatch(/sourceOfTruth/);
  });

  it('regression: per-filter check — one missing sourceOfTruth in a two-filter file still fails', () => {
    const synthetic = `
import { STUDY_STATUS_VALUES, TRIAL_STATUS_VALUES } from '@/lib/enums';

export const cols = [
  {
    id: 'status',
    filter: {
      kind: 'enum',
      wireValues: STUDY_STATUS_VALUES,
      sourceOfTruth: 'backend/app/api/v1/schemas.py StudyStatusWire',
    },
  },
  {
    id: 'trial_status',
    filter: { kind: 'enum', wireValues: TRIAL_STATUS_VALUES },
  },
];
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateColumnConfig('synthetic.column-config.ts', synthetic, enumsContent);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors.some((e) => /is missing a `sourceOfTruth/.test(e.message))).toBe(true);
  });

  it('regression: inline array literal in wireValues is rejected', () => {
    const synthetic = `
export const cols = [
  {
    id: 'status',
    filter: {
      kind: 'enum',
      wireValues: ['queued', 'running'],
      sourceOfTruth: 'backend/app/api/v1/schemas.py StudyStatusWire',
    },
  },
];
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateColumnConfig('synthetic.column-config.ts', synthetic, enumsContent);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors.some((e) => /Inline arrays are forbidden/.test(e.message))).toBe(true);
  });

  it('regression: enum filter referencing inline (non-imported) literal fails', () => {
    const synthetic = `
export const cols = [
  {
    id: 'status',
    filter: {
      kind: 'enum',
      wireValues: SOME_INLINE_LITERAL,
      sourceOfTruth: 'backend/app/api/v1/schemas.py FakeWire',
    },
  },
];
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateColumnConfig('synthetic.column-config.ts', synthetic, enumsContent);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]!.message).toMatch(/not imported from '@\/lib\/enums'/);
  });

  it("regression: sourceOfTruth that doesn't start with 'backend/' fails", () => {
    const synthetic = `
import { STUDY_STATUS_VALUES } from '@/lib/enums';

export const cols = [
  {
    id: 'status',
    filter: {
      kind: 'enum',
      wireValues: STUDY_STATUS_VALUES,
      sourceOfTruth: 'ui/src/lib/enums.ts STUDY_STATUS_VALUES',
    },
  },
];
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateColumnConfig('synthetic.column-config.ts', synthetic, enumsContent);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors.some((e) => /does not start with 'backend\//.test(e.message))).toBe(true);
  });

  it('regression: fk-select without sourceOfTruth fails', () => {
    const synthetic = `
export const cols = [
  {
    id: 'cluster_id',
    filter: { kind: 'fk-select', placeholder: 'All clusters' },
  },
];
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateColumnConfig('synthetic.column-config.ts', synthetic, enumsContent);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]!.message).toMatch(/sourceOfTruth/);
  });

  it('regression: enums.ts identifier without the canonical comment fails', () => {
    // Build a synthetic enums.ts content where FAKE_VALUES lacks the
    // 'Values must match backend/...' comment immediately above.
    const fakeEnums = `
export const FAKE_VALUES = ['a', 'b'] as const;
`;
    const synthetic = `
import { FAKE_VALUES } from '@/lib/enums';

export const cols = [
  {
    id: 'fake',
    filter: {
      kind: 'enum',
      wireValues: FAKE_VALUES,
      sourceOfTruth: 'backend/app/api/v1/schemas.py FakeWire',
    },
  },
];
`;
    const errors = validateColumnConfig('synthetic.column-config.ts', synthetic, fakeEnums);
    expect(errors.some((e) => /canonical .*source-of-truth comment/.test(e.message))).toBe(true);
  });
});
