/**
 * FAQ — operator-judgment-shaped Q&A surface for questions tooltips and the
 * glossary can't carry. Lives next to `ui/src/lib/glossary.ts` because it
 * cross-references the same domain vocabulary and uses the same
 * `react-markdown` rendering pipeline.
 *
 * **What goes here vs what goes in the glossary:**
 * - Glossary answers "what does X mean?" in 1–2 sentences (definitional).
 * - FAQ answers "what should I do about X?" / "why does Y happen?" in
 *   3–5 sentences (judgment-shaped).
 *
 * Entries are deep-linkable via the `anchor` field — `/guide/faq#<anchor>`
 * scrolls the targeted entry into view.
 */

export type FAQCategory =
  | 'studies-and-confidence'
  | 'judgments'
  | 'proposals-and-prs'
  | 'chat-agent'
  | 'setup-and-install';

export interface FAQEntry {
  /** Unique slug for the URL fragment. Kebab-case, no leading hash. */
  readonly anchor: string;
  /** The question as the operator would ask it. */
  readonly question: string;
  /** Markdown answer — paragraphs, bullets, inline code, bold/italic. */
  readonly answer: string;
  readonly category: FAQCategory;
}

export const FAQ_CATEGORIES: Readonly<Record<FAQCategory, string>> = {
  'studies-and-confidence': 'Studies & confidence',
  judgments: 'Judgments',
  'proposals-and-prs': 'Proposals & PRs',
  'chat-agent': 'Chat agent',
  'setup-and-install': 'Setup & install',
};

export const FAQ_CATEGORY_ORDER: readonly FAQCategory[] = [
  'setup-and-install',
  'studies-and-confidence',
  'judgments',
  'proposals-and-prs',
  'chat-agent',
];

