import { describe, expect, it } from 'vitest';

import {
  AUTH_KIND_VALUES,
  ENVIRONMENT_VALUES,
  FOLLOWUP_KIND_VALUES,
  HEALTH_STATUS_VALUES,
  JUDGMENT_SOURCE_VALUES,
  OBJECTIVE_DIRECTION_VALUES,
  OBJECTIVE_K_VALUES,
  OBJECTIVE_METRIC_VALUES,
  PROPOSAL_PR_STATE_VALUES,
  PROPOSAL_STATUS_VALUES,
  PRUNER_VALUES,
  RATING_VALUES,
  SAMPLER_VALUES,
  STUDY_STATUS_VALUES,
  TRIAL_SORT_VALUES,
  TRIAL_STATUS_VALUES,
} from '@/lib/enums';
import {
  expectGlossaryGroundedAgainstEnums,
  glossary,
  listGlossaryKeysWithPrefix,
} from '@/lib/glossary';

// Compile-time / type assertion: ensures enums.ts and glossary.ts are
// version-aligned via this single source-of-truth file.
void ENVIRONMENT_VALUES;
void HEALTH_STATUS_VALUES;

describe('glossary parity against ui/src/lib/enums.ts (FR-4 / AC-5)', () => {
  it('study.status — every StudyStatusWire value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('study.status', STUDY_STATUS_VALUES);
  });

  it('trial.status — every TrialStatusWire value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('trial.status', TRIAL_STATUS_VALUES);
  });

  it('trial.sort — every TrialSortKey value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('trial.sort', TRIAL_SORT_VALUES);
  });

  it('study.metric — every ObjectiveMetric value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('study.metric', OBJECTIVE_METRIC_VALUES);
  });

  it('study.k — every ObjectiveK value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('study.k', OBJECTIVE_K_VALUES);
  });

  it('study.direction — every ObjectiveDirection value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('study.direction', OBJECTIVE_DIRECTION_VALUES);
  });

  it('study.sampler — every SamplerKind value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('study.sampler', SAMPLER_VALUES);
  });

  it('study.pruner — every PrunerKind value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('study.pruner', PRUNER_VALUES);
  });

  // Phase 2 / 3 additions
  it('judgment.rating — every RatingWire value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('judgment.rating', RATING_VALUES);
  });

  it('judgment.source — every JudgmentSourceWire value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('judgment.source', JUDGMENT_SOURCE_VALUES);
  });

  it('proposal.status — every ProposalStatusWire value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('proposal.status', PROPOSAL_STATUS_VALUES);
  });

  it('proposal.pr_state — every ProposalPrStateWire value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('proposal.pr_state', PROPOSAL_PR_STATE_VALUES);
  });

  it('cluster.auth_kind — every AuthKind value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('cluster.auth_kind', AUTH_KIND_VALUES);
  });

  it('cluster.environment — every Environment value has a key + no extras', () => {
    expectGlossaryGroundedAgainstEnums('cluster.environment', ENVIRONMENT_VALUES);
  });
});

describe('feat_digest_executable_followups Story 5.3 — followup glossary keys', () => {
  it('every FollowupKind value has a glossary key + no extras', () => {
    // The kind-keys use a flat naming pattern (proposal.followup_kind_<kind>)
    // rather than a dot prefix, so we check each key individually rather
    // than via the expectGlossaryGroundedAgainstEnums helper.
    for (const kind of FOLLOWUP_KIND_VALUES) {
      const key = `proposal.followup_kind_${kind}` as const;
      expect(glossary[key], `glossary[${key}] missing`).toBeDefined();
      expect(glossary[key]?.short).toBeTruthy();
    }
  });

  it('the Run button + search-space-diff glossary keys are populated', () => {
    expect(glossary['proposal.followup_run_button']?.short).toBeTruthy();
    expect(glossary['proposal.followup_search_space_diff']?.short).toBeTruthy();
  });

  it('feat_digest_executable_followups_swap_template — declared-params-diff key is populated', () => {
    // Story 3.4 — new key for the swap_template card's parent-vs-target
    // declared_params comparison.
    expect(glossary['proposal.followup_declared_params_diff']?.short).toBeTruthy();
  });
});

