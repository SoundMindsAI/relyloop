import { describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';

import { QueryProvider } from '@/components/providers/query-provider';
import { Toaster } from '@/components/ui/sonner';

function QueryConsumer() {
  const q = useQuery({
    queryKey: ['test'],
    queryFn: async () => 42,
  });
  return <div data-testid="value">{q.data ?? 'pending'}</div>;
}

describe('QueryProvider', () => {
  it('provides a QueryClient to child consumers (useQuery does not throw)', async () => {
    render(
      <QueryProvider>
        <QueryConsumer />
      </QueryProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId('value')).toHaveTextContent('42');
    });
  });

  it('mounts the Toaster so toast.error renders into the DOM', async () => {
    function ToastTrigger() {
      return (
        <button type="button" onClick={() => toast.error('boom')} data-testid="trigger">
          fire
        </button>
      );
    }
    render(
      <QueryProvider>
        <Toaster />
        <ToastTrigger />
      </QueryProvider>,
    );
    screen.getByTestId('trigger').click();
    await waitFor(() => {
      // sonner renders inside a section[aria-label*=Notifications]. Look for the text.
      expect(screen.getByText('boom')).toBeInTheDocument();
    });
  });
});
