'use client';

import { ExternalLink, Maximize2, Minimize2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const GITHUB_BLOB_BASE = 'https://github.com/SoundMindsAI/relyloop/blob/main';

// Reuse the same localStorage namespace as the GuideViewer so the text-size
// preference is honored across both surfaces (a user who upsizes the visual
// walkthroughs gets larger long-form docs too).
const STORAGE_TEXT_SIZE = 'relyloop.guide-viewer.text-size';

type TextSize = 'sm' | 'base' | 'lg';
const TEXT_SIZE_CYCLE: TextSize[] = ['sm', 'base', 'lg'];

function readStoredTextSize(): TextSize {
  if (typeof window === 'undefined') return 'base';
  try {
    const raw = window.localStorage.getItem(STORAGE_TEXT_SIZE);
    if (raw === 'sm' || raw === 'base' || raw === 'lg') return raw;
    return 'base';
  } catch {
    return 'base';
  }
}

/**
 * Long-form markdown documentation viewer. Fetches the markdown from
 * `/docs/<file>` (Next.js serves it from `ui/public/docs/`, copied at
 * build time from `docs/08_guides/`), renders with react-markdown + GFM,
 * and rewrites repository-relative links to GitHub URLs.
 *
 * Shares the GuideViewer's accessibility affordances:
 *   - Text-size toggle (Aa) cycles sm / base / lg, persisted to localStorage
 *   - "View on GitHub" link below the title gives users the canonical source
 *   - Standard `prose` typography handles headings, code blocks, lists,
 *     tables (via remark-gfm) consistently with the rest of the app
 */
export function MarkdownDoc({ file, title }: { file: string; title: string }) {
  const [markdown, setMarkdown] = useState<string>('');
  const [status, setStatus] = useState<'loading' | 'loaded' | 'error'>('loading');
  const [error, setError] = useState<string | null>(null);
  const [textSize, setTextSize] = useState<TextSize>(() => readStoredTextSize());
  const [wide, setWide] = useState<boolean>(false);

  // Reset state when `file` prop changes — React's "set state during render"
  // pattern (not inside an effect) avoids the cascading-renders lint rule.
  const [storedFile, setStoredFile] = useState(file);
  if (storedFile !== file) {
    setStoredFile(file);
    setMarkdown('');
    setStatus('loading');
    setError(null);
  }

  useEffect(() => {
    let cancelled = false;

    async function loadDoc() {
      try {
        const resp = await fetch(`/docs/${file}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const text = await resp.text();
        if (cancelled) return;
        setMarkdown(text);
        setStatus('loaded');
      } catch (err: unknown) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        setStatus('error');
      }
    }

    void loadDoc();
    return () => {
      cancelled = true;
    };
  }, [file]);

  const cycleTextSize = useCallback(() => {
    setTextSize((prev) => {
      const idx = TEXT_SIZE_CYCLE.indexOf(prev);
      const next = TEXT_SIZE_CYCLE[(idx + 1) % TEXT_SIZE_CYCLE.length]!;
      try {
        window.localStorage.setItem(STORAGE_TEXT_SIZE, next);
      } catch {
        // ignore (private browsing / quota)
      }
      return next;
    });
  }, []);

  // Rewrite repository-relative links to absolute GitHub URLs.
  //
  //   ../01_architecture/optimization.md
  //   ../../backend/workers/orchestrator.py
  //
  // Source docs sit at `docs/08_guides/`. From that base, `../foo` resolves
  // to `docs/foo`, `../../foo` to `foo` (repo root), etc. We compute the
  // resolved repo-relative path then prepend the GitHub blob URL.
  const resolveLink = useCallback((href: string): string => {
    if (!href) return href;
    // Absolute URLs + in-page anchors pass through.
    if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('#') || href.startsWith('mailto:')) {
      return href;
    }
    // Repository-relative path. Compute against the source location.
    const sourceBase = ['docs', '08_guides'];
    const parts = href.split('/');
    const stack = [...sourceBase];
    for (const part of parts) {
      if (part === '' || part === '.') continue;
      if (part === '..') stack.pop();
      else stack.push(part);
    }
    return `${GITHUB_BLOB_BASE}/${stack.join('/')}`;
  }, []);

  const proseSize =
    textSize === 'sm' ? 'prose-sm' : textSize === 'base' ? 'prose-base' : 'prose-lg';

  return (
    <article
      className="mx-auto space-y-6 px-4 py-8 sm:px-6"
      data-testid="markdown-doc"
      data-text-size={textSize}
      data-wide={wide ? 'true' : 'false'}
      style={{ maxWidth: wide ? '1400px' : '900px' }}
    >
      <header className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
        <div className="flex items-center gap-2">
          <a
            href={`${GITHUB_BLOB_BASE}/docs/08_guides/${file}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
            data-testid="markdown-doc-github"
          >
            <ExternalLink className="h-3 w-3" />
            View on GitHub
          </a>
          <Button
            variant="ghost"
            size="icon"
            onClick={cycleTextSize}
            data-testid="markdown-doc-text-size"
            aria-label={`Text size: ${textSize}. Click to cycle.`}
            title="Cycle text size"
          >
            <span className="font-semibold">
              {textSize === 'sm' ? 'A−' : textSize === 'base' ? 'A' : 'A+'}
            </span>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setWide((w) => !w)}
            data-testid="markdown-doc-wide"
            aria-label={wide ? 'Narrower column' : 'Wider column'}
            aria-pressed={wide}
            title="Toggle column width"
          >
            {wide ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </Button>
        </div>
      </header>

      {status === 'loading' && (
        <p className="py-12 text-center text-sm text-muted-foreground">Loading documentation…</p>
      )}

      {status === 'error' && (
        <p className="py-12 text-center text-sm text-destructive" data-testid="markdown-doc-error">
          Could not load documentation: {error}
        </p>
      )}

      {status === 'loaded' && (
        <div className={cn('prose max-w-none dark:prose-invert', proseSize)}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            disallowedElements={['script', 'iframe', 'style']}
            unwrapDisallowed
            urlTransform={resolveLink}
          >
            {markdown}
          </ReactMarkdown>
        </div>
      )}
    </article>
  );
}
