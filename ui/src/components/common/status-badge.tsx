import { Badge, type BadgeProps } from '@/components/ui/badge';

type BadgeVariant = NonNullable<BadgeProps['variant']>;

/** Maps (kind, value) → shadcn Badge variant per Story 1.3 color table. */
const VARIANT_TABLE: Record<string, Record<string, BadgeVariant>> = {
  study: {
    queued: 'secondary',
    running: 'default',
    completed: 'success',
    cancelled: 'outline',
    failed: 'destructive',
  },
  trial: {
    complete: 'success',
    pruned: 'secondary',
    failed: 'destructive',
  },
  proposal: {
    pending: 'secondary',
    pr_opened: 'default',
    pr_merged: 'success',
    rejected: 'outline',
  },
  proposal_pr: {
    open: 'default',
    closed: 'outline',
    merged: 'success',
  },
  judgment_list: {
    generating: 'default',
    complete: 'success',
    failed: 'destructive',
  },
  health: {
    green: 'success',
    yellow: 'warning',
    red: 'destructive',
    unreachable: 'secondary',
  },
};

export type StatusBadgeKind = keyof typeof VARIANT_TABLE;

export interface StatusBadgeProps {
  kind: StatusBadgeKind;
  value: string;
  className?: string;
}

export function StatusBadge({ kind, value, className }: StatusBadgeProps) {
  // `kind` is typed as StatusBadgeKind (typescript-enforced); `value` is a wire string
  // we explicitly chain-default to 'secondary' on miss. The eslint security plugin
  // can't see the TypeScript type narrowing — suppress with cited safety argument.
  // eslint-disable-next-line security/detect-object-injection
  const variant = VARIANT_TABLE[kind]?.[value] ?? 'secondary';
  return (
    <Badge variant={variant} className={className} data-kind={kind} data-value={value}>
      {value}
    </Badge>
  );
}
