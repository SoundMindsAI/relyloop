'use client';
import { Highlight, themes } from 'prism-react-renderer';

import { Textarea } from '@/components/ui/textarea';
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
  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-md border border-input font-mono text-sm',
        className,
      )}
      data-testid="template-body-editor"
    >
      <Highlight code={value || ' '} language="jsx" theme={themes.github}>
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
        value={value}
        readOnly={readOnly}
        rows={rows}
        spellCheck={false}
        onChange={(e) => onChange?.(e.target.value)}
        className="absolute inset-0 h-full min-h-[16em] resize-none border-0 bg-transparent p-3 text-transparent caret-black focus-visible:ring-0"
        data-testid="template-body-textarea"
      />
    </div>
  );
}
