// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { DemoBadge } from '@/components/common/demo-badge';
import { HelpPopover } from '@/components/common/help-popover';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { UbiRungBadge } from '@/components/clusters/ubi-rung-badge';
import { useDebouncedValue } from '@/hooks/use-debounced-value';
import type { ClusterDetail } from '@/lib/api/clusters';
import { useQuerySets } from '@/lib/api/query-sets';
import { useUbiReadiness } from '@/lib/api/ubi';
import { isDemoSyntheticUbiClusterName } from '@/lib/demo-data';
import { useQueryClient } from '@tanstack/react-query';

export interface ClusterDetailUbiReadinessCardProps {
  cluster: ClusterDetail;
}

// FR-2: full picker page size; FR-4: a separate length-2 probe drives the
// auto-seed predicate (rows.length === 1 && !has_more).
const PICKER_LIMIT = 50;
const AUTO_SEED_PROBE_LIMIT = 2;
const TARGET_MAX_LENGTH = 256; // matches backend cap (backend/app/api/v1/clusters.py).
const TARGET_DEBOUNCE_MS = 200;

/**
 * Cluster-detail UBI readiness card (chore_cluster_detail_rung_badge).
 *
 * Unconditionally mounted on `/clusters/[id]`. The operator picks a query set
 * + types a target index; the card calls `useUbiReadiness(...)` and renders the
 * `<UbiRungBadge>` (plus the synthetic-data chip on demo clusters). When the
 * cluster has exactly one query set AND a `target_filter` is set, the controls
 * auto-seed so the badge resolves on first visit without operator input.
 */
