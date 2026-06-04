// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared helpers for rendering ``proposals.config_diff`` JSONB values.
 *
 * Promoted out of ``ui/src/components/proposals/config-diff-panel.tsx`` in
 * the ``feat_proposal_full_param_space_view`` Story 1.1 refactor so both
 * ``<ConfigDiffPanel>`` and the new ``<FullParamSpacePanel>`` (Story 1.3)
 * consume the same canonical normalization without duplicating logic.
 *
 * Backend writes ``proposals.config_diff`` from feat_digest_proposal as a
 * flat ``{ "<param>": {"from": <prev>, "to": <new>} }`` dict — see
 * backend/workers/digest.py:1158-1174. Manual / agent-created proposals
 * may also write a flat ``{ "<param>": ["before", "after"] }`` 2-tuple
 * (legacy shape) or a non-per-key shape like
 * ``{"params": {...}, "source": "..."}`` (agent tool); the canonical
 * renderer handles the ``{from, to}`` object form, falls back to the
 * 2-tuple array form, and drops to a single "value" column for
 * everything else.
 */

export function renderValue(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return JSON.stringify(v);
}

export function extractFromTo(raw: unknown): { from: unknown; to: unknown } {
  // Canonical digest-worker form: { from, to } object per key.
  if (
    raw !== null &&
    typeof raw === 'object' &&
    !Array.isArray(raw) &&
    'from' in (raw as object) &&
    'to' in (raw as object)
  ) {
    const r = raw as { from: unknown; to: unknown };
    return { from: r.from, to: r.to };
  }
  // Legacy 2-tuple form: [before, after].
  if (Array.isArray(raw) && raw.length === 2) {
    return { from: raw[0], to: raw[1] };
  }
  // Unknown shape — render as a single value in the "To" column.
  return { from: null, to: raw };
}
