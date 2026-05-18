/**
 * Source-of-truth lint guard for form components (chore_form_dropdown_primitive Story 1.2 / FR-7).
 *
 * Sibling to `data-table-column-discipline.test.tsx`. That guard scans
 * `*.column-config.{ts,tsx}` for `wireValues` / `sourceOfTruth` discipline;
 * this guard scans **form components** (`ui/src/components/<resource>/<comp>.tsx`)
 * for inline `<SelectItem value="<literal>">` where `<literal>` matches any
 * backend enum wire value defined in `ui/src/lib/enums.ts`.
 *
 * Failure mode it catches:
 *   <SelectItem value="completed">Completed</SelectItem>   // ← matches STUDY_STATUS_VALUES
 *
 * Approved replacement:
 *   {STUDY_STATUS_VALUES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
 *
 * Escape hatch:
 *   // no-enum-import: gradual migration of legacy form — see PR #999
 *   …
 *   <SelectItem value="completed">…</SelectItem>   // ← allowed; reason required
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const COMPONENTS_ROOT = join(process.cwd(), 'src', 'components');
const ENUMS_PATH = join(process.cwd(), 'src', 'lib', 'enums.ts');

const SELECTITEM_IMPORT_RE = /import\s+(?:type\s+)?\{[^}]*\bSelectItem\b[^}]*\}\s+from\s+['"]@\/components\/ui\/select['"]/;
const SELECTITEM_LITERAL_RE = /<SelectItem[^>]*\svalue=['"]([^'"]+)['"]/g;
const ESCAPE_HATCH_RE = /\/\/\s*no-enum-import:(.*)$/m;
const VALUES_BLOCK_RE = /export\s+const\s+[A-Z_][A-Z0-9_]*_VALUES\s*=\s*\[([\s\S]*?)\]\s*as\s+const/g;
const STRING_OR_NUMBER_LITERAL_RE = /['"]([^'"]+)['"]|(\b\d+\b)/g;

const EXCLUDED_DIR_SEGMENTS = new Set(['__tests__', 'common']);

interface ValidationError {
  file: string;
  message: string;
}

function isExcludedDirSegment(name: string): boolean {
  return EXCLUDED_DIR_SEGMENTS.has(name);
}

function isColumnConfigFile(name: string): boolean {
  return name.endsWith('.column-config.ts') || name.endsWith('.column-config.tsx');
}

function walkFormFiles(dir: string): string[] {
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
      if (isExcludedDirSegment(name)) continue;
      out.push(...walkFormFiles(full));
    } else if (stats.isFile() && name.endsWith('.tsx') && !isColumnConfigFile(name)) {
      out.push(full);
    }
  }
  return out;
}

/**
 * Parse every `*_VALUES = [...] as const` block in enums.ts and union the
 * string/number literals into one set. Numbers are coerced to strings to
 * match how `<SelectItem value="0">` renders the RATING_VALUES = [0,1,2,3]
 * array in JSX.
 */
export function extractEnumWireValues(enumsContent: string): Set<string> {
  const out = new Set<string>();
  for (const blockMatch of enumsContent.matchAll(VALUES_BLOCK_RE)) {
    const body = blockMatch[1]!;
    for (const literalMatch of body.matchAll(STRING_OR_NUMBER_LITERAL_RE)) {
      const value = literalMatch[1] ?? literalMatch[2];
      if (value) out.add(value);
    }
  }
  return out;
}

/**
 * Pure: validate a single form file's content against the enum source-of-truth.
 * Returns a list of validation errors; empty array = pass.
 */
export function validateFormSelect(
  filePath: string,
  content: string,
  enumsContent: string,
): ValidationError[] {
  const errors: ValidationError[] = [];

  // 1. If the file does not import SelectItem from shadcn, it's irrelevant.
  if (!SELECTITEM_IMPORT_RE.test(content)) return errors;

  // 2. Check for the escape-hatch comment.
  const escapeMatch = content.match(ESCAPE_HATCH_RE);
  if (escapeMatch) {
    const reason = (escapeMatch[1] ?? '').trim();
    if (reason.length === 0) {
      errors.push({
        file: filePath,
        message:
          'The // no-enum-import: comment requires a non-empty reason after the colon. ' +
          'Format: // no-enum-import: <reason>',
      });
      return errors;
    }
    // Valid escape hatch with reason — file is opted out.
    return errors;
  }

  // 3. Scan for <SelectItem value="<literal>"> matches.
  const enumValues = extractEnumWireValues(enumsContent);
  for (const match of content.matchAll(SELECTITEM_LITERAL_RE)) {
    const literal = match[1]!;
    if (enumValues.has(literal)) {
      errors.push({
        file: filePath,
        message:
          `inline <SelectItem value="${literal}"> matches a backend enum wire value defined in ` +
          `src/lib/enums.ts. Import the matching *_VALUES array from '@/lib/enums' and map over ` +
          `it instead: {STATUS_VALUES.map((s) => <SelectItem key={s} value={s}>…</SelectItem>)}. ` +
          `If you have a legitimate reason to inline this literal, add a top-of-file comment: ` +
          `// no-enum-import: <reason>.`,
      });
    }
  }

  return errors;
}

