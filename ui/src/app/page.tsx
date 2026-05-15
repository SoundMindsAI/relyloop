'use client';
import { useQuery } from '@tanstack/react-query';

import { CountCard } from '@/components/dashboard/count-card';
import { RecentStudiesCards } from '@/components/dashboard/recent-studies-cards';
import { StartHereChecklist } from '@/components/dashboard/start-here-checklist';
import { EmptyState } from '@/components/common/empty-state';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { apiClient } from '@/lib/api-client';
import type { ClusterListResponse } from '@/lib/api/clusters';
import type { JudgmentListListResponse } from '@/lib/api/judgments';
import type { StudyListResponse } from '@/lib/api/studies';
import type { ProposalsListResponse } from '@/lib/api/proposals';

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

function sevenDaysAgoIso(): string {
  return new Date(Date.now() - SEVEN_DAYS_MS).toISOString();
}

export default function DashboardPage() {
  const recent = useQuery({
    queryKey: ['studies', { limit: 5 }, 'recent'],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<StudyListResponse>('/api/v1/studies', {
        params: { limit: 5 },
      });
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
  const openProposals = useQuery({
    queryKey: ['proposals', { status: 'pr_opened', limit: 1 }, 'count'],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<ProposalsListResponse>('/api/v1/proposals', {
        params: { status: 'pr_opened', limit: 1 },
      });
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
  const completedRecently = useQuery({
    queryKey: ['studies', { status: 'completed', since: 'last-7-days', limit: 1 }, 'count'],
    queryFn: async () => {
      const since = sevenDaysAgoIso();
      const { data, headers } = await apiClient.get<StudyListResponse>('/api/v1/studies', {
        params: { status: 'completed', since, limit: 1 },
      });
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });

  // First-run-state signals for the StartHereChecklist (Phase 3 of feat_contextual_help_mvp2).
  // Each query asks for `limit=1` because we only need the totalCount header to know
  // whether the resource exists at all.
  const clustersCount = useQuery({
    queryKey: ['clusters', { limit: 1 }, 'first-run-count'],
    queryFn: async () => {
      const { headers } = await apiClient.get<ClusterListResponse>('/api/v1/clusters', {
        params: { limit: 1 },
      });
      return Number(headers.get('X-Total-Count') ?? 0);
    },
  });
  const judgmentListsCount = useQuery({
    queryKey: ['judgment-lists', { limit: 1 }, 'first-run-count'],
    queryFn: async () => {
      const { headers } = await apiClient.get<JudgmentListListResponse>('/api/v1/judgment-lists', {
        params: { limit: 1 },
      });
      return Number(headers.get('X-Total-Count') ?? 0);
    },
  });

  const allFailed = recent.isError && openProposals.isError && completedRecently.isError;

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Recent activity across studies, proposals, and judgments.
        </p>
      </div>
      {allFailed ? (
        <EmptyState
          title="Backend unreachable"
          message="Check `make logs` and confirm the API container is healthy."
        />
      ) : (
        <>
          {/*
           * StartHereChecklist renders only on the first-run state (no clusters
           * OR no judgment-list OR no studies). Returns null once all three
           * are non-empty, so it disappears as soon as the user has a working
           * setup. The component handles its own "all done → hide" logic.
           */}
          {clustersCount.isSuccess && judgmentListsCount.isSuccess && recent.isSuccess && (
            <StartHereChecklist
              hasClusters={clustersCount.data > 0}
              hasQuerySetsWithJudgments={judgmentListsCount.data > 0}
              hasStudies={(recent.data?.totalCount ?? 0) > 0}
            />
          )}
          <section className="grid gap-3 sm:grid-cols-2">
            <CountCard
              label="Open proposals"
              count={openProposals.isError ? null : (openProposals.data?.totalCount ?? null)}
              href="/proposals"
              testid="card-open-proposals"
            />
            <CountCard
              label="Studies completed (last 7 days)"
              count={
                completedRecently.isError ? null : (completedRecently.data?.totalCount ?? null)
              }
              href="/studies?status=completed"
              testid="card-completed-recent"
            />
          </section>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Recent studies</CardTitle>
            </CardHeader>
            <CardContent>
              {recent.isPending ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : recent.isError ? (
                <p className="text-sm text-destructive">Could not load recent studies.</p>
              ) : (
                <RecentStudiesCards rows={recent.data?.data ?? []} />
              )}
            </CardContent>
          </Card>
        </>
      )}
    </main>
  );
}
