// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { beforeAll, describe, expect, it } from 'vitest';

/**
 * Locks the glossary-gate edits applied to three Claude skill files by
 * `chore_guides_glossary_route`. If a future edit relaxes the gate language
 * (drops the same-PR default, removes the source-of-truth comment marker,
 * etc.), this test fails loudly so reviewers see the regression instead of
 * the glossary silently rotting.
 *
 * The skill files live at `.claude/skills/<skill>/SKILL.md` in the repo
 * root. Vitest runs with `cwd=ui/`, so we resolve from this test file's URL
 * up the tree: `ui/src/__tests__/skills/` → `<repo>/` is four `..` segments.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '../../../..');

function readSkill(name: string): string {
  const p = path.join(REPO_ROOT, '.claude', 'skills', name, 'SKILL.md');
  if (!existsSync(p)) {
    throw new Error(`SKILL.md not found at expected path: ${p}`);
  }
  return readFileSync(p, 'utf-8');
}

let implExecute: string;
let specGen: string;
let implPlanGen: string;

beforeAll(() => {
  implExecute = readSkill('impl-execute');
  specGen = readSkill('spec-gen');
  implPlanGen = readSkill('impl-plan-gen');
});

describe('impl-execute Step 3 — glossary gate (AC-10)', () => {
  it('Step 3 questionnaire surfaces both glossary questions', () => {
    expect(implExecute).toContain('New terminology');
    expect(implExecute).toContain('Drift on existing entries');
  });

  it('both questions cite ui/src/lib/glossary.ts', () => {
    // Naive count: the phrase should appear at least twice (one per bullet).
    const occurrences = implExecute.split('ui/src/lib/glossary.ts').length - 1;
    expect(occurrences).toBeGreaterThanOrEqual(2);
  });

  it('locks the same-PR default for new terminology', () => {
    expect(implExecute).toMatch(/SAME PR.*that's what shipped the term/);
  });

  it('locks the escape-hatch gating (explicitly approved, not free)', () => {
    expect(implExecute).toContain('escape hatch');
    expect(implExecute).toContain('explicitly-approved');
  });

  it('locks the no-escape-hatch rule for drift fixes', () => {
    expect(implExecute).toContain('no idea-file escape hatch');
  });

  it('locks the Step 8 finalization blocking enforcement', () => {
    expect(implExecute).toMatch(/blocks?\s+Step 8 finalization/i);
  });
});

describe('impl-execute — FAQ gates (chore_guides_faq)', () => {
  it('Step 2.5 tangential-observations sweep includes the FAQ-shaped question prompt', () => {
    // The 6th prompt (FAQ catch-net) sits in the numbered sweep walking back
    // through the implementation session.
    expect(implExecute).toMatch(/operator-judgment-shaped question that has no canonical answer/);
    expect(implExecute).toContain('ui/src/lib/faq.ts');
  });

  it('Step 2.5 prompts distinguish FAQ from tooltips/glossary', () => {
    expect(implExecute).toMatch(/Tooltips and the glossary are NOT the right surface/);
    expect(implExecute).toMatch(/they're definitional, not judgment-shaped/);
  });

  it('Step 3 guide-impact gate includes the "New operator decision point" class', () => {
    expect(implExecute).toContain('New operator decision point');
    expect(implExecute).toContain('FAQ surface');
  });

  it('Step 3 locks the tooltip / glossary / FAQ rubric', () => {
    expect(implExecute).toMatch(/tooltip if 1[-–]2 sentences suffice/);
    expect(implExecute).toMatch(/glossary if it's a definitional term/);
    expect(implExecute).toMatch(/FAQ if the answer requires balancing trade-offs/);
  });

  it('Step 3 FAQ gate defaults to same-PR, mirroring the glossary gate', () => {
    // The FAQ bullet explicitly says default is add-in-same-PR with the same
    // operator-approval gating as the New terminology bullet.
    expect(implExecute).toMatch(/default action is add-in-same-PR/);
  });
});

describe('spec-gen Step 3 item 11 — tooltip inventory glossary discipline (AC-11)', () => {
  it('locks the requirement that every tooltip cites an existing glossary key', () => {
    expect(specGen).toContain('every entry cites either an existing glossary key');
  });

  it('cites the source-of-truth file path', () => {
    expect(specGen).toContain('ui/src/lib/glossary.ts');
  });

  it('locks the grep verification method', () => {
    expect(specGen).toMatch(/verifiable by\s+`grep`/);
  });

  it('locks the new-key escape as a legitimate path', () => {
    expect(specGen).toContain('or names a new key to be added in a specific story');
  });
});

describe('impl-plan-gen line 111 — per-tooltip plan checklist (AC-12)', () => {
  it('locks the new fields required in the per-tooltip plan checklist', () => {
    expect(implPlanGen).toContain('glossary key, source-of-truth comment target');
  });

  it('includes the literal Source-of-truth comment marker shape so reviewers know what to grep', () => {
    expect(implPlanGen).toContain('// Source-of-truth:');
  });

  it('references the two canonical source-of-truth files', () => {
    expect(implPlanGen).toContain('ui/src/lib/glossary.ts');
    expect(implPlanGen).toContain('ui/src/lib/enums.ts');
  });
});
