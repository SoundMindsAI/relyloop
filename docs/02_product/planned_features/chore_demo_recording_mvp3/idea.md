# chore_demo_recording_mvp3

## Status

Idea — deferred from `chore_tutorial_polish` Story 4.6 on 2026-05-12.
Pulled out of MVP1 scope post-merge of PR #64.

## Origin

`chore_tutorial_polish/feature_spec.md` FR-6 required a 5–7 minute screencast
of the full Karpathy loop (clone → study → digest → Open PR), linked from the
README. The spec marked it as a SHOULD; the smoke gate is the actual
release-blocking artifact.

After PR #64 merged with the smoke gate green, the maintainer evaluated
whether to record the demo for `v0.1.0` and decided to defer to **MVP3**
("Production Stacks") release polish. Captured here so it surfaces in
`/pipeline status` when MVP3 is in flight.

## Why MVP3, not MVP2 or MVP4

| Defer to | UX content stable? | New audience reached? | Worth recording? |
|---|---|---|---|
| **MVP2** ("Observable") | Same chat/study/proposal flow as today | No — observability is backend-only; demo is unchanged | No — same video, 3 weeks delayed |
| **MVP3** ("Production Stacks") | First "production" UX (TLS install, Lucidworks Fusion adapter, multi-Git-provider) | Yes — demo can credibly say "deploy this in front of your team" | **Yes** |
| **MVP4** ("Multi-tenant") | Login screen + tenant switcher reshape the chrome | Yes, but would invalidate any MVP3 video within weeks | Re-record needed; do MVP3 first then MVP4 update |
| **GA v1** | Stable | Yes | Yes — but waiting that long means no demo for ~12+ weeks |

MVP2 is wasted effort (same content). MVP4 will invalidate any earlier
recording. MVP3 is the sweet spot: first credible "production" story to
tell, with enough UX stability to not rot in 4 weeks.

## Scope

A 5–7 minute screencast hosted as YouTube unlisted (or Loom), linked from
README's "What it looks like" section. Captures (per FR-6):

1. `git clone` → `make up`
2. `make migrate` + `make seed-clusters` + `make seed-es`
3. Create query set + generate judgments via the chat agent OR `/judgments/new` UI
4. Create study via the chat agent (show the agent's `create_study` proposal + operator confirmation)
5. Watch trial table fill in at `/studies/{id}`
6. See the digest narrative + recommended config + parameter-importance chart
7. Click **Open PR** on the proposal — land on the GitHub PR

Hard cap: **7 minutes**. Anything longer undermines the "30-minute tutorial"
promise from `tutorial-first-study.md`.

## Recording playbook (transferred from the deferral conversation)

### Pre-record checklist

```bash
make down && rm -rf ./data
brew services restart docker  # only if Docker has been up for days
cp .env.example .env  # if not already
echo "sk-…" > ./secrets/openai_key
chmod 644 ./secrets/openai_key
open docs/08_guides/tutorial-first-study.md
```

Cosmetic prep:

- Terminal font size **18+** (`Cmd+=` a few times)
- Browser zoom **125%**
- Hide system menu bar + dock (System Settings → Desktop & Dock → Auto-hide)
- Quiet notifications (Focus → Do Not Disturb)

### Tooling decisions (proposed)

| Decision | Recommendation | Why |
|---|---|---|
| Recorder | **QuickTime Player** (Mac, free) | No editing needed if dry-run is clean. ScreenFlow only if you want trim/zoom edits. |
| Hosting | **YouTube unlisted** | No subscription, no expiry, embeddable thumbnail, free analytics. |
| Voiceover | **Captions over voiceover for take 1** | Real-time narration is hard to do cleanly in 7 min. Silent run + on-screen text overlays in post is faster and re-recordable. Voiceover in v2 if it tests well. |

### Timing budget (7 min total = ~50s/beat)

| # | Beat | Target | Notes |
|---|---|---|---|
| 1 | `git clone` | 10s | Cut to already-cloned repo if real clone is slow |
| 2 | `make up` | 30s | Cold pull is 90s — record start, cut to "all 7 containers healthy" |
| 3 | `make migrate` | 15s | Show alembic head |
| 4 | `make seed-clusters` + `make seed-es` | 30s | Show `curl localhost:9200/products/_count` returning 1000 |
| 5 | Create query set + generate judgments | 90s | LLM round-trip — show `judgment_list.status` going `generating → complete` (~30–60s real) |
| 6 | Create study via chat agent | 60s | Open `/chat`, type the tune request, **show the agent proposing** + operator confirming "yes" |
| 7 | Watch trials run + read digest | 90s | Edit-cut the middle of the 3–5 min study runtime; show first 3 trials + jump to completed |
| 8 | Click "Open PR" | 30s | Land on the GitHub PR page in `relyloop-test-configs` |

### Pitfalls to avoid

1. **Don't show your real OpenAI key on screen.** Pre-populate `./secrets/openai_key` off-camera; never `cat` it.
2. **Don't show your real GitHub PAT.** Same.
3. **Don't promise something the tutorial doesn't deliver.** If the demo shows a 30-second study, the tutorial must match. The 10-trial study takes ~3–5 min real time — edit-cut, don't speed up.
4. **5–7 min is a hard cap.**

### Post-record

```bash
# Upload to YouTube as Unlisted
# Title: "RelyLoop v0.X.0 — relevance tuning loop, end-to-end in 5 minutes"
# Description: links to repo + tutorial-first-study.md
```

Wire the URL into `README.md`:

```markdown
[![Watch the 5-minute demo](https://img.youtube.com/vi/<VIDEO_ID>/maxresdefault.jpg)](https://www.youtube.com/watch?v=<VIDEO_ID>)
```

(YouTube auto-generates the maxresdefault thumbnail. Push as a docs PR.)

## Acceptance

- [ ] 5–7 min screencast covering all 8 beats above
- [ ] Hosted on YouTube unlisted (or Loom) with stable URL
- [ ] README's "What it looks like" section restored with the live URL +
      thumbnail
- [ ] No secrets visible on screen at any point (audit by re-watching)

## Related

- [`docs/00_overview/implemented_features/2026_05_12_chore_tutorial_polish/feature_spec.md`](../../../00_overview/implemented_features/2026_05_12_chore_tutorial_polish/feature_spec.md) — origin spec FR-6
- [`docs/03_runbooks/release-checklist.md`](../../../03_runbooks/release-checklist.md) — release-time pointer back here
- [`docs/01_architecture/tech-stack.md`](../../../01_architecture/tech-stack.md) — canonical release matrix (MVP3 themes)
