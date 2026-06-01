// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { components } from '@/lib/types';

type StudyConvergenceShape = components['schemas']['StudyConvergenceShape'];
type TrialsSummaryShape = components['schemas']['TrialsSummaryShape'];
// StudyDetail.status is an inline enum in the generated types — pull it off
// the StudyDetail shape so the union stays in lockstep with backend wire.
// Source-of-truth: backend/app/db/models/study.py status CHECK constraint.
type StudyStatusWire = components['schemas']['StudyDetail']['status'];

export interface ConvergencePanelProps {
  /** ``StudyDetail.convergence`` — null in-flight, sub-MIN trials, or
   * graceful-degrade null paths (invalid direction / classifier exception). */
  convergence: StudyConvergenceShape | null | undefined;
  /** ``StudyDetail.status`` — drives the null-state badge label. */
  studyStatus: StudyStatusWire;
  /** ``StudyDetail.trials_summary`` — drives the "not enough trials" vs
   * "unavailable" null-state branch. */
  trialsSummary: TrialsSummaryShape;
}

// Values must match backend/app/domain/study/convergence.py ConvergenceVerdict.
// Note: distinct from CONVERGENCE_BADGE in confidence-panel.tsx (different
// concept — that one classifies winner-trial *timing*, this one classifies
// metric *plateau*).
const VERDICT_BADGE: Record<
  StudyConvergenceShape['verdict'],
  { label: string; variant: 'success' | 'warning' }
> = {
  converged: { label: 'Converged', variant: 'success' },
  still_improving: { label: 'Still improving when it stopped', variant: 'warning' },
  too_few_trials: { label: 'Too few trials to tell', variant: 'warning' },
};

// Source-of-truth: backend/app/db/models/study.py status CHECK constraint.
// In-flight statuses get the "still running" null-state badge.
const IN_FLIGHT_STATUSES: ReadonlySet<StudyStatusWire> = new Set<StudyStatusWire>([
  'queued',
  'running',
]);

interface NullStateMeta {
  label: string;
  reason: 'still_running' | 'not_enough_trials' | 'unavailable';
}

function pickNullStateBadge(
  studyStatus: StudyStatusWire,
  trialsSummary: TrialsSummaryShape,
): NullStateMeta {
  if (IN_FLIGHT_STATUSES.has(studyStatus)) {
    return { label: 'Verdict pending — still running', reason: 'still_running' };
  }
  // CONVERGENCE_FLAT_MIN_COMPLETE = 5 — match
  // backend/app/domain/study/convergence.py.
  if (trialsSummary.complete < 5) {
    return {
      label: 'Verdict pending — not enough trials yet',
      reason: 'not_enough_trials',
    };
  }
  return { label: 'Verdict unavailable', reason: 'unavailable' };
}

export function ConvergencePanel({
  convergence,
  studyStatus,
  trialsSummary,
}: ConvergencePanelProps) {
  // Null path: render the panel shell with a neutral null-state badge so
  // operators see the affordance even before the study finishes. (The
  // confidence panel takes the opposite route — it renders nothing — but
  // convergence is more central to the overnight-study story, so we keep
  // the slot visible and explanatory.)
  if (!convergence) {
    const meta = pickNullStateBadge(studyStatus, trialsSummary);
    return (
      <Card data-testid="convergence-panel">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-1">
            Convergence
            <InfoTooltip glossaryKey="convergence_verdict" />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Badge
            variant="secondary"
            data-testid="cs-convergence-verdict"
            data-null-reason={meta.reason}
            aria-label={meta.label}
          >
            {meta.label}
          </Badge>
          <details data-testid="convergence-curve-details">
            <summary className="cursor-pointer text-xs uppercase text-muted-foreground flex items-center gap-1">
              Show convergence curve
              <InfoTooltip glossaryKey="convergence_curve" />
            </summary>
            <p className="mt-2 text-sm text-muted-foreground">—</p>
          </details>
        </CardContent>
      </Card>
    );
  }

  const { verdict, window_size, improvement_in_window, total_complete_trials, best_so_far_curve } =
    convergence;
  const badge = VERDICT_BADGE[verdict];
  const detailsOpen = verdict !== 'converged';
  // Reference-area covers the trailing window — index defensively because
  // window_size is always <= curve length, but guarantee never out-of-bounds.
  const windowStartIndex = Math.max(0, best_so_far_curve.length - window_size);
  const referenceX1 = best_so_far_curve[windowStartIndex]?.trial_number;
  const referenceX2 = best_so_far_curve[best_so_far_curve.length - 1]?.trial_number;
  const showReferenceArea =
    (verdict === 'converged' || verdict === 'still_improving') &&
    referenceX1 != null &&
    referenceX2 != null;

  const ariaLabel =
    `Convergence curve: ${verdict} after ${total_complete_trials} trials; ` +
    `window ${window_size}; improvement ${improvement_in_window.toFixed(4)}`;

  return (
    <Card data-testid="convergence-panel">
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-1">
          Convergence
          <InfoTooltip glossaryKey="convergence_verdict" />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Badge
          variant={badge.variant}
          data-testid="cs-convergence-verdict"
          data-verdict={verdict}
          aria-label={badge.label}
        >
          {badge.label}
        </Badge>
        <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
          Improved by {improvement_in_window.toFixed(4)} in the last {window_size} trials
          <InfoTooltip glossaryKey="convergence_window" />
        </p>
        <details data-testid="convergence-curve-details" {...(detailsOpen ? { open: true } : {})}>
          <summary className="cursor-pointer text-xs uppercase text-muted-foreground flex items-center gap-1">
            Show convergence curve
            <InfoTooltip glossaryKey="convergence_curve" />
          </summary>
          <div
            data-testid="convergence-curve"
            style={{ width: '100%', height: 240 }}
            aria-label={ariaLabel}
            className="mt-2"
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={best_so_far_curve}
                margin={{ top: 8, right: 16, bottom: 8, left: 24 }}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="trial_number" type="number" />
                <YAxis type="number" domain={['auto', 'auto']} />
                <RechartsTooltip
                  formatter={(value) =>
                    typeof value === 'number' ? value.toFixed(4) : String(value)
                  }
                />
                <Line
                  type="monotone"
                  dataKey="best_so_far"
                  stroke="#3b82f6"
                  dot={false}
                  isAnimationActive={false}
                />
                {showReferenceArea && (
                  <ReferenceArea
                    x1={referenceX1}
                    x2={referenceX2}
                    strokeOpacity={0}
                    fillOpacity={0.08}
                    fill="#3b82f6"
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}
