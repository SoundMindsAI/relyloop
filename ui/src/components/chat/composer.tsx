'use client';

import { useState, type KeyboardEvent } from 'react';

import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

export interface ComposerProps {
  onSend: (text: string) => void | Promise<void>;
  streaming: boolean;
}

export function Composer({ onSend, streaming }: ComposerProps) {
  const [input, setInput] = useState('');

  const submit = () => {
    const value = input.trim();
    if (!value || streaming) return;
    setInput('');
    void onSend(value);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className="flex items-end gap-2" data-testid="composer">
      <Textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask the agent. Cmd+Enter to send."
        rows={3}
        className="min-h-[60px] flex-1 resize-y"
        data-testid="composer-input"
        disabled={streaming}
      />
      <Button
        type="button"
        onClick={submit}
        disabled={streaming || !input.trim()}
        data-testid="composer-send"
      >
        {streaming ? 'Sending…' : 'Send'}
      </Button>
    </div>
  );
}
