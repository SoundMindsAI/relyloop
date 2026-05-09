---
name: guide-gen
pipeline-stage: 3.1
pipeline-role: conditional — invoked from impl-execute when tenant-facing UI changes
description: "Generate, audit, or regenerate tenant-facing walkthrough guides with Playwright screenshots and cross-model visual review. Use when: creating a new walkthrough guide, auditing existing guide screenshots against the codebase, regenerating screenshots after UI changes, or reviewing guide accuracy. Trigger phrases: generate guide, create walkthrough, audit guide, regenerate walkthrough screenshots, review guide accuracy, visual audit guide."
argument-hint: "[flow description or guide number, e.g. 'signup and onboarding' or '01'] [optional: '--audit' to audit existing guide without regenerating, '--regen' to regenerate screenshots only]"
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, Agent, WebFetch, WebSearch, TodoWrite
model: claude-opus-4-7
user-invocable: true
---

# Walkthrough Guide Generator & Visual Auditor

> **DORMANT** until RelyLoop has a tenant-facing web frontend (MVP3+ at the earliest per the umbrella spec roadmap). Do NOT invoke this skill before the web stack lands. The patterns below describe how the skill will work once activated; concrete file paths (`web/`, `web/src/components/guide-trigger.tsx`, `docs/08_guides/`) don't exist yet.

You generate, audit, and maintain user-facing walkthrough guides for the RelyLoop project. Each guide is a set of Playwright-captured screenshots with captions, served in-app via a `GuideViewer` component (to be built when the UI matures).

The core value of this skill is **visual verification**: every screenshot is compared against the codebase's expected state to catch UI bugs, missing features, stale content, and broken flows — before a tenant ever sees them.

## Inputs

- **Flow description or guide number**: e.g., `"signup and onboarding"`, `"first discovery run"`, or `"01"` (references `01_signup_and_onboarding`)
- **Optional flags**:
  - `--audit` — audit an existing guide's screenshots against the codebase without regenerating. Produces findings only.
  - `--regen` — regenerate screenshots for an existing guide (re-run the Playwright spec, then audit).
  - Omitted (default) — full generate mode: analyze codebase, write spec, capture screenshots, audit, write guide assets.

## Modes

| Mode | When to use | Behavior |
|---|---|---|
| **Generate** | New guide from a flow description | Analyze codebase → write Playwright spec → capture screenshots → visual audit → cross-model review → write guide assets |
| **Audit** | Review existing guide accuracy | Read existing screenshots → build expected-state model from code → compare → report findings → create bug/idea files |
| **Regenerate** | UI changed, screenshots stale | Re-run existing Playwright spec → visual audit → update assets |

## Project context

Read these files before starting:

- `CLAUDE.md` — project conventions, stack, data model
- `architecture.md` — system design, page structure
- `docs/08_guides/README.md` — guide conventions, directory structure, walkthrough inventory
- `web/src/components/guide-trigger.tsx` — route-to-guide mapping (GUIDE_MAP)
- `web/src/components/guide-viewer.tsx` — how guides are rendered in-app

## Directory structure

```
web/public/guides/<guide_id>/          # Single source of truth for assets
  metadata.json                        # Title, description, slides array
  01-screenshot-slug.png               # Screenshots (served by Next.js)
  ...

web/tests/e2e/guides/                  # Playwright specs
  <NN>_<slug>.spec.ts

docs/08_guides/
  README.md                            # Conventions and inventory only
```

## Walkthrough inventory

**This skill is DORMANT until RelyLoop has a tenant-facing web frontend** (per the umbrella spec roadmap, MVP3+ at the earliest). The walkthrough inventory below will be authored when the UI matures. Likely first guides for RelyLoop:

