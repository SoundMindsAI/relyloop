# Import judgments + calibrate

> 3-minute walkthrough — establish ground truth and measure LLM agreement.

Judgments are the relevance ratings (0–3) for every (query, doc) pair the
queries surface. They're what `ir_measures` scores trials against. Two
paths to populate them:

- **LLM generation** (Guide TBD when MVP2 ships LLM mocking) — fires
  `POST /api/v1/judgments/generate`, the worker calls OpenAI for each
  (query, doc) pair.
- **Import** (this guide) — bypass the LLM entirely via
  `POST /api/v1/judgment-lists/import`. Useful for tutorial data, pre-curated
  benchmarks (Amazon ESCI, MS MARCO, etc.), or hand-labeled human truth.

## Calibration

Once you have a judgment list, calibration measures **how much you can
trust it**. Provide a small set of human-rated samples; the platform
computes:

- **Cohen's κ** — chance-corrected agreement. >0.6 = substantial, >0.8 = near-perfect.
- **Linear-weighted κ** — also accounts for *how off* the disagreements are.
  A 0-vs-3 disagreement weighs more than a 2-vs-3 disagreement.

Calibration scores are saved on the judgment list and inherited by every
study that references it.

## Steps

1. **Import a judgment list** — for this walkthrough we use the import path,
   so the screenshots are deterministic and don't depend on an LLM.

   ```bash
   curl -X POST http://localhost:8000/api/v1/judgment-lists/import \
     -H "Content-Type: application/json" \
     -d @samples/judgments.json
   ```
2. **Open the detail page** at `/judgments/{id}`.
3. **Click "Calibrate"** to open the modal.
4. **Paste a CSV** of human-rated samples: `query_id,doc_id,rating` header
   followed by one row per sample. Need ≥10 distinct (query_id, doc_id)
   pairs.
5. **Submit.** Result panel shows both kappa scores + the matched sample
   count.

## Reference

- API import: `POST /api/v1/judgment-lists/import`
- API calibrate: `POST /api/v1/judgment-lists/{id}/calibration`
- API per-judgment override: `PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}`
- Runbook: [`docs/03_runbooks/judgment-generation-debugging.md`](../03_runbooks/judgment-generation-debugging.md)

> See the [glossary](/guide/glossary) for definitions of every term used in this walkthrough.
