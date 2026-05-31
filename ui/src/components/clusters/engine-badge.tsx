// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// EngineBadge — small icon + label for ES / OpenSearch / Solr clusters
// (infra_adapter_solr Story A11).
//
// Renders a per-engine inline SVG mark plus the human-friendly engine name.
// For Solr clusters the tooltip surfaces the deployment mode (cloud /
// standalone) recorded by the capability probe.
//
// Values must match backend/app/api/v1/schemas.py EngineTypeWire

import type { FC } from 'react';
import type { EngineType } from '@/lib/enums';

interface IconProps {
  className?: string;
}

const ElasticsearchMark: FC<IconProps> = ({ className }) => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    className={className}
  >
    <path d="M3 7c4-1 14-1 18 0M3 12h18M3 17c4 1 14 1 18 0" strokeLinecap="round" />
  </svg>
);

const OpenSearchMark: FC<IconProps> = ({ className }) => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    className={className}
  >
    <circle cx="12" cy="12" r="6" />
    <path d="M16 8l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const SolrMark: FC<IconProps> = ({ className }) => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    className={className}
  >
    <path
      d="M12 3l9 5-9 5-9-5 9-5zm-9 9l9 5 9-5M3 17l9 5 9-5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const ENGINE_META: Record<EngineType, { label: string; Icon: FC<IconProps> }> = {
  elasticsearch: { label: 'Elasticsearch', Icon: ElasticsearchMark },
  opensearch: { label: 'OpenSearch', Icon: OpenSearchMark },
  solr: { label: 'Apache Solr', Icon: SolrMark },
};

export interface EngineBadgeProps {
  engine: EngineType;
  /** Solr deployment mode populated by the capability probe (engine_config.mode). */
  mode?: 'cloud' | 'standalone';
  /** Engine version string from health_check / probe. */
  version?: string | null;
  className?: string;
}

export function EngineBadge({
  engine,
  mode,
  version,
  className,
}: EngineBadgeProps): React.ReactElement {
  const { label, Icon } = ENGINE_META[engine];
  const tipParts = [label];
  if (version) tipParts.push(version);
  if (engine === 'solr' && mode) tipParts.push(`(${mode})`);
  const tip = tipParts.join(' ');
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${className ?? ''}`.trim()}
      title={tip}
      aria-label={`${label} engine`}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="text-sm">{label}</span>
    </span>
  );
}

export const ENGINE_LABELS: Record<EngineType, string> = Object.fromEntries(
  (Object.entries(ENGINE_META) as Array<[EngineType, { label: string }]>).map(([k, v]) => [
    k,
    v.label,
  ]),
) as Record<EngineType, string>;
