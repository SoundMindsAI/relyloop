import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { ConversationList } from '@/components/chat/conversation-list';
import type { ConversationSummary } from '@/lib/api/conversations';

const BASE_ROW: ConversationSummary = {
  id: 'c1',
  title: 'tune product_search',
  created_at: '2026-05-12T00:00:00Z',
  message_count: 4,
  last_message_preview: 'latest user follow-up',
  last_message_at: '2026-05-12T00:05:00Z',
};

describe('ConversationList', () => {
  it('renders the preview line under the title when last_message_preview is present', () => {
    render(<ConversationList rows={[BASE_ROW]} />);
    const row = screen.getByTestId('conversation-row');
    expect(within(row).getByTestId('conversation-preview')).toHaveTextContent(
      'latest user follow-up',
    );
  });

  it('omits the preview line entirely when last_message_preview is null', () => {
    const empty: ConversationSummary = {
      ...BASE_ROW,
      id: 'c-empty',
      message_count: 0,
      last_message_preview: null,
      last_message_at: null,
    };
    render(<ConversationList rows={[empty]} />);
    expect(screen.queryByTestId('conversation-preview')).toBeNull();
  });

  it('displays last_message_at as the timestamp when present', () => {
    render(<ConversationList rows={[BASE_ROW]} />);
    const ts = screen.getByTestId('conversation-timestamp');
    // toLocaleString output varies by locale; assert it parses to the last_at
    // moment, not created_at. Cheap check: the text matches whatever
    // toLocaleString returns for last_message_at.
    expect(ts).toHaveTextContent(new Date(BASE_ROW.last_message_at as string).toLocaleString());
  });

  it('falls back to created_at when last_message_at is null', () => {
    const empty: ConversationSummary = {
      ...BASE_ROW,
      id: 'c-empty',
      message_count: 0,
      last_message_preview: null,
      last_message_at: null,
    };
    render(<ConversationList rows={[empty]} />);
    const ts = screen.getByTestId('conversation-timestamp');
    expect(ts).toHaveTextContent(new Date(empty.created_at).toLocaleString());
  });

  it('still renders the message count line in all cases', () => {
    render(
      <ConversationList
        rows={[
          BASE_ROW,
          {
            ...BASE_ROW,
            id: 'c-empty',
            message_count: 0,
            last_message_preview: null,
            last_message_at: null,
          },
        ]}
      />,
    );
    // The non-empty row shows "4 messages"; the empty row shows "Empty".
    expect(screen.getByText('4 messages')).toBeInTheDocument();
    expect(screen.getByText('Empty')).toBeInTheDocument();
  });
});
