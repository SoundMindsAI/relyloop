'use client';
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { useState } from 'react';
import { toast } from 'sonner';

import { isApiError, toToastMessage } from '@/lib/api-errors';

/**
 * Global error-toast wiring (FR-10):
 *   - `meta.suppressErrorCodes: ["X", "Y"]` on a query/mutation skips toasting
 *     when the thrown ApiError's `errorCode` is in the list (used by
 *     useStudyDigest for DIGEST_NOT_READY).
 *   - `meta.suppressGlobalErrorToast: true` skips toasting entirely for that
 *     query/mutation (used when the caller handles error display inline).
 *   - Modal mutation callers do NOT add their own `onError: toast.error(...)`
 *     — they let the global handler toast and use their `onError` only to
 *     control modal lifecycle (e.g., keep open on error).
 */
function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, refetchOnWindowFocus: true },
    },
    queryCache: new QueryCache({
      onError: (err, query) => {
        if (!isApiError(err)) {
          toast.error('Unknown error');
          return;
        }
        const suppress = (query.meta?.suppressErrorCodes as string[] | undefined) ?? [];
        if (suppress.includes(err.errorCode)) return;
        if (query.meta?.suppressGlobalErrorToast) return;
        toast.error(toToastMessage(err));
      },
    }),
    mutationCache: new MutationCache({
      onError: (err, _vars, _ctx, mutation) => {
        if (!isApiError(err)) {
          toast.error('Unknown error');
          return;
        }
        if (mutation.meta?.suppressGlobalErrorToast) return;
        toast.error(toToastMessage(err));
      },
    }),
  });
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  // Recreate the client per component instance so test environments get fresh state.
  const [client] = useState(() => createQueryClient());
  return (
    <QueryClientProvider client={client}>
      {children}
      {process.env.NODE_ENV === 'development' && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  );
}