| # | Guide ID | Flow | Route prefix |
|---|---|---|---|
| 01 | `01_register_first_cluster` | Add cluster → configure auth → verify health | `/clusters` |
| 02 | `02_create_query_set_and_judgments` | Upload CSV → generate or import judgments → review calibration | `/query-sets`, `/judgments` |
| 03 | `03_run_first_study` | Create study form → watch live trials → see digest | `/studies` |
| 04 | `04_review_digest_and_open_pr` | Read narrative + parameter importance → click Open PR → see PR in GitHub | `/proposals` |
| 05 | `05_chat_driven_workflow` | Ask agent to tune → watch tool calls → confirm → study runs | `/chat` |

---

## Workflow — Generate mode

### Step 1: Analyze the codebase

Build an **expected-state model** for the flow — what the user should see at each step:

1. **Identify the pages/components** involved in the flow. Read each page file (`web/src/app/...`) and its key components.
2. **For each screen in the flow**, document:
   - URL and route
   - Heading text, form fields, buttons, badges visible
   - Data-driven elements (how many plan options? which filter tabs? what status badges?)
   - Conditional UI (what shows for trial vs pro? what shows with no keywords?)
3. **Identify API endpoints** called by each page — read the backend route to understand what data shapes the UI.
4. **Build the expected-state checklist**: a structured list of assertions per screen.

Example expected-state entry:
```
Screen: /studies/{id}
Expected elements:
  - Heading: study name
  - Status badge: one of "queued | running | completed | cancelled | failed"
  - Trials table: columns (#, params, primary_metric, duration_ms, status)
  - Cancel button: visible only when status="running"
  - Digest panel: visible only when an associated digests row exists
Source: web/src/app/studies/[id]/page.tsx — depends on `useStudy(id)` hook in ui/lib/api/studies.ts
```

### Step 2: Write the Playwright spec

Create `web/tests/e2e/guides/<NN>_<slug>.spec.ts` following the established patterns:

**Required conventions:**
- Import helpers from `../helpers/` (registerCluster, seedQuerySet, importJudgments, cleanupTestStudies, etc.)
- Write screenshots to `web/public/guides/<guide_id>/`
- Dismiss cookie consent banner at the start (`page.getByRole("button", { name: /got it/i })`)
- Hide floating overlays via MutationObserver (for Notion Web Clipper or similar)
- Use `page.evaluate(() => window.scrollTo(0, 0))` and `page.waitForTimeout(400)` before screenshots
- Clean up created tests in `test.afterEach`
- Use `getByRole()`, `getByLabel()`, `getByText()` — not CSS selectors
- Add `fullPage: true` for long pages that extend below the viewport

**Screenshot naming:** `NN-descriptive-slug.png` (e.g., `01-cluster-list.png`)

### Step 3: Run the spec

```bash
cd web
npx playwright test -c playwright.demo.config.ts \
  tests/e2e/guides/<NN>_<slug>.spec.ts \
  --project=chromium --reporter=line
```

**Prerequisites check:** Before running, verify:
1. Backend is responding: `curl -s http://localhost:4800/health`
2. Frontend is responding: `curl -s http://localhost:4100`
3. If either is down, run `bash scripts/dev/start.sh` and wait for both to come up

**Rate limiter:** If the cluster registration endpoint returns "Too many requests", the backend's in-memory rate limiter needs a reset. Restart the backend: kill the uvicorn process and restart it.

**If the spec fails:** Read the error, check the failure screenshot at `web/test-results/demo-artifacts/`, fix the spec, and re-run. Common issues:
- Rate limiter blocking the API (restart backend)
- Cluster-not-yet-registered redirect (register a cluster first)
- Form field placeholder mismatch (check actual placeholder text in the component)
- `page.goto()` losing session context (use in-page navigation instead)

### Step 4: Visual audit (Opus — Pass 1)

Read each captured screenshot and compare against the expected-state model from Step 1:

For each screenshot:

