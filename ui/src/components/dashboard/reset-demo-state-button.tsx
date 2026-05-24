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
import { apiClient } from '@/lib/api-client';
import { ApiError, isApiError } from '@/lib/api-errors';

/**
 * "Reset to demo state" affordance for the first-run dashboard.
 *
 * Per feat_home_demo_reseed_endpoint spec FR-6 + plan Story 2.1. Self-
 * contained component:
 *   - Renders a secondary <Button> that opens an <AlertDialog> confirming
 *     the destructive wipe + reseed.
 *   - On confirm: POSTs ``/api/v1/_test/demo/reseed`` via the project's
 *     ``apiClient`` wrapper (which throws ``ApiError`` on non-2xx).
 *   - Client-side 180s abort signal — generous ceiling even when the
 *     backend's ``demo_reseed_per_call_http_timeout_s`` is set high.
 *   - On success: sonner toast + invalidates the four TanStack queries the
 *     dashboard uses for its first-run signals + ``recent`` cards.
 *   - On envelope failure (``ApiError``): toast carries the error code and
 *     the runbook hint about ``docker compose restart api``.
 *   - On non-envelope failure (network / abort): a softer "in progress or
 *     unreachable" toast so the operator refreshes rather than retrying
 *     against a still-busy backend.
 */
interface ReseedSummary {
  clusters_created: number;
  query_sets_created: number;
  studies_completed: number;
  proposals_created: number;
  duration_ms: number;
}

export function ResetDemoStateButton(): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const queryClient = useQueryClient();

  async function handleConfirm(event: React.MouseEvent): Promise<void> {
    // Keep the dialog open while the POST is in-flight so the user sees
    // the "Resetting…" affordance.
    event.preventDefault();
    setIsPending(true);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 180_000);
    try {
      const { data } = await apiClient.post<ReseedSummary>('/api/v1/_test/demo/reseed', undefined, {
        signal: controller.signal,
      });
      toast.success(
        `Demo state reset — ${data.clusters_created} clusters, ${data.query_sets_created} query sets, ${data.studies_completed} completed studies. The dashboard will refresh in a moment.`,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['clusters'] }),
        queryClient.invalidateQueries({ queryKey: ['judgment-lists'] }),
        queryClient.invalidateQueries({ queryKey: ['studies'] }),
        queryClient.invalidateQueries({ queryKey: ['proposals'] }),
      ]);
      setOpen(false);
    } catch (err) {
      // Distinguish three failure modes:
      //   1. Envelope failure with a real status (4xx/5xx) → show error
      //      code + runbook hint (SEED_FAILED, SEED_IN_PROGRESS, etc).
      //   2. Caller-aborted (180s client ceiling) → REQUEST_ABORTED
      //      envelope → unreachable toast.
      //   3. Raw network failure (apiClient wraps as ApiError with
      //      errorCode='SERVICE_UNAVAILABLE' and status=0) → unreachable
      //      toast — backend may still be running; refresh, don't retry.
      //      (Per GPT-5.5 final-review.)
      const isEnvelopeFailure =
        isApiError(err) &&
        err instanceof ApiError &&
        err.status > 0 &&
        err.errorCode !== 'REQUEST_ABORTED';
      if (isEnvelopeFailure) {
        toast.error(
          `Reseed failed: ${(err as ApiError).errorCode}. If this followed a hang or timeout, run \`docker compose restart api\` before retrying; otherwise see the demo-reseed runbook or run \`make seed-demo FORCE=1\` from the host.`,
        );
      } else {
        toast.error('Reseed in progress or unreachable — refresh the page in a moment.');
      }
    } finally {
      clearTimeout(timeoutId);
      setIsPending(false);
    }
  }

  return (
    <>
      <Button
        type="button"
        variant="secondary"
        onClick={() => setOpen(true)}
        data-testid="reset-demo-state-trigger"
      >
        Reset to demo state
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Wipe and reseed demo data?</AlertDialogTitle>
            <AlertDialogDescription>
              This will WIPE the dev Postgres demo state (clusters, studies, query sets, query
              templates, judgment lists, judgments, trials, digests, proposals) AND the
              corresponding ES/OS indices. Then it will seed 4 demo scenarios.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isPending} data-testid="reset-demo-state-cancel">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={isPending}
              onClick={handleConfirm}
              data-testid="reset-demo-state-confirm"
            >
              {isPending ? 'Resetting…' : 'Reset to demo state'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