describe('glossary content shape (FR-5)', () => {
  it('every `short` field is ≤140 characters', () => {
    for (const [key, entry] of Object.entries(glossary)) {
      if ('short' in entry && entry.short !== undefined) {
        expect(entry.short.length, `${key}.short`).toBeLessThanOrEqual(140);
      }
    }
  });

  it('every `long` field is ≤800 characters', () => {
    for (const [key, entry] of Object.entries(glossary)) {
      if ('long' in entry && entry.long !== undefined) {
        expect(entry.long.length, `${key}.long`).toBeLessThanOrEqual(800);
      }
    }
  });

  it('every `long` field is free of disallowed raw HTML (defense-in-depth)', () => {
    // The HelpPopover wrapper's react-markdown renderer also strips these via
    // `disallowedElements`; this is a content-time check so glossary edits can't
    // accidentally introduce them.
    for (const [key, entry] of Object.entries(glossary)) {
      if ('long' in entry && entry.long !== undefined) {
        expect(entry.long, `${key}.long must not contain <script>`).not.toMatch(/<script/i);
        expect(entry.long, `${key}.long must not contain <iframe>`).not.toMatch(/<iframe/i);
        expect(entry.long, `${key}.long must not contain <style>`).not.toMatch(/<style/i);
      }
    }
  });
});

describe('AC-12 — no backend references in user-visible copy', () => {
  // User-visible fields must never expose backend file paths or symbol names.
  // Citations belong in TypeScript comments above each group, never in copy.
  const FORBIDDEN_SUBSTRINGS = [
    'backend/',
    '.py',
    'StudyStatusWire',
    'TrialStatusWire',
    'TrialSortKey',
    'ObjectiveMetric',
    'ObjectiveK',
    'ObjectiveDirection',
    'SamplerKind',
    'PrunerKind',
    'K_REQUIRED',
  ];

  it('no `short` field mentions a backend file path or symbol', () => {
    for (const [key, entry] of Object.entries(glossary)) {
      if ('short' in entry && entry.short !== undefined) {
        for (const forbidden of FORBIDDEN_SUBSTRINGS) {
          expect(entry.short, `${key}.short must not contain "${forbidden}"`).not.toContain(
            forbidden,
          );
        }
      }
    }
  });

  it('no `long` field mentions a backend file path or symbol', () => {
    for (const [key, entry] of Object.entries(glossary)) {
      if ('long' in entry && entry.long !== undefined) {
        for (const forbidden of FORBIDDEN_SUBSTRINGS) {
          expect(entry.long, `${key}.long must not contain "${forbidden}"`).not.toContain(
            forbidden,
          );
        }
      }
    }
  });

  it('no `ariaLabel` field mentions a backend file path or symbol', () => {
    for (const [key, entry] of Object.entries(glossary)) {
      if ('ariaLabel' in entry && entry.ariaLabel !== undefined) {
        for (const forbidden of FORBIDDEN_SUBSTRINGS) {
          expect(entry.ariaLabel, `${key}.ariaLabel must not contain "${forbidden}"`).not.toContain(
            forbidden,
          );
        }
      }
    }
  });
});

describe('listGlossaryKeysWithPrefix helper', () => {
  it('returns per-wire-value keys but excludes the aggregate prefix-only key', () => {
    const studyMetricKeys = listGlossaryKeysWithPrefix('study.metric');
    expect(studyMetricKeys).not.toContain('study.metric');
    expect(studyMetricKeys).toContain('study.metric.ndcg');
    expect(studyMetricKeys).toContain('study.metric.mrr');
  });

  it('returns empty array for an unknown prefix', () => {
    expect(listGlossaryKeysWithPrefix('not.a.real.prefix')).toEqual([]);
  });
});
