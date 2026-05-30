// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import { notFound, useParams } from 'next/navigation';

import { MarkdownDoc } from '@/components/guides/markdown-doc';
import { DOC_REGISTRY } from '@/components/guides/guide-types';

export default function DocPage() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug;
  const doc = DOC_REGISTRY.find((d) => d.slug === slug);
  if (!doc) {
    notFound();
  }

  return (
    <main className="min-h-screen">
      <div className="border-b bg-muted/30">
        <div className="mx-auto max-w-5xl px-4 py-3 sm:px-6">
          <Link
            href="/guide"
            className="text-sm text-blue-600 underline-offset-4 hover:underline"
            data-testid="back-to-guides"
          >
            ← All guides
          </Link>
        </div>
      </div>
      <MarkdownDoc file={doc.file} title={doc.title} />
    </main>
  );
}