export const faq: readonly FAQEntry[] = [
  // ---------------------------------------------------------------------------
  // Setup & install
  // ---------------------------------------------------------------------------
  {
    anchor: 'llm-capability-check-warning',
    category: 'setup-and-install',
    question: 'The LLM capability check WARN-logged at startup — should I care?',
    answer: [
      'Yes — three features depend on it: judgment generation (`/judgments/generate`), digest narrative authoring, and the chat agent. The WARN line will name which probe failed (`/v1/models`, `/v1/chat/completions`, or `/v1/embeddings`).',
      '',
      "Check `OPENAI_BASE_URL` (defaults to `https://api.openai.com/v1`) and your mounted key at `./secrets/openai_key`. If you're pointing at a local Ollama / LM Studio / vLLM endpoint, verify it's running with the model you set via `OPENAI_MODEL`. `/healthz` surfaces the cached probe result under `subsystems.openai`.",
      '',
      'See [`llm-orchestration.md`](https://github.com/SoundMindsAI/relyloop/blob/main/docs/01_architecture/llm-orchestration.md) for the full capability matrix.',
    ].join('\n'),
  },
  {
    anchor: 'ollama-lm-studio',
    category: 'setup-and-install',
    question: 'Can I use Ollama / LM Studio / vLLM instead of OpenAI?',
    answer: [
      'Yes — any OpenAI-compatible endpoint works. Set `OPENAI_BASE_URL` in `.env` to your local endpoint (e.g., `http://host.docker.internal:11434/v1` for Ollama) and `OPENAI_MODEL` to the model name. The capability check probes the same three endpoints on whatever you point it at.',
      '',
      "Empty `./secrets/openai_key` is fine when the local endpoint doesn't require auth — the API logs a WARN and `/healthz` reports `subsystems.openai: missing_key`. See the tutorial's [Step 0 Path B](https://github.com/SoundMindsAI/relyloop/blob/main/docs/08_guides/tutorial-first-study.md) for a worked example.",
    ].join('\n'),
  },
  {
    anchor: 'github-token-storage',
    category: 'setup-and-install',
    question: 'Where do my GitHub tokens live?',
    answer: [
      'Per-config-repo PATs are stored as files under `./secrets/<config_repos.auth_ref>` — never in the database, never in env vars. The `config_repos.auth_ref` column carries the filename, and the `open_pr` worker reads the file at PR-creation time via the `GIT_CONFIG_*` env-var pattern documented in [`github-token-handling.md`](https://github.com/SoundMindsAI/relyloop/blob/main/docs/04_security/github-token-handling.md).',
      '',
      'Rotate by overwriting the file in place — no DB write, no restart needed. The pre-existing PR body redaction scrubs any accidental token leak from log lines via the `SensitiveFieldScrubber` (MVP2+).',
    ].join('\n'),
  },

  // ---------------------------------------------------------------------------
  // Studies & confidence
  // ---------------------------------------------------------------------------
  {
    anchor: 'confidence-ci-missing',
    category: 'studies-and-confidence',
    question: 'My confidence interval is missing — why?',
    answer: [
      'The 95% CI computation needs at least 5 completed queries with per-query metrics. Three things make it degrade gracefully (returns `null` for that sub-shape rather than failing the digest):',
      '',
      '- **Old study** — `trials.per_query_metrics` is `NULL` for studies completed before `feat_pr_metric_confidence` shipped (Alembic head `0015`). The column is additive; pre-existing rows stay NULL forever.',
      "- **Small query set** — fewer than 5 queries means bootstrap resampling can't produce stable bounds. The fix is to add more queries to the set, not to lower the threshold.",
      '- **No best trial** — `studies.best_trial_id IS NULL` (study failed, was cancelled with no completed trials, or hit the zero-streak abort). In that case the entire `confidence` field is `null`, not just `ci_95`.',
      '',
      'See the [glossary entry](/guide/glossary#confidence.ci_95) for the metric definition.',
    ].join('\n'),
  },
  {
    anchor: 'convergence-noisy',
    category: 'studies-and-confidence',
    question: 'Convergence regime is *noisy* — should I rerun with a different sampler?',
    answer: [
      "*Noisy* by itself isn't a problem — it just means the optimizer didn't find a clear winner-and-plateau pattern within the trial budget. Three follow-ups in increasing severity:",
      '',
      '- **Few trials (≤20):** noisy is meaningless — TPE needs ~10 random + ~10 informed trials before its pattern is interpretable. Re-run with 50+ trials before changing the sampler.',
      "- **Noisy + sharp peak runner-up gap:** the winner is isolated AND the optimizer didn't reproduce it — could be a lucky single trial. Re-run; if the winner reproduces, accept it.",
      '- **Noisy + many late-rising trials:** the optimizer was still improving at the end of the budget. Re-run with a larger budget OR switch to a tighter search space (smaller bounds on the parameter with the most importance per the parameter-importance chart).',
      '',
      'See [glossary: convergence_regime](/guide/glossary#confidence.convergence_regime) for the regime definitions.',
    ].join('\n'),
  },
  {
    anchor: 'confidence-null-vs-partial',
    category: 'studies-and-confidence',
    question: 'Why is my `confidence` field `null` instead of a partial shape?',
    answer: [
      'There are two distinct null cases — they look the same in the UI but have different causes:',
      '',
      '- **`best_trial_id IS NULL`** — the study has no winner trial (failed, cancelled before any trial completed, or hit the zero-streak abort). The entire `confidence` field is `null`. Fix: re-run the study after addressing the underlying failure (check `studies.failed_reason`).',
      '- **`best_trial_id` set but winner `per_query_metrics IS NULL`** — the winner trial completed but pre-dates `feat_pr_metric_confidence`. The entire `confidence` field is `null` because no analytics can run without per-query data. Fix: re-run; new trials will populate the column.',
      '',
      "If only individual sub-shapes are null (e.g., `ci_95: null` but `runner_up_gap: {...}` present), that's the FR-7 partial-shape path — see [confidence-ci-missing](#confidence-ci-missing).",
    ].join('\n'),
  },
  {
    anchor: 'runner-up-terminology',
    category: 'studies-and-confidence',
    question: "What's the difference between `runner_up_gap` and `runner_up_metric`?",
    answer: [
      '- **`runner_up_metric`** — the primary-metric value of the second-best trial. Just a number.',
      '- **`runner_up_gap`** — the *interpretation* of how far the runner-up sat from the winner, expressed as a regime label (`robust_plateau` or `sharp_peak`) plus the actual metric delta.',
      '',
      'The gap is the operator-facing field; the raw metric is mostly for debugging. `robust_plateau` means many near-equivalents exist (winner is reproducible); `sharp_peak` means the winner is isolated (small parameter changes could swing the metric).',
    ].join('\n'),
  },
  {
    anchor: 'how-many-trials',
    category: 'studies-and-confidence',
    question: 'How many trials should I run?',
    answer: [
      'Three breakpoints:',
      '',
      '- **First study on a new template:** 10 trials (the tutorial default). Enough to see the loop work end-to-end; not enough to draw conclusions.',
      '- **Tuning a known-good template:** 50 trials. Lets TPE finish its random phase (10) and have 40 informed trials. Most studies converge within this budget.',
      '- **Production tuning with a wide search space:** 100–200 trials. Necessary when cardinality is high (≥4 floats or ≥1 categorical with ≥5 choices). Late-rising regime in the digest is the signal to bump higher.',
      '',
      "The orchestrator's `max_trials` AND `time_budget_seconds` both terminate; whichever fires first wins. Set both — `max_trials` caps cost, `time_budget` caps wall-clock.",
    ].join('\n'),
  },
  {
    anchor: 'no-signal-zero-streak',
    category: 'studies-and-confidence',
    question:
      "My study failed with 'no signal: 20 consecutive trials scored 0.0' — what went wrong?",
    answer: [
      'The mid-flight Tier-3 zero-streak guard fired. 20 trials in a row scored `primary_metric = 0.0`, which means **the judgment overlap is gone** — every retrieved doc ID is unrated, so every score is zero regardless of parameters.',
      '',
      'Two common causes:',
      '',
      "- **Target index mismatch.** The study targets index `products-v2` but the judgment list was built against `products-v1`. Doc IDs from v2 have no rating in v1's judgments. Verify `studies.target` matches `judgment_lists.target` for the chosen list.",
      '- **Cluster mismatch.** The study points at cluster A but the judgment list was created against cluster B — doc IDs are cluster-scoped, so even the same target name on two clusters yields zero overlap. (This is why `feat_study_target_judgment_mismatch_guard` rejects at create-time with `JUDGMENT_CLUSTER_MISMATCH` / `JUDGMENT_TARGET_MISMATCH` — but old studies created before that guard can still hit the mid-flight version.)',
      '',
      'Fix: regenerate / re-import judgments against the correct cluster + target, then re-run the study.',
    ].join('\n'),
  },

  // ---------------------------------------------------------------------------
  // Judgments
  // ---------------------------------------------------------------------------
  {
    anchor: 'kappa-trust-threshold',
    category: 'judgments',
    question: 'When should I trust LLM-as-judge ratings vs override them?',
    answer: [
      'After running calibration against a human-rated sample, you get two kappa values:',
      '',
      "- **Cohen's κ ≥ 0.6:** strong agreement — LLM ratings are trustworthy. Accept as-is.",
      "- **Linear-weighted κ ≥ 0.5, Cohen's < 0.6:** the LLM is close but not exact (e.g., it rates a relevant doc as 2 when the human rates it 3). Acceptable for relative ranking — studies will optimize ordering correctly.",
      '- **Both κ < 0.5:** systematic disagreement. Inspect the lowest-confidence ratings via the override panel (`PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}`) and consider rewriting the rubric.',
      '',
      'See [`judgment-generation-debugging.md`](https://github.com/SoundMindsAI/relyloop/blob/main/docs/03_runbooks/judgment-generation-debugging.md) for the override workflow.',
    ].join('\n'),
  },
  {
    anchor: 'cohens-vs-linear-weighted',
    category: 'judgments',
    question: "What's the difference between Cohen's κ and linear-weighted κ?",
    answer: [
      'Both measure agreement above chance on the 0–3 rating scale, but they penalize disagreements differently:',
      '',
      "- **Cohen's κ** treats every disagreement equally. A 0-vs-3 mismatch counts the same as a 2-vs-3 mismatch.",
      '- **Linear-weighted κ** penalizes by distance. A 0-vs-3 mismatch hurts the score more than a 2-vs-3 mismatch.',
      '',
      'For ordinal ranking-relevance scales, linear-weighted is the more meaningful signal — getting "almost right" is genuinely better than getting "completely wrong." Cohen\'s is the conservative floor; linear-weighted is the practical threshold.',
    ].join('\n'),
  },
  {
    anchor: 'judgment-llm-cost',
    category: 'judgments',
    question: 'Why does judgment generation cost so much?',
    answer: [
      "Cost scales as **N queries × K top-docs × 1 LLM call**. With 50 queries × 20 top-docs = 1000 LLM calls per judgment list. Even at $0.001/call, that's $1 per regeneration — non-trivial across iterations.",
      '',
      'Three knobs to control cost:',
      '',
      '- **Smaller `top_k`** in the generate request (default 10; 5 cuts cost in half).',
      '- **Smaller / cheaper model** via `OPENAI_MODEL` (e.g., `gpt-5.5-nano` is ~10× cheaper than `gpt-5.5`).',
      '- **Budget gate** — set `OPENAI_BUDGET_USD_PER_RUN` in `.env` to halt the run if estimated cost exceeds the threshold.',
      '',
      'See the [LLM data flow doc](https://github.com/SoundMindsAI/relyloop/blob/main/docs/04_security/llm-data-flow.md) for exactly what each call sends.',
    ].join('\n'),
  },
  {
    anchor: 'bulk-import-judgments',
    category: 'judgments',
    question: 'How do I bulk-import judgments without running the LLM?',
    answer: [
      'Use `POST /api/v1/judgment-lists/import` with either JSON or CSV. The endpoint creates the judgment list AND every per-(query, doc) rating in one transaction — no LLM call, no cost, deterministic results.',
      '',
      'CSV format: `query_id,doc_id,rating` (rating ∈ {0, 1, 2, 3}). JSON format: same fields in an array. The list ID is returned in the response and can be used immediately in study creation.',
      '',
      'See [guide 05](/guide#) for the UI walkthrough.',
    ].join('\n'),
  },
  {
    anchor: 'do-i-need-ubi',
    category: 'judgments',
    question: 'Do I need UBI to use RelyLoop?',
    answer: [
      "No. The LLM-as-judge path works on any cluster — that's the default and what the tutorial covers. UBI (User Behavior Insights) is an opt-in upgrade once you have an instrumented cluster.",
      '',
      "UBI's value: ratings reflect what users actually do (clicks, dwell) rather than what an LLM thinks they should do. No LLM cost for pure converters. If you operate at scale and care about real-traffic relevance, install the [OpenSearch UBI plugin / o19s ES UBI fork](https://github.com/SoundMindsAI/relyloop/blob/main/docs/03_runbooks/ubi-judgment-generation.md) and switch the method picker.",
    ].join('\n'),
  },
  {
    anchor: 'trust-ubi-over-llm',
    category: 'judgments',
    question: 'Should I trust UBI ratings over LLM ratings?',
    answer: [
      'It depends on your traffic shape. UBI captures **real behavior** — clicks and dwell from actual users — so high-traffic queries get high-confidence ratings. But sparse queries (long tail) get weak or no UBI signal; pure UBI rates them 0, which can hurt your study.',
      '',
      'Recommended progression:',
      '',
      '- **rung_3** (≥ 500 events): trust pure UBI (`ctr_threshold` or `dwell_time`) — the signal is dense enough.',
      '- **rung_2** (≥ 100 events): use `hybrid_ubi_llm` — UBI rates the head, LLM fills sparse pairs.',
      '- **rung_1** (< 100 events): use `hybrid_ubi_llm` AND consider widening the time window.',
      '- **rung_0** (UBI not enabled): use LLM-only — the picker defaults to this.',
    ].join('\n'),
  },
  {
    anchor: 'cluster-no-ubi',
    category: 'judgments',
    question: 'My cluster shows "UBI not enabled" — is that a problem?',
    answer: [
      "No, it just means the UBI plugin isn't installed on this cluster (or it's installed but no events have landed yet). LLM-as-judge still works.",
      '',
      'If you want UBI: install the [OpenSearch UBI plugin / o19s ES UBI fork](https://github.com/SoundMindsAI/relyloop/blob/main/docs/03_runbooks/ubi-judgment-generation.md) on every node, configure your application to emit events with `application=<target-index-name>`, and re-open the generate-judgments dialog. The on-ramp nudge that surfaces at rung_0 includes the install link.',
    ].join('\n'),
  },

  // ---------------------------------------------------------------------------
  // Proposals & PRs
  // ---------------------------------------------------------------------------
  {
    anchor: 'pr-regressed-count',
    category: 'proposals-and-prs',
    question: 'The PR body shows `regressed: 2` — should I reject?',
    answer: [
      'Not automatically. `regressed` is the count of queries where the winner config scored *worse* than the runner-up by more than the per-metric threshold (NDCG/Precision/Recall: 0.01; MAP/MRR: 0.02). Two regressions in a 50-query set is 4% — usually acceptable if the gains elsewhere outweigh them.',
      '',
      'Look at the named regressors in the per-query outcomes table:',
      '',
      "- **If they're queries you care about specifically** (e.g., flagship brand-name queries), reject and tune the search space.",
      "- **If they're long-tail / low-priority queries**, accept — the overall lift on more important queries justifies the trade.",
      '',
      'There\'s no "right" threshold — it\'s an operator judgment shaped by your query catalog priorities.',
    ].join('\n'),
  },
  {
    anchor: 'rejected-proposal-github-pr',
    category: 'proposals-and-prs',
    question: 'I rejected a proposal — what happens to the open PR on GitHub?',
    answer: [
      "**Nothing automatic.** Rejecting a proposal sets `proposal.status = 'rejected'` in the database; it does NOT close the corresponding GitHub PR. The decoupling is intentional — RelyLoop doesn't hold a GitHub token with `repo:write` scope at rejection time, only at PR-creation time.",
      '',
      'You must close the GitHub PR manually (with a comment citing the rejection reason for audit trail). The orphan-branch cleanup is documented in [`pr-open-debugging.md`](https://github.com/SoundMindsAI/relyloop/blob/main/docs/03_runbooks/pr-open-debugging.md).',
    ].join('\n'),
  },
  {
    anchor: 'open-pr-not-creating',
    category: 'proposals-and-prs',
    question: "Why isn't `open_pr` creating my PR?",
    answer: [
      'Three common causes — debug in this order:',
      '',
      "- **Pre-existing PR on the same branch.** The worker checks GitHub for an open PR matching the proposal's slug; if one exists, it links rather than creating. Look for the existing PR in your config repo.",
      '- **Token scope.** The per-repo PAT at `./secrets/<config_repos.auth_ref>` needs `repo` scope on the config repo. Insufficient scope returns 403 from GitHub; the worker logs the error and sets `proposal.last_open_pr_error`.',
      "- **Branch protection.** If the config repo requires signed commits or status checks on the proposal branch, the worker's force-push fails. Loosen branch protection on `relyloop/proposal/*` branches or sign commits.",
      '',
      'See [`pr-open-debugging.md`](https://github.com/SoundMindsAI/relyloop/blob/main/docs/03_runbooks/pr-open-debugging.md) for the full triage flow.',
    ].join('\n'),
  },

  // ---------------------------------------------------------------------------
  // Chat agent
  // ---------------------------------------------------------------------------
  {
    anchor: 'agent-tool-hallucination',
    category: 'chat-agent',
    question: "The agent claims a study exists but I can't find it in the UI.",
    answer: [
      'Tool hallucination — the LLM invented a study ID. The cure is in the conversation log:',
      '',
      '- Open the conversation detail page and find the assistant turn that referenced the study.',
      '- Look at the tool call that turn issued (`get_study`, `list_studies`, etc.). The actual study_id passed will be visible in the call args.',
      '- If the call returned an error (e.g., `RESOURCE_NOT_FOUND`), the agent should have surfaced it but may have soft-failed and hallucinated content.',
      '',
      'When this happens, re-prompt with the explicit study ID you expect — agents stay on-task when the user pins the entity.',
    ].join('\n'),
  },
  {
    anchor: 'force-agent-tool-call',
    category: 'chat-agent',
    question: 'How do I force the agent to use a specific tool?',
    answer: [
      "Phrase the question in terms of the tool's *output*, not the tool's name. The agent matches function-call decisions to user intent — generic phrasing leaves it free to pick the wrong tool or skip the call entirely.",
      '',
      '- ❌ "Use list_trials" — agents don\'t reliably honor name-pinning.',
      '- ✅ "Show me the parameter importance chart for study X" — the only tool that produces parameter importance is `get_study_details`, so the agent dispatches it.',
      '',
      'See the [agent tool registry](https://github.com/SoundMindsAI/relyloop/blob/main/docs/01_architecture/agent-tools.md) for the canonical tool list and what each one produces.',
    ].join('\n'),
  },
] as const;

export type FAQAnchor = (typeof faq)[number]['anchor'];
