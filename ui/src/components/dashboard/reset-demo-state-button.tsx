// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { useDemoReseedStatus, type ReseedStatusResponse } from '@/lib/api/demo-reseed';
import { apiClient } from '@/lib/api-client';
import { ApiError, isApiError } from '@/lib/api-errors';

/**
 * "Reset to demo state" affordance for the first-run dashboard.
 *
 * Per ``bug_demo_reseed_fake_metric_regression``. The button replaces the
 * previous synchronous-180s POST with an async enqueue + poll pattern:
 *
 *   1. POST `/api/v1/_test/demo/reseed` → 202 + initial
 *      ReseedStatusResponse. The backend's Arq worker picks up the job and
 *      runs the real-study seeding path (real Optuna trials, real metrics
 *      per scenario).
 *   2. ``useDemoReseedStatus`` polls every 2s while ``status === 'running'``
 *      and renders the worker's ``current_step`` string verbatim so the
 *      operator sees forward motion ("seeding acme-products-prod: trial 7/12").
 *   3. On ``complete``: success toast + invalidate the dashboard's queries.
 *      On ``failed``: error toast with ``failed_reason``.
 *
 * The dialog stays open during the reseed so the user sees progress; the
 * Cancel button is replaced with Close once the run terminates.
 */
export function ResetDemoStateButton(): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [pollingEnabled, setPollingEnabled] = useState(false);
  const queryClient = useQueryClient();
  const statusQuery = useDemoReseedStatus({ enabled: pollingEnabled });
  const status: ReseedStatusResponse | undefined = statusQuery.data;
  const isRunning = status?.status === 'running';
  const isTerminal = status?.status === 'complete' || status?.status === 'failed';

  async function startReseed(event: React.MouseEvent): Promise<void> {
    // Keep the dialog open so the progress card replaces the "are you sure"
    // copy.
    event.preventDefault();
    setPollingEnabled(true);
    try {
      await apiClient.post<ReseedStatusResponse>('/api/v1/_test/demo/reseed', undefined);
      // Worker writes status updates to Redis; the polling hook picks them
      // up on its next 2s tick.
    } catch (err) {
      setPollingEnabled(false);
      if (isApiError(err) && (err as ApiError).errorCode === 'SEED_IN_PROGRESS') {
        toast.info(
          'A reseed is already running. Watch progress in the dialog or wait for it to finish.',
        );
        // Resume polling so the operator sees the in-flight run's progress.
        setPollingEnabled(true);
        return;
      }
      toast.error(
        `Reseed enqueue failed: ${
          isApiError(err) ? (err as ApiError).errorCode : 'unknown'
        }. Refresh and try again, or run \`make seed-demo FORCE=1\` from the host.`,
      );
    }
  }

  // Drive the success / failure toast once per terminal transition. Per
  // Gemini PR #286 finding #1 — side effects (toasts, invalidateQueries)
  // MUST run inside useEffect, not during render. Use a useRef for the
  // dedup gate so the effect's setState→re-render→setState loop is
  // sidestepped (eslint `react-hooks/set-state-in-effect`).
  const lastTerminalAtRef = useRef<number | null>(null);
  useEffect(() => {
    if (!isTerminal || statusQuery.dataUpdatedAt === 0) return;
    if (statusQuery.dataUpdatedAt === lastTerminalAtRef.current) return;
    lastTerminalAtRef.current = statusQuery.dataUpdatedAt;
    if (status?.status === 'complete') {
      toast.success(
        `Demo state reset — ${status.summary?.studies_completed ?? 0} studies completed with real metrics. The dashboard will refresh in a moment.`,
      );
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ['clusters'] }),
        queryClient.invalidateQueries({ queryKey: ['judgment-lists'] }),
        queryClient.invalidateQueries({ queryKey: ['studies'] }),
        queryClient.invalidateQueries({ queryKey: ['proposals'] }),
      ]);
    } else if (status?.status === 'failed') {
      toast.error(
        `Reseed failed: ${status.failed_reason ?? 'unknown'}. See logs / demo-reseed runbook.`,
      );
    }
  }, [
    isTerminal,
    statusQuery.dataUpdatedAt,
    status?.status,
    status?.summary?.studies_completed,
    status?.failed_reason,
    queryClient,
  ]);

  function progressPercent(): number | null {
    if (status == null || status.scenarios_total === 0) return null;
    return Math.round((status.scenarios_completed / status.scenarios_total) * 100);
  }

  // Auto-scroll the step-history log to the newest entry as steps arrive.
  // ``steps`` is appended-to by the worker (oldest-first), so the freshest
  // line is at the bottom; keep it pinned into view on each poll tick.
  const steps = status?.steps ?? [];
  const logRef = useRef<HTMLOListElement | null>(null);
  useEffect(() => {
    const el = logRef.current;
    if (el != null) el.scrollTop = el.scrollHeight;
    // ``open`` is a dep so the log pins to the newest entry when the dialog is
    // (re)opened — without it, reopening with an unchanged ``steps.length``
    // would leave the log scrolled to the top (the ref was null while closed).
  }, [steps.length, open]);

  return (
    <>
      <Button
        type="button"
        variant="secondary"
        onClick={() => {
          setOpen(true);
          // Polling only starts after the operator clicks Confirm
          // (``startReseed``). Opening the dialog alone doesn't fire the
          // status endpoint — that endpoint may not even exist if the
          // backend hasn't been rebuilt, and polling a missing endpoint
          // floods the console with 404s.
        }}
        data-testid="reset-demo-state-trigger"
      >
        Reset to demo state
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {isRunning
                ? 'Reseeding demo data…'
                : isTerminal && status?.status === 'complete'
                  ? 'Demo state reset complete'
                  : isTerminal && status?.status === 'failed'
                    ? 'Reseed failed'
                    : 'Wipe and reseed demo data?'}
            </AlertDialogTitle>
            {!isRunning && !isTerminal && (
              <AlertDialogDescription>
                This will WIPE the dev Postgres demo state (clusters, studies, query sets, query
                templates, judgment lists, judgments, trials, digests, proposals) AND the
                corresponding ES/OS indices. Then it will seed 5 demo scenarios by running real
                Optuna trials (~5–9 minutes wall-clock; each scenario gets a real best metric). The
                5th scenario (acme-products-rich-prod) bulk-indexes 1000 ESCI products and calls the
                OpenAI API to generate judgments (~$0.05 in tokens); it is skipped gracefully if no
                OpenAI key is configured.
              </AlertDialogDescription>
            )}
            {isRunning && status && (
              <AlertDialogDescription asChild>
                <div className="space-y-2" data-testid="reset-demo-state-progress">
                  <div className="text-sm">{status.current_step ?? 'Starting…'}</div>
                  <div className="text-xs text-muted-foreground">
                    Scenario {status.scenarios_completed} of {status.scenarios_total}
                    {progressPercent() != null && ` (${progressPercent()}%)`}
                  </div>
                </div>
              </AlertDialogDescription>
            )}
            {isTerminal && status?.status === 'failed' && (
              <AlertDialogDescription>
                {status.failed_reason ?? 'Unknown failure — see logs.'}
              </AlertDialogDescription>
            )}
            {isTerminal && status?.status === 'complete' && status.summary && (
              <AlertDialogDescription>
                Completed in {(status.summary.duration_ms / 1000).toFixed(1)}s.
                {status.summary.studies_completed} studies seeded with distinct real metrics.
              </AlertDialogDescription>
            )}
          </AlertDialogHeader>
          {steps.length > 0 && (
            <div className="space-y-1" data-testid="reset-demo-state-log">
              <div className="text-xs font-medium text-muted-foreground">Step log</div>
              <ol
                ref={logRef}
                className="max-h-40 overflow-y-auto rounded border bg-muted/40 p-2 font-mono text-xs leading-relaxed"
                data-testid="reset-demo-state-log-list"
              >
                {steps.map((step, i) => (
                  // The history is append-only and may contain repeated
                  // (non-adjacent) step strings, so the index is the stable
                  // key here — entries are never reordered or removed.
                  <li key={i} className="whitespace-pre-wrap break-words">
                    {step}
                  </li>
                ))}
              </ol>
            </div>
          )}
          <AlertDialogFooter>
            {!isRunning && !isTerminal && (
              <>
                <AlertDialogCancel data-testid="reset-demo-state-cancel">Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={startReseed} data-testid="reset-demo-state-confirm">
                  Reset to demo state
                </AlertDialogAction>
              </>
            )}
            {isRunning && (
              <AlertDialogCancel data-testid="reset-demo-state-running-close">
                Run in background
              </AlertDialogCancel>
            )}
            {isTerminal && (
              <AlertDialogAction
                onClick={() => {
                  setOpen(false);
                }}
                data-testid="reset-demo-state-done"
              >
                Close
              </AlertDialogAction>
            )}
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
