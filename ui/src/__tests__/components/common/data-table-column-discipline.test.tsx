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

const ENUM_FILTER_RE = /filter:\s*\{\s*kind:\s*['"]enum['"]\s*,\s*wireValues:\s*([A-Z][A-Z0-9_]*)/g;
const FK_FILTER_RE = /filter:\s*\{\s*kind:\s*['"]fk-select['"]/g;
const SOURCE_OF_TRUTH_RE = /sourceOfTruth:\s*['"]([^'"]*)['"]/g;
const ENUMS_IMPORT_RE =
  /import\s+(?:type\s+)?\{[^}]*?\b([A-Z][A-Z0-9_]*)\b[^}]*?\}\s+from\s+['"]@\/lib\/enums['"]/g;

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

  // 1. Every enum filter must reference an identifier from enums.ts.
  const enumMatches = [...content.matchAll(ENUM_FILTER_RE)];
  const importedFromEnums = new Set<string>();
  for (const m of content.matchAll(ENUMS_IMPORT_RE)) {
    importedFromEnums.add(m[1]!);
  }
  for (const m of enumMatches) {
    const ident = m[1]!;
    if (!importedFromEnums.has(ident)) {
      errors.push({
        file: filePath,
        message: `enum filter references \`${ident}\` but it is not imported from '@/lib/enums'. Inline arrays are forbidden — add the value to enums.ts (with a 'Values must match backend/...' comment) and import it.`,
      });
      continue;
    }
    // Verify the enums.ts declaration is preceded by the canonical comment.
    const enumLines = enumsContent.split('\n');
    const declRe = new RegExp(`^\\s*export\\s+const\\s+${ident}\\b`);
    const declLineIdx = enumLines.findIndex((line) => declRe.test(line));
    if (declLineIdx === -1) {
      errors.push({
        file: filePath,
        message: `enum filter references \`${ident}\` but no \`export const ${ident}\` declaration found in src/lib/enums.ts.`,
      });
      continue;
    }
    // Look at lines N-1 and N-2 for the canonical comment.
    const commentRe = /^\s*\/\/\s*Values must match\s+backend\//;
    const precedingLines = [enumLines[declLineIdx - 1] ?? '', enumLines[declLineIdx - 2] ?? ''];
    if (!precedingLines.some((line) => commentRe.test(line))) {
      errors.push({
        file: filePath,
        message: `\`${ident}\` declaration in src/lib/enums.ts is missing the canonical \`// Values must match backend/...py <Symbol>\` source-of-truth comment on the preceding line.`,
      });
    }
  }

  // 2. Every filter (enum + fk-select) must carry a non-empty backend sourceOfTruth.
  const filterCount = enumMatches.length + [...content.matchAll(FK_FILTER_RE)].length;
  const sotMatches = [...content.matchAll(SOURCE_OF_TRUTH_RE)];
  if (filterCount > 0 && sotMatches.length === 0) {
    errors.push({
      file: filePath,
      message: `column-config declares ${filterCount} filter(s) but no \`sourceOfTruth: '...'\` field. Every filter column must cite the backend allowlist (e.g., 'backend/app/api/v1/schemas.py StudyStatusWire').`,
    });
  }
  for (const m of sotMatches) {
    const value = m[1]!;
    if (value.trim() === '') {
      errors.push({
        file: filePath,
        message: `\`sourceOfTruth\` is empty. Cite the backend allowlist (e.g., 'backend/app/api/v1/schemas.py StudyStatusWire').`,
      });
    } else if (!value.startsWith('backend/')) {
      errors.push({
        file: filePath,
        message: `\`sourceOfTruth\` value \`${value}\` does not start with 'backend/'. Filter values must be grounded in a backend file, not a frontend path.`,
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
