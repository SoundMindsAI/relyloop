// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared markdown rendering safety policy.
 *
 * Every surface that renders user-data-shaped markdown (HelpPopover,
 * MarkdownDoc, the /guide/glossary route, the /guide/faq route) MUST
 * use this constant as the `disallowedElements` argument to
 * `react-markdown`. Centralizing the list prevents per-surface drift —
 * a change here is automatically picked up by every consumer.
 *
 * The current allowlist forbids:
 *   - <script> — XSS via inline JS
 *   - <iframe> — third-party content injection
 *   - <style>  — global style hijacking
 *
 * Glossary and FAQ entries are vetted at content-time by parity tests
 * (`ui/src/__tests__/lib/glossary.test.ts`), and `react-markdown`
 * without `rehypeRaw` already treats raw HTML in markdown source as
 * literal text — `disallowedElements` is belt-and-braces against
 * the day someone adds `rehypeRaw` without understanding the
 * downstream impact.
 */
export const MARKDOWN_DISALLOWED_ELEMENTS = ['script', 'iframe', 'style'] as const;
