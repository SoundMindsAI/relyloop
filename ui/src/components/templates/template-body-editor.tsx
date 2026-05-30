// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { Highlight, themes } from 'prism-react-renderer';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { prettyPrintJinjaJson } from '@/lib/jinja-json-format';
import { cn } from '@/lib/utils';

export interface TemplateBodyEditorProps {
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  rows?: number;
  className?: string;
  /** Test hook so RHF + tests can target the textarea. */
  name?: string;
}

/**
 * Jinja2-flavored highlight using Prism's `jsx` token set (closest fit;
 * Prism does not ship a Jinja2 language). The textarea sits on top of the
 * highlighted overlay with `bg-transparent text-transparent caret-foreground`
 * so keystrokes still work and selection is visible.
 */
export function TemplateBodyEditor({
  value,
  onChange,
  readOnly = false,
  rows = 16,
  className,
  name,
}: TemplateBodyEditorProps) {
  // ReadOnly callers don't pass `onChange`, so Format updates an internal
  // override that takes precedence over `value`. Editable callers receive
  // the formatted text via `onChange` and we never set localValue.
  const [localValue, setLocalValue] = useState<string | null>(null);
  const effectiveValue = localValue ?? value;
  const isFormatted = localValue !== null;

  function handleFormat() {
    const result = prettyPrintJinjaJson(effectiveValue);
    if (!result.ok) {
      toast.error(`Couldn't format: ${result.error}`);
      return;
    }
    if (onChange) {
      onChange(result.text);
    } else {
      setLocalValue(result.text);
    }
  }

  function handleShowOriginal() {
    setLocalValue(null);
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-end gap-2">
        {readOnly && isFormatted && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={handleShowOriginal}
            data-testid="template-body-show-original"
          >
            Show original
          </Button>
        )}
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleFormat}
          data-testid="template-body-format"
        >
          Pretty-print JSON
        </Button>
      </div>
      <div
        className={cn(
          'relative overflow-hidden rounded-md border border-input font-mono text-sm',
          className,
        )}
        data-testid="template-body-editor"
      >
        <Highlight code={effectiveValue || ' '} language="jsx" theme={themes.github}>
          {({ tokens, getLineProps, getTokenProps }) => (
            <pre
              aria-hidden
              className="pointer-events-none m-0 min-h-[16em] whitespace-pre-wrap break-words p-3"
              data-testid="template-body-highlight"
            >
              {tokens.map((line, i) => {
                const lineProps = getLineProps({ line });
                return (
                  <div key={`line-${i}`} {...lineProps}>
                    {line.map((token, ti) => {
                      const tokenProps = getTokenProps({ token });
                      return <span key={`token-${i}-${ti}`} {...tokenProps} />;
                    })}
                  </div>
                );
              })}
            </pre>
          )}
        </Highlight>
        <Textarea
          name={name}
          value={effectiveValue}
          readOnly={readOnly}
          rows={rows}
          spellCheck={false}
          onChange={(e) => {
            // Editing wipes any local format override — the caller's value
            // is authoritative once the user starts typing.
            if (localValue !== null) setLocalValue(null);
            onChange?.(e.target.value);
          }}
          className="absolute inset-0 h-full min-h-[16em] resize-none border-0 bg-transparent p-3 text-transparent caret-black focus-visible:ring-0"
          data-testid="template-body-textarea"
        />
      </div>
    </div>
  );
}