describe('Form-select discipline (Story 1.2)', () => {
  it('scans every form *.tsx under ui/src/components — all pass', () => {
    const files = walkFormFiles(COMPONENTS_ROOT);
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const allErrors: ValidationError[] = [];
    for (const file of files) {
      const content = readFileSync(file, 'utf8');
      allErrors.push(...validateFormSelect(file, content, enumsContent));
    }
    if (allErrors.length > 0) {
      const summary = allErrors.map((e) => `  ${e.file}: ${e.message}`).join('\n');
      throw new Error(`Form-select discipline violations:\n${summary}`);
    }
  });

  it('regression: inline <SelectItem value="completed"> matching STUDY_STATUS_VALUES fails', () => {
    const synthetic = `
import { SelectItem } from '@/components/ui/select';

export function Foo() {
  return <SelectItem value="completed">Completed</SelectItem>;
}
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateFormSelect('synthetic.tsx', synthetic, enumsContent);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]!.message).toMatch(/completed/);
    expect(errors[0]!.message).toMatch(/enums\.ts/);
  });

  it('regression: inline <SelectItem value="ndcg"> matching OBJECTIVE_METRIC_VALUES fails', () => {
    const synthetic = `
import { SelectItem } from '@/components/ui/select';

export function Foo() {
  return <SelectItem value="ndcg">NDCG</SelectItem>;
}
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateFormSelect('synthetic.tsx', synthetic, enumsContent);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]!.message).toMatch(/ndcg/);
  });

  it('regression: mapped-from-enum pattern passes', () => {
    const synthetic = `
import { SelectItem } from '@/components/ui/select';
import { STUDY_STATUS_VALUES } from '@/lib/enums';

export function Foo() {
  return STUDY_STATUS_VALUES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>);
}
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateFormSelect('synthetic.tsx', synthetic, enumsContent);
    expect(errors).toEqual([]);
  });

  it('regression: indexed access passes (no inline literal)', () => {
    const synthetic = `
import { SelectItem } from '@/components/ui/select';
import { STUDY_STATUS_VALUES } from '@/lib/enums';

export function Foo() {
  return <SelectItem value={STUDY_STATUS_VALUES[0]}>First</SelectItem>;
}
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateFormSelect('synthetic.tsx', synthetic, enumsContent);
    expect(errors).toEqual([]);
  });

  it('regression: escape hatch with reason passes', () => {
    const synthetic = `
// no-enum-import: legacy migration in progress — see PR #999
import { SelectItem } from '@/components/ui/select';

export function Foo() {
  return <SelectItem value="completed">Completed</SelectItem>;
}
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateFormSelect('synthetic.tsx', synthetic, enumsContent);
    expect(errors).toEqual([]);
  });

  it('regression: escape hatch with empty reason fails', () => {
    const synthetic = `
// no-enum-import:
import { SelectItem } from '@/components/ui/select';

export function Foo() {
  return <SelectItem value="completed">Completed</SelectItem>;
}
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateFormSelect('synthetic.tsx', synthetic, enumsContent);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]!.message).toMatch(/non-empty reason/);
  });

  it('regression: file without SelectItem import is ignored', () => {
    const synthetic = `
import { Button } from '@/components/ui/button';

export function Foo() {
  return <Button>Click</Button>;
}
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateFormSelect('synthetic.tsx', synthetic, enumsContent);
    expect(errors).toEqual([]);
  });

  it('regression: SelectItem with non-enum literal is ignored', () => {
    const synthetic = `
import { SelectItem } from '@/components/ui/select';

export function Foo() {
  return <SelectItem value="custom-non-enum-value">Custom</SelectItem>;
}
`;
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const errors = validateFormSelect('synthetic.tsx', synthetic, enumsContent);
    expect(errors).toEqual([]);
  });

  it('extractEnumWireValues includes both string and number literals', () => {
    const enumsContent = readFileSync(ENUMS_PATH, 'utf8');
    const values = extractEnumWireValues(enumsContent);
    // String enums
    expect(values.has('elasticsearch')).toBe(true);
    expect(values.has('opensearch')).toBe(true);
    expect(values.has('completed')).toBe(true);
    expect(values.has('green')).toBe(true);
    // Number enums (RATING_VALUES = [0, 1, 2, 3])
    expect(values.has('0')).toBe(true);
    expect(values.has('3')).toBe(true);
  });
});
