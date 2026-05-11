'use client';
import Link from 'next/link';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export interface CountCardProps {
  label: string;
  count: number | null;
  href?: string;
  testid?: string;
}

export function CountCard({ label, count, href, testid }: CountCardProps) {
  const body = (
    <Card data-testid={testid}>
      <CardHeader>
        <CardTitle className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-semibold tracking-tight">
          {count != null ? count.toLocaleString() : '—'}
        </p>
      </CardContent>
    </Card>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}