1. **Read the PNG file** using the Read tool (it renders images).
2. **Check every item** in the expected-state checklist for that screen:
   - Are all expected UI elements present?
   - Are text labels correct?
   - Are counts correct (e.g., 5 plan options, not 3)?
   - Is the layout reasonable (no clipped content, no overlapping elements)?
   - Are there any unexpected artifacts (extension icons, dev indicators, cookie banners)?
3. **Record findings** as:
   - **Pass** — screenshot matches expected state
   - **UI Bug** — code says X should be there, screenshot shows it's missing or wrong
   - **Spec Issue** — the Playwright spec captured the wrong state (e.g., wrong page, bad timing)
   - **Cosmetic** — minor visual issue (clipped text, awkward spacing) that doesn't affect functionality

### Step 5: Cross-model visual review (GPT-5.5 — Pass 2)

**This step is MANDATORY for Generate mode.**

Send each screenshot + its expected-state checklist to GPT-5.5 for an independent visual audit.

**API key resolution:**
1. Parse key: `grep '^OPENAI_API_KEY=' .env | cut -d'=' -f2-`
2. Use model `gpt-5.5` with `max_completion_tokens` (not `max_tokens`)

**Important: GPT-5.5 cannot read image files directly.** Instead, send:
- The expected-state checklist for each screen
- The Playwright spec source (showing what actions were taken)
- A text description of what Opus observed in each screenshot during Pass 1
- Ask GPT-5.5 to identify any expected elements that Opus may have missed or normalized away

**Review prompt:**
```
You are auditing a product walkthrough guide against its expected state.
For each screen, I'll provide:
  1. What the code says SHOULD be visible (expected-state checklist)
  2. What was observed in the screenshot (Opus's Pass 1 findings)
  3. The Playwright spec that captured it

Check for:
- Missing UI elements that the code defines but weren't observed
- Incorrect counts (e.g., code defines 5 items, only 3 were seen)
- Stale labels or copy that doesn't match the code
- Flow logic issues (wrong redirect, missing step)
- Accessibility gaps (missing labels, no keyboard nav)

Return findings as JSON: {"findings": [{"severity": "High/Medium/Low",
"screen": "NN-slug", "expected": "what should be there",
"observed": "what was seen instead", "source": "file:line",
"category": "ui_bug|missing_feature|spec_issue|cosmetic"}]}
```

**Opus adjudication:** For each GPT-5.5 finding:
- **Accept** — cite the code evidence, stage the action
- **Reject** — cite counter-evidence from screenshot or code
- **Escalate** — present to user for decision

### Step 5b: Completeness check

Verify the guide covers the complete user journey for the flow it describes:

1. **Entry point:** Does the first slide show the starting state the user would actually see? If the guide is for an authenticated flow, does it start on the correct page/tab?
2. **Action continuity:** Does each slide end with a clear action that leads to the next slide? Are there any gaps where the user would be stuck between slides?
3. **Exit point:** Does the last slide leave the user in a state where they can either:
   - Proceed independently (they know what to do next), OR
   - Pick up the next guide in the sequence (with an explicit bridge in the caption)?
4. **No dead ends:** If the guide ends at a prompt (e.g., "No keywords configured"), does the caption tell the user exactly what to do AND reference the follow-up guide?
5. **Minimum viable flow:** Does the guide cover enough steps that the user can accomplish the stated goal? A "First Discovery Run" guide that doesn't show results is incomplete. A "Send Email" guide that doesn't show the send button is incomplete.

If the guide is incomplete, extend it or adjust the scope and bridge to the next guide.

### Step 5c: Route relevance check

Verify the guide is mapped to the correct pages in `GUIDE_MAP` (`web/src/components/guide-trigger.tsx`):

1. **Read `GUIDE_MAP`** and check which route prefixes are mapped to this guide.
2. **For each slide**, verify the screenshot was taken on a page that matches one of the mapped route prefixes. A guide mapped to `/studies` should not show `/settings` screenshots unless the user is explicitly navigated there as part of the flow.
3. **Check for missing mappings:** If the guide shows pages not in its route mapping, either:
   - Add the route prefix to `GUIDE_MAP`, OR
   - Remove those slides (they belong in a different guide)
