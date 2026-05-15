'use client';

import Link from 'next/link';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

/**
 * First-run "Start here" checklist for the dashboard.
 *
 * Renders a Stripe-style 3-step checklist that auto-completes as the user
 * makes progress:
 *
 *   1. Register your first cluster      → /clusters
 *   2. Create a query set + judgments    → /query-sets
 *   3. Run your first study              → /studies
 *
 * Each step takes a boolean `done` prop from the dashboard page, which
 * already fetches counts via TanStack Query. When `done === true`, the step
 * renders with a ✓ icon and `text-muted-foreground` styling; when not yet
 * done, the step shows its CTA link as the primary affordance.
 *
 * Steps below the current step (e.g., step 3 when step 1 isn't done yet)
 * are rendered as "locked" — visible but with a muted label so the user
 * understands the dependency order.
 *
 * Per Phase 3 of feat_contextual_help_mvp2.
 */

interface ChecklistStep {
  readonly key: string;
  readonly title: string;
  readonly description: string;
  readonly href: string;
  readonly ctaLabel: string;
  readonly done: boolean;
}

export interface StartHereChecklistProps {
  hasClusters: boolean;
  hasQuerySetsWithJudgments: boolean;
  hasStudies: boolean;
}

export function StartHereChecklist({
  hasClusters,
  hasQuerySetsWithJudgments,
  hasStudies,
}: StartHereChecklistProps): React.ReactElement | null {
  // The whole component is for the first-run state — if any meaningful state
  // exists, hide it.
  if (hasClusters && hasQuerySetsWithJudgments && hasStudies) return null;

  const steps: readonly ChecklistStep[] = [
    {
      key: 'cluster',
      title: 'Register your first cluster',
      description:
        'Point RelyLoop at an Elasticsearch or OpenSearch index. Credentials mount from ./secrets/.',
      href: '/clusters',
      ctaLabel: 'Add a cluster',
      done: hasClusters,
    },
    {
      key: 'query-set',
      title: 'Create a query set and import judgments',
      description:
        'A named collection of test queries + relevance ratings. The ground truth your studies optimize against.',
      href: '/query-sets',
      ctaLabel: 'Build a query set',
      done: hasQuerySetsWithJudgments,
    },
    {
      key: 'study',
      title: 'Run your first study',
      description:
        'Pick a metric (NDCG@10 is a good default), a small search space, and 25–100 trials. Watch trials populate live.',
      href: '/studies',
      ctaLabel: 'Create a study',
      done: hasStudies,
    },
  ];

  // The "current" step is the first incomplete one. Steps after it are
  // gently locked (still visible, but no CTA link).
  const currentIdx = steps.findIndex((s) => !s.done);

  return (
    <Card data-testid="start-here-checklist">
      <CardHeader>
        <CardTitle className="text-base">Get started</CardTitle>
        <p className="text-sm text-muted-foreground">
          Three steps to your first relevance proposal. Each one unlocks the next.
        </p>
      </CardHeader>
      <CardContent>
        <ol className="space-y-3">
          {steps.map((step, i) => {
            const isLocked = !step.done && i > currentIdx;
            const isCurrent = i === currentIdx;
            return (
              <li
                key={step.key}
                data-testid={`start-here-step-${step.key}`}
                data-done={step.done ? 'true' : 'false'}
                data-locked={isLocked ? 'true' : 'false'}
                className={`flex items-start gap-3 rounded-md border p-3 ${
                  step.done
                    ? 'border-emerald-200 bg-emerald-50/50 dark:border-emerald-900/40 dark:bg-emerald-950/20'
                    : isCurrent
                      ? 'border-foreground/20 bg-background'
                      : 'border-muted bg-muted/30 opacity-70'
                }`}
              >
                <span
                  aria-hidden="true"
                  className={
                    'mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-xs ' +
                    (step.done
                      ? 'border-emerald-500 bg-emerald-500 text-white'
                      : 'border-muted-foreground/40 bg-background text-muted-foreground')
                  }
                >
                  {step.done ? '✓' : String(i + 1)}
                </span>
                <div className="flex-1 space-y-1">
                  <p className="text-sm font-medium">
                    {step.title}
                    {step.done && (
                      <span className="ml-2 text-xs font-normal text-emerald-700 dark:text-emerald-400">
                        Done
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-muted-foreground">{step.description}</p>
                  {!step.done && !isLocked && (
                    <Link
                      href={step.href}
                      data-testid={`start-here-cta-${step.key}`}
                      className="inline-block text-xs font-medium text-blue-600 underline-offset-4 hover:underline"
                    >
                      {step.ctaLabel} →
                    </Link>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}
