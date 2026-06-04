// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { Suspense, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { CreateStudyModal, type PrefillValues } from '@/components/studies/create-study-modal';
import { buildPrefillFromStudy } from '@/components/studies/prefill-from-study';
import { RecentChainsCard } from '@/components/studies/recent-chains-card';
import { StudiesTable } from '@/components/studies/studies-table';
import { studiesColumns } from '@/components/studies/studies-table.column-config';
import { useDataTableUrlState } from '@/hooks/use-data-table-url-state';
import { useStudies, useStudy } from '@/lib/api/studies';

function StudiesPageInner() {
  const urlState = useDataTableUrlState('studies', studiesColumns, { defaultPageSize: 50 });
  const router = useRouter();
  const searchParams = useSearchParams();
  const [createOpen, setCreateOpen] = useState(false);
  // feat_study_clone_from_previous Story 2.3 — deep-link state for
  // ``/studies?clone_from=<source_id>``. One-shot via useRef so the
  // effect can set cloneInitialValues without depending on it (avoids
  // the stale-closure shape that would re-fire mid-render).
  const [cloneInitialValues, setCloneInitialValues] = useState<PrefillValues | null>(null);
  const cloneEffectFired = useRef(false);

  // FR-4 / D-11: distinguish presence (?clone_from=…) from absence
  // (no key). A trimmed empty value is treated the same as garbage —
  // toast + open empty modal. A 36-char UUID is the only valid shape.
  const hasCloneFrom = searchParams.has('clone_from');
  const cloneFromId = searchParams.get('clone_from')?.trim() || null;
  const cloneFromValid = cloneFromId !== null && cloneFromId.length === 36;
  const cloneSource = useStudy(cloneFromId ?? '', { enabled: cloneFromValid });

  // Re-arm the one-shot when the source id changes. Covers the
  // in-app navigation case where the user goes from
  // `?clone_from=A` to `?clone_from=B` without closing the modal —
  // without this reset, the previous A-fire would block the B-fire
  // (Gemini PR #243 review finding #1). Fires on every cloneFromId
  // change including the post-fire `router.replace('/studies')` that
  // sets cloneFromId back to null; that re-set is harmless because
  // the main effect's `if (!hasCloneFrom) return` short-circuits.
  useEffect(() => {
    cloneEffectFired.current = false;
  }, [cloneFromId]);

  // The deep-link reader's whole job is to react to URL + source-fetch
  // state and seed the modal's local state. The useRef one-shot prevents
  // cascading re-fires. Moving this logic out of useEffect would require
  // running fetches during render — not appropriate here.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!hasCloneFrom) return;
    if (cloneEffectFired.current) return;
    if (!cloneFromValid) {
      cloneEffectFired.current = true;
      setCloneInitialValues(null);
      toast.error('Invalid clone-from id — opening empty create form');
      router.replace('/studies');
      setCreateOpen(true);
      return;
    }
    if (cloneSource.isError) {
      cloneEffectFired.current = true;
      setCloneInitialValues(null);
      toast.error(`Source study ${cloneFromId} not found — opening empty create form`);
      router.replace('/studies');
      setCreateOpen(true);
      return;
    }
    if (cloneSource.data) {
      cloneEffectFired.current = true;
      setCloneInitialValues(buildPrefillFromStudy(cloneSource.data));
      setCreateOpen(true);
      router.replace('/studies');
    }
    // Dependencies: presence + validity + id + fetch state.
    // cloneInitialValues intentionally omitted — guarded by useRef one-shot.
  }, [hasCloneFrom, cloneFromValid, cloneFromId, cloneSource.data, cloneSource.isError, router]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // feat_index_document_browser FR-5 — ?target= filter chip.
  // The URL is the single source of truth for filter state (matches the
  // ?cluster_id= pattern from feat_cluster_target_filter). Clicking × on
  // the chip drops the param from the URL; the query refetches on the
  // next render.
  const targetFromUrl = searchParams.get('target');
  const clusterIdFromUrl = searchParams.get('cluster_id');

  function clearTargetFilter() {
    const params = new URLSearchParams(searchParams.toString());
    params.delete('target');
    const qs = params.toString();
    router.replace(qs ? `/studies?${qs}` : '/studies');
  }

  const query = useStudies({
    status: urlState.filters['status'],
    cluster_id: clusterIdFromUrl ?? undefined,
    target: targetFromUrl ?? undefined,
    sort: urlState.sort ?? undefined,
    q: urlState.q ?? undefined,
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
  });

  const rows = query.data?.data ?? [];

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Studies</h1>
        <Button onClick={() => setCreateOpen(true)} data-testid="open-create-study">
          Create study
        </Button>
      </div>
      {/*
        feat_overnight_studies_summary_card Story 2.2 — "Ran while you
        were away" card. Self-contained (owns its own data + visited-
        state); early-returns null on empty / error / pending so the
        studies table below always renders predictably.
      */}
      <RecentChainsCard />
      {targetFromUrl && (
        <div className="flex items-center gap-2 text-sm" data-testid="studies-active-filters">
          <span className="text-muted-foreground">Active filters:</span>
          <span
            className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-xs"
            data-testid="studies-target-filter-chip"
          >
            Target: <span className="font-mono">{targetFromUrl}</span>
            <button
              type="button"
              onClick={clearTargetFilter}
              className="ml-1 text-muted-foreground hover:text-foreground"
              aria-label="Clear target filter"
              data-testid="studies-target-filter-clear"
            >
              ×
            </button>
          </span>
        </div>
      )}
      <Card>
        <CardContent className="pt-6">
          <StudiesTable
            rows={rows}
            totalCount={query.data?.totalCount}
            has_more={query.data?.has_more ?? false}
            next_cursor={query.data?.next_cursor ?? null}
            isLoading={query.isPending}
            isError={query.isError}
            urlState={urlState}
          />
        </CardContent>
      </Card>
      <CreateStudyModal
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
          if (!open) {
            // Clear prefill on close so the next "Create study" click
            // opens a fresh modal; re-arm the one-shot so subsequent
            // ?clone_from=… links in the same session still fire.
            setCloneInitialValues(null);
            cloneEffectFired.current = false;
          }
        }}
        initialValues={cloneInitialValues ?? undefined}
      />
    </main>
  );
}

export default function StudiesPage() {
  // `useSearchParams` must live under a `<Suspense>` boundary in Next 16 App Router.
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
      <StudiesPageInner />
    </Suspense>
  );
}