4. **Check for wrong mappings:** If the guide is mapped to a page where its content isn't relevant (e.g., a signup guide showing on the studies page), remove that mapping.
5. **Verify the guide is listed on the `/guide` page** (`web/src/app/guide/page.tsx` → `GUIDE_CATALOG`). If it's a new guide, add it.

### Step 6: Findings gate

Classify all findings from both passes (including completeness and route relevance):

**For UI Bugs (code is right, UI is wrong):**
Create a bug tracking file:
```
docs/02_product/planned_features/bug_<description>/idea.md
```
Following the idea template with:
- **Status:** `Bug — identified by guide-gen visual audit`
- **Origin:** `guide-gen audit of guide <guide_id>, screenshot <NN-slug.png>`
- **Problem:** What's wrong and where (with file:line references)
- **Proposed capabilities:** The fix needed
- **Scope signals:** Which layers need changes

**For Missing Features (intentional gap, not a bug):**
Create a feature tracking file:
```
docs/02_product/planned_features/<feature_name>/idea.md
```

**For Spec Issues:**
Fix the Playwright spec and re-run. Do not create tracking files.

**For Cosmetic Issues:**
Note in the audit log but do not create tracking files unless the user requests it.

**Present all findings to the user before proceeding.** Major findings (High severity) require user confirmation.

### Step 7: Write guide assets

After findings are resolved:

1. **metadata.json** → `web/public/guides/<guide_id>/metadata.json`
   ```json
   {
     "title": "Human-readable guide title",
     "description": "One-sentence description for the Guides page",
     "order": <number>,
     "tags": ["tag1", "tag2"],
     "estimated_time": "N minutes",
     "screenshots": [
       { "file": "01-slug.png", "caption": "What this screen shows" },
       ...
     ]
   }
   ```

2. **script.md** → `web/public/guides/<guide_id>/script.md`
   - One `## NN — Title` section per screenshot
   - 1-2 sentences of narrative context
   - `![alt text](/guides/<guide_id>/NN-slug.png)` image reference

3. **GUIDE_MAP entry** → update `web/src/components/guide-trigger.tsx`
   - Add the route prefix → guide ID mapping
   - Only add if the guide is relevant to an unauthenticated or specific page

### Step 8: Update inventory

Update `docs/08_guides/README.md` walkthrough inventory table — mark the guide as Complete.

### Step 9: Commit

Stage all new/modified files and commit:
```
git add web/public/guides/<guide_id>/ \
  web/tests/e2e/guides/<spec>.spec.ts \
  docs/08_guides/walkthroughs/<guide_id>/ \
  web/src/components/guide-trigger.tsx \
  docs/08_guides/README.md
```

If bug/idea files were created, include them in the commit.

---

## Workflow — Audit mode

When auditing an existing guide (`--audit`):

1. **Read the existing guide** — metadata.json, screenshots, spec
2. **Build expected-state model** from the current codebase (Step 1 of Generate)
3. **Visual audit** each screenshot against the model (Step 4 of Generate)
4. **Cross-model review** via GPT-5.5 (Step 5 of Generate)
5. **Report findings** — do NOT regenerate screenshots or modify guide assets
6. **Create bug/idea files** for any UI bugs or missing features found
7. **Present findings to user** with recommendations:
   - Fix the code (create bug file) → then regenerate with `--regen`
   - Update the spec (spec issue) → then regenerate with `--regen`
   - Accept as-is (cosmetic only)

---

## Workflow — Regenerate mode

When regenerating an existing guide (`--regen`):

1. **Read the existing Playwright spec** — do not rewrite it unless it fails
2. **Re-run the spec** to capture fresh screenshots
3. **Run visual audit** (Pass 1 + Pass 2) on the new screenshots
4. **If findings exist**, follow the Findings gate (Step 6 of Generate)
5. **Update guide assets** — copy new screenshots, update metadata.json if captions changed
6. **Commit** the updated screenshots

