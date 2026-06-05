// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { Suspense, use } from 'react';

import { StudyComparisonPage } from '@/components/studies/study-comparison-page';

interface CompareRouteProps {
  searchParams: Promise<{ a?: string; b?: string }>;
}

export default function StudyComparePage({ searchParams }: CompareRouteProps) {
  const { a, b } = use(searchParams);
  return (
    <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading comparison…</main>}>
      <StudyComparisonPage a={a} b={b} />
    </Suspense>
  );
}
