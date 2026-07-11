// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect } from 'react';

const SUFFIX = 'RelyLoop';

/**
 * Set the document title to `<title> · RelyLoop` for the lifetime of the
 * component, restoring the previous title on unmount. Every route page is a
 * client component (no server `metadata` export), so this is how tabs, history
 * entries, and bookmarks get descriptive names instead of a bare "RelyLoop".
 *
 * Pass `null`/`undefined` (e.g. while a detail entity is still loading) to
 * leave the title untouched until the real name is known.
 */
export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    if (title == null || title === '') return;
    const previous = document.title;
    document.title = `${title} · ${SUFFIX}`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
