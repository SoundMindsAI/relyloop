import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { TemplateBodyEditor } from '@/components/templates/template-body-editor';

describe('TemplateBodyEditor', () => {
  it('renders prism-highlighted tokens for the provided body', () => {
    const body = '{ "query": { "match": { "title": "{{ q }}" } } }';
    render(<TemplateBodyEditor value={body} readOnly />);
    const overlay = screen.getByTestId('template-body-highlight');
    // Prism wraps tokens in <span class="token ..."> children; assert at least one is present.
    expect(overlay.querySelector('span.token')).not.toBeNull();
  });

  it('calls onChange when the textarea is edited', () => {
    const onChange = vi.fn();
    render(<TemplateBodyEditor value="initial" onChange={onChange} />);
    const ta = screen.getByTestId('template-body-textarea') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'updated' } });
    expect(onChange).toHaveBeenCalledWith('updated');
  });

  it('honours readOnly', () => {
    render(<TemplateBodyEditor value="locked" readOnly />);
    const ta = screen.getByTestId('template-body-textarea') as HTMLTextAreaElement;
    expect(ta.readOnly).toBe(true);
  });
});
