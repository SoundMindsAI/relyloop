'use client';
import { useClusters } from '@/lib/api/clusters';

export interface ClusterFilterSelectProps {
  value: string | null;
  onChange: (clusterId: string | null) => void;
}

export function ClusterFilterSelect({ value, onChange }: ClusterFilterSelectProps) {
  // MVP1: <10 clusters per installer; limit=200 is conservative. The
  // chore_cluster_filter_full_list idea file captures the full-list paging
  // follow-up when this assumption no longer holds.
  const clustersQ = useClusters({ limit: 200 });
  const isLoading = clustersQ.isPending;
  const clusters = clustersQ.data?.data ?? [];
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="cluster-filter" className="text-sm">
        Cluster
      </label>
      <select
        id="cluster-filter"
        className="rounded-md border border-gray-200 bg-white px-2 py-1 text-sm"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={isLoading}
        data-testid="cluster-filter-select"
      >
        <option value="">{isLoading ? '(loading…)' : 'All clusters'}</option>
        {clusters.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
    </div>
  );
}
