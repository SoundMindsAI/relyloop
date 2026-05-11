'use client';
import { useQuery } from '@tanstack/react-query';

import { CountCard } from '@/components/dashboard/count-card';
import { RecentStudiesCards } from '@/components/dashboard/recent-studies-cards';
import { EmptyState } from '@/components/common/empty-state';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { apiClient } from '@/lib/api-client';
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