export function ClusterDetailUbiReadinessCard({
  cluster,
}: ClusterDetailUbiReadinessCardProps): React.ReactElement {
  const queryClient = useQueryClient();
  const [querySetId, setQuerySetId] = useState<string>('');
  const [targetRaw, setTargetRaw] = useState<string>('');

  // FR-2: picker list (separate cache key from the auto-seed probe per D-14).
  const pickerQuery = useQuerySets({ cluster_id: cluster.id, limit: PICKER_LIMIT });
  // FR-4: auto-seed proof (length-2 probe; distinct cache key).
  const autoSeedProbe = useQuerySets({ cluster_id: cluster.id, limit: AUTO_SEED_PROBE_LIMIT });
  const [didEvaluateAutoSeed, setDidEvaluateAutoSeed] = useState(false);

  // The auto-seed effect's whole job is to react to the probe's settled state
  // and seed the picker controls once. The `didEvaluateAutoSeed` one-shot
  // prevents cascading re-fires. Moving this out of useEffect would require
  // reading the async probe during render — not appropriate here. (Same
  // precedent as src/app/studies/page.tsx:56.)
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (didEvaluateAutoSeed) return;
    // D-4 / cycle-2 C-1: lock the decision on BOTH success and error so a
    // probe that errors then refetches successfully cannot trigger a delayed
    // auto-seed that overwrites operator-entered state (initial-mount only).
    if (autoSeedProbe.status === 'pending') return;

    if (autoSeedProbe.status === 'success') {
      const rows = autoSeedProbe.data.data;
      const hasMore = autoSeedProbe.data.has_more;
      const trimmedTargetFilter = (cluster.target_filter ?? '').trim();
      const shouldSeed = rows.length === 1 && !hasMore && trimmedTargetFilter.length > 0;
      if (shouldSeed && rows[0]) {
        setQuerySetId(rows[0].id);
        setTargetRaw(trimmedTargetFilter);
      }
    }
    // status === 'error' → lock without seeding.
    setDidEvaluateAutoSeed(true);
  }, [autoSeedProbe.status, autoSeedProbe.data, cluster.target_filter, didEvaluateAutoSeed]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // FR-3: debounce the free-form target before it reaches the readiness fetch.
  const target = useDebouncedValue(targetRaw, TARGET_DEBOUNCE_MS).trim();

  // FR-2 (cycle-1 B1): disable the readiness fetch while the picker list is
  // loading or errored — we have no valid query-set options to pair yet.
  const pickerReady = pickerQuery.status === 'success';
  const readinessQuery = useUbiReadiness(
    cluster.id,
    pickerReady ? querySetId || null : null,
    pickerReady ? target || null : null,
  );

  // D-16 dual leak gate: a stale badge must not render after the operator
  // clears either control. `targetRaw.trim()` is checked alongside the
  // debounced `target` so clearing the input hides the badge *immediately*
  // (spec interaction table) rather than after the 200ms debounce window.
  const pickerStateValid =
    pickerReady && querySetId !== '' && targetRaw.trim().length > 0 && target.length > 0;
  const showBadge = pickerStateValid && readinessQuery.data != null;
  const showSyntheticChip = isDemoSyntheticUbiClusterName(cluster.name);

  const renderBody = (): React.ReactElement => {
    if (pickerQuery.isPending) {
      return <p className="text-sm text-muted-foreground">Loading query sets…</p>;
    }
    if (pickerQuery.isError) {
      return (
        <div className="space-y-2 text-sm" data-testid="ubi-readiness-picker-error">
          <p className="text-muted-foreground">Couldn&apos;t load query sets.</p>
          <Button size="sm" variant="outline" onClick={() => pickerQuery.refetch()}>
            Retry
          </Button>
        </div>
      );
    }

    const rows = pickerQuery.data.data;
    if (rows.length === 0) {
      // FR-6 empty state. Creation is a modal on /query-sets (no /query-sets/new
      // route exists; verified at impl time per Story 2 Task 4).
      return (
        <p className="text-sm text-muted-foreground" data-testid="ubi-readiness-empty">
          Create a query set to check UBI readiness for this cluster.{' '}
          <Link
            className="text-blue-600 underline-offset-4 hover:underline"
            href="/query-sets"
            data-testid="ubi-readiness-create-query-set"
          >
            Create a query set →
          </Link>
        </p>
      );
    }

    return (
      <div className="space-y-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:gap-4">
          <div className="space-y-1 md:flex-1">
            <Label htmlFor="cluster-detail-ubi-query-set">Query set</Label>
            <Select value={querySetId} onValueChange={setQuerySetId}>
              <SelectTrigger
                id="cluster-detail-ubi-query-set"
                data-testid="cluster-detail-ubi-query-set-trigger"
              >
                <SelectValue placeholder="Select a query set" />
              </SelectTrigger>
              <SelectContent>
                {rows.map((row) => (
                  <SelectItem key={row.id} value={row.id}>
                    {row.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1 md:flex-1">
            <Label htmlFor="cluster-detail-ubi-target">Target</Label>
            <Input
              id="cluster-detail-ubi-target"
              data-testid="cluster-detail-ubi-target-input"
              maxLength={TARGET_MAX_LENGTH}
              value={targetRaw}
              onChange={(e) => setTargetRaw(e.target.value)}
              placeholder={cluster.target_filter ?? 'index or collection name'}
            />
          </div>
          {querySetId !== '' && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setQuerySetId('')}
              data-testid="cluster-detail-ubi-clear-query-set"
            >
              Clear
            </Button>
          )}
        </div>

        {/* FR-7: inline error (only unrecognized codes; the hook absorbs 404/503). */}
        {pickerStateValid && readinessQuery.isError && (
          <div className="space-y-2 text-sm" data-testid="ubi-readiness-error">
            <p className="text-muted-foreground">Couldn&apos;t load UBI readiness.</p>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                queryClient.invalidateQueries({
                  queryKey: ['ubi-readiness', cluster.id, querySetId, target],
                })
              }
            >
              Retry
            </Button>
          </div>
        )}

        {/* FR-7: first-fetch skeleton — gated on `data == null` so it never
            replaces a placeholderData-preserved badge during a target edit. */}
        {pickerStateValid && readinessQuery.isPending && readinessQuery.data == null && (
          <div
            className="h-5 w-32 animate-pulse rounded bg-muted"
            aria-label="Loading UBI readiness"
            data-testid="ubi-readiness-skeleton"
          />
        )}

        {showBadge && (
          <div
            className="flex flex-row items-center gap-2"
            data-testid="cluster-detail-ubi-result-row"
          >
            <UbiRungBadge rung={readinessQuery.data.rung} />
            {showSyntheticChip && <DemoBadge variant="synthetic-ubi" />}
            {readinessQuery.data.covered_pairs_pct === null &&
              readinessQuery.data.head_covered === null && (
                <span className="text-xs text-muted-foreground">
                  Couldn&apos;t refresh UBI status (cluster unreachable or query set missing).
                </span>
              )}
          </div>
        )}

        {pickerQuery.data.has_more && (
          <p className="text-xs text-muted-foreground">
            Showing first {PICKER_LIMIT} query sets.{' '}
            <Link className="text-blue-600 underline-offset-4 hover:underline" href="/query-sets">
              Browse all →
            </Link>
          </p>
        )}
      </div>
    );
  };

  return (
    <Card data-testid="cluster-detail-ubi-readiness-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <span>UBI readiness</span>
          <HelpPopover glossaryKey="cluster.ubi_readiness" />
        </CardTitle>
      </CardHeader>
      <CardContent>{renderBody()}</CardContent>
    </Card>
  );
}
