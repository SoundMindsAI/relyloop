'use client';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export interface SuggestedFollowupsPanelProps {
  followups: readonly string[];
}

export function SuggestedFollowupsPanel({ followups }: SuggestedFollowupsPanelProps) {
  if (followups.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Suggested follow-ups</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-3" data-testid="suggested-followups-list">
          {followups.map((f, i) => (
            <li key={`followup-${i}`} className="flex items-start gap-3">
              <span className="flex-1 text-sm">{f}</span>
              <Button asChild variant="outline" size="sm">
                <Link
                  href={`/studies?hypothesis=${encodeURIComponent(f)}`}
                  data-testid={`followup-${i}-create-study`}
                >
                  Create study from this hypothesis
                </Link>
              </Button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
