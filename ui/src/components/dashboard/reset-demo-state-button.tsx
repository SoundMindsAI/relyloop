'use client';

import { useState } from 'react';
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

  function handleTerminalState() {
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
  }

  // Drive the success / failure toast once per terminal transition. The
  // statusQuery.dataUpdatedAt timestamp gates the effect so a stale-card
  // mount doesn't re-fire the toast.
  const [lastTerminalAt, setLastTerminalAt] = useState<number | null>(null);
  if (isTerminal && statusQuery.dataUpdatedAt > 0 && statusQuery.dataUpdatedAt !== lastTerminalAt) {
    setLastTerminalAt(statusQuery.dataUpdatedAt);
    handleTerminalState();
  }

  function progressPercent(): number | null {
    if (status == null || status.scenarios_total === 0) return null;
    return Math.round((status.scenarios_completed / status.scenarios_total) * 100);
  }

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