---

## Playwright spec patterns

### Auth patterns by flow type

**Unauthenticated flows (signup, login):**
```ts
await page.goto("/signup");
// Dismiss cookie banner
const gotIt = page.getByRole("button", { name: /got it/i });
if (await gotIt.isVisible({ timeout: 2000 }).catch(() => false)) {
  await gotIt.click();
}
```

**Authenticated flows (studies, clusters):**
```ts
import { seedTenantSession } from "../helpers/tenant_session";
import { createAdminTenant } from "../helpers/admin_tenant";

// Create tenant with pre-seeded data
const { tenantId } = await createAdminTenant(request, { name: "Guide Tenant", plan: "pro" });
await seedTenantSession(page, { tenantId, tenantName: "Guide Tenant" });
await page.goto("/studies");
```

**Flows requiring existing data (study results, proposals):**
```ts
// Seed via admin API endpoints
const adminToken = createAdminAccessToken("super_admin");
await request.post(`${API_URL}/admin/e2e/seed-completed-study`, { ... });
```

### Screenshot capture pattern
```ts
// Scroll to top, wait for animations, capture
await page.evaluate(() => window.scrollTo(0, 0));
await page.waitForTimeout(400);
await page.screenshot({
  path: path.join(SCREENSHOTS, "NN-slug.png"),
  fullPage: false, // true for long pages
});
```

### Overlay hiding pattern
```ts
// Hide floating overlays (Notion Web Clipper, etc.)
await page.addInitScript(() => {
  const observer = new MutationObserver(() => {
    document.querySelectorAll("body > div").forEach((el) => {
      const style = window.getComputedStyle(el);
      if (style.position === "fixed" && parseInt(style.zIndex) > 999999) {
        (el as HTMLElement).style.display = "none";
      }
    });
  });
  if (document.body) observer.observe(document.body, { childList: true, subtree: true });
  else document.addEventListener("DOMContentLoaded", () =>
    observer.observe(document.body, { childList: true, subtree: true })
  );
});
```

---

## Rules

1. **Never skip the visual audit.** Every screenshot must be read and compared against the expected-state model.
2. **Always use GPT-5.5 for cross-model review** in Generate mode. Model ID: `gpt-5.5`. Never substitute gpt-4o.
3. **Always create bug files** for UI discrepancies where the code is correct but the UI is wrong. Use the `bug_` prefix.
4. **Never modify application code** to fix bugs found during the audit. Create the tracking file and move on. The fix belongs in a separate PR via the normal spec → plan → execute pipeline.
5. **Always dismiss the cookie banner** before capturing screenshots.
6. **Always check that dev servers are running** before executing the Playwright spec.
7. **Screenshots are the single source of truth** — they live in `web/public/guides/` only. No duplicate copies.
8. **Clean up test data** — every Playwright spec must clean up created tenants/users in `test.afterEach`.
9. **Use Playwright's bundled Chromium** — not system Chrome. The demo config sets `channel: undefined` and `--disable-extensions` to avoid browser extension artifacts.
10. **Present findings to the user** before creating bug/idea files. Major findings require confirmation.
11. **Captions must be action-oriented instructions.** Every caption starts with a verb telling the user what to do: "Click", "Enter", "Select", "Scroll", "Open". Never describe outcomes — describe actions. Bad: "The Studies tab shows your studies." Good: "Click the Studies tab to see your study trial logs."
12. **Guides must be complete.** A guide that ends before the user can accomplish the stated goal is not done. If a technical limitation prevents completion (e.g., session issues), bridge to the next guide explicitly in the last caption.
13. **Route mappings must be verified.** Every guide must be mapped to the correct pages in `GUIDE_MAP` and listed in `GUIDE_CATALOG` on the `/guide` page. A guide should only appear on pages where its content is relevant to what the user is currently doing.
