// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
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
import { Label } from '@/components/ui/label';
import { useDemoEnginesCapability } from '@/lib/api/demo-engines';
import {
  postDemoReseed,
  useDemoReseedStatus,
  type ReseedStatusResponse,
} from '@/lib/api/demo-reseed';
import { ApiError, isApiError } from '@/lib/api-errors';
import { ENGINE_TYPE_VALUES, type EngineType } from '@/lib/enums';

/** Human-friendly engine names used in the reset-modal checkbox labels.
 * Wire values live in ENGINE_TYPE_VALUES (sourced from
 * backend/app/api/v1/schemas.py EngineTypeWire — see ui/src/lib/enums.ts).
 * Labels diverge intentionally per spec §7.4 ("Labels shown to the user
 * may differ from the wire value"). */
const ENGINE_DISPLAY_LABELS: Record<EngineType, string> = {
  elasticsearch: 'Elasticsearch',
  opensearch: 'OpenSearch',
  solr: 'Apache Solr',
};

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
  // feat_selective_engine_startup_and_demo Story 3.1 / FR-8.
  //
  // ``userSelection`` tracks the operator's checkbox interactions:
  //   - null → operator hasn't toggled anything; the resolved view derives
  //            from the capability response (defaults to all reachable
  //            engines per AC-10).
  //   - Set  → user-controlled. Even an empty Set is honored so the AC-11
  //            "Confirm disabled when nothing selected" path works.
  // The dialog's onOpenChange resets this to null on close so a re-open
  // re-seeds from the next capability fetch — no useEffect needed.
  const [userSelection, setUserSelection] = useState<Set<EngineType> | null>(null);
  const enginesQuery = useDemoEnginesCapability({ enabled: open });
  const queryClient = useQueryClient();
  const statusQuery = useDemoReseedStatus({ enabled: pollingEnabled });
  const status: ReseedStatusResponse | undefined = statusQuery.data;
  const isRunning = status?.status === 'running';
  const isTerminal = status?.status === 'complete' || status?.status === 'failed';

  // Derived view consumed by the checkbox group, Confirm-gate, and POST
  // dispatch. When the operator has interacted (``userSelection`` is a
  // Set, even an empty one) we use that verbatim — empty means the
  // Confirm button is disabled and `hasUserCleared` will be true. When
  // the operator hasn't touched anything, default to "all reachable
  // engines" per AC-10. Capability fetch failure → fall back to all
  // three so the operator can still trigger a reseed; the orchestrator's
  // reachability gate handles unreachable engines downstream.
  const effectiveSelectedEngines = useMemo<Set<EngineType>>(() => {
    if (userSelection !== null) return userSelection;
    const data = enginesQuery.data;
    if (data != null) {
      const reachable = data.engines.filter((e) => e.reachable).map((e) => e.engine_type);
      return new Set(reachable.length > 0 ? reachable : ENGINE_TYPE_VALUES);
    }
    if (enginesQuery.error != null) return new Set(ENGINE_TYPE_VALUES);
    return new Set();
  }, [userSelection, enginesQuery.data, enginesQuery.error]);

  // Tracks the AC-11 "operator unchecked everything" case so the Confirm
  // button + hint render distinctly from the pre-capability-load empty
  // state (which is transient and shouldn't show the hint).
  const hasUserCleared = userSelection !== null && userSelection.size === 0;

  async function startReseed(event: React.MouseEvent): Promise<void> {
    // Keep the dialog open so the progress card replaces the "are you sure"
    // copy.
    event.preventDefault();
    if (effectiveSelectedEngines.size === 0) return; // belt-and-suspenders; button disabled
    setPollingEnabled(true);
    try {
      // Pass null when the operator implicitly selected "all three" so the
      // backend takes the back-compat "all reachable engines" path without
      // recording user_excluded reasons (cosmetic — same behavior either
      // way, but it keeps the partial-completion footer cleaner).
      const allSelected = effectiveSelectedEngines.size === ENGINE_TYPE_VALUES.length;
      const enginesPayload = allSelected ? null : Array.from(effectiveSelectedEngines);
      await postDemoReseed(enginesPayload);
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

  function toggleEngine(engine: EngineType, next: boolean): void {
    // First user interaction must promote null → Set; subsequent toggles
    // mutate the existing Set. Read the CURRENT effective view (which
    // returns the seeded default when userSelection is still null) so
    // unchecking starts from the right baseline.
    setUserSelection((prev) => {
      const base = prev ?? effectiveSelectedEngines;
      const copy = new Set(base);
      if (next) copy.add(engine);
      else copy.delete(engine);
      return copy;
    });
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
      <AlertDialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          // Reset the operator's checkbox interactions on close so the
          // next re-open starts from a fresh capability-derived default
          // (and the "user has cleared everything" hint doesn't linger
          // from a prior session). Setting state from an event handler
          // is the cheap fix that keeps react-hooks/set-state-in-effect
          // green — no useEffect needed.
          if (!next) setUserSelection(null);
        }}
      >
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
            {/* feat_selective_engine_startup_and_demo Story 3.1 / FR-8 — pick
                which engines to reseed. Renders only in the pre-confirm state;
                the capability fetch only fires once the dialog opens
                (enabled: open in useDemoEnginesCapability). */}
            {!isRunning && !isTerminal && (
              <div className="space-y-2 pt-2" data-testid="reset-demo-state-engines">
                <div className="text-sm font-medium">Engines to reseed</div>
                <p className="text-xs text-muted-foreground">
                  Defaults to all running engines. Unreachable engines are shown disabled.
                </p>
                {enginesQuery.data == null && enginesQuery.error != null && (
                  <p
                    className="text-xs italic text-muted-foreground"
                    data-testid="reset-demo-engines-fallback"
                  >
                    Couldn&apos;t probe engines — continuing as if all are reachable.
                  </p>
                )}
                <div className="space-y-1.5">
                  {ENGINE_TYPE_VALUES.map((engineType) => {
                    const probeRow = enginesQuery.data?.engines.find(
                      (e) => e.engine_type === engineType,
                    );
                    // Fallback: when the capability fetch failed (404 / network)
                    // treat every engine as reachable so the operator can still
                    // trigger a reseed; the orchestrator's reachability gate
                    // handles unreachable engines downstream.
                    const reachable = probeRow?.reachable ?? enginesQuery.data == null;
                    const disabled = !reachable;
                    const checked = effectiveSelectedEngines.has(engineType);
                    const id = `engine-${engineType}`;
                    return (
                      <div key={engineType} className="flex items-center gap-2">
                        <input
                          id={id}
                          type="checkbox"
                          checked={checked}
                          disabled={disabled}
                          aria-disabled={disabled ? 'true' : undefined}
                          onChange={(ev) => toggleEngine(engineType, ev.target.checked)}
                          className="h-4 w-4 rounded border-input"
                          data-testid={`engine-checkbox-${engineType}`}
                        />
                        <Label htmlFor={id} className={disabled ? 'text-muted-foreground' : ''}>
                          {/* eslint-disable-next-line security/detect-object-injection -- engineType is a typed EngineType (Literal) from ENGINE_TYPE_VALUES, never operator input */}
                          {ENGINE_DISPLAY_LABELS[engineType]}
                          {disabled && (
                            <span className="ml-1 text-xs italic text-muted-foreground">
                              (unreachable)
                            </span>
                          )}
                        </Label>
                      </div>
                    );
                  })}
                </div>
                {hasUserCleared && (
                  <p
                    className="text-xs text-destructive"
                    data-testid="reset-demo-engines-empty-hint"
                  >
                    Select at least one engine to reseed.
                  </p>
                )}
              </div>
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
            {isTerminal && status?.status === 'complete' && status.scenarios_skipped.length > 0 && (
              <AlertDialogDescription asChild>
                <p
                  className="text-xs italic text-muted-foreground"
                  data-testid="reset-demo-state-partial"
                >
                  {/* "scenario(s)", not "engine(s)": scenarios_skipped is
                      slug-keyed, and one down engine (e.g. ES) can skip several
                      scenario slugs. GPT-5.5 PR #367 final review. */}
                  Partial completion — {status.scenarios_skipped.length} scenario
                  {status.scenarios_skipped.length === 1 ? '' : 's'} skipped:{' '}
                  {status.scenarios_skipped.join(', ')}.{' '}
                  <a
                    href="https://github.com/SoundMindsAI/relyloop/blob/main/docs/03_runbooks/demo-reseed-engine-tolerance.md"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline"
                  >
                    Why?
                  </a>
                </p>
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
                <AlertDialogAction
                  onClick={startReseed}
                  disabled={hasUserCleared}
                  data-testid="reset-demo-state-confirm"
                >
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
