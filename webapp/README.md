# AI Carousel Studio (local web app)

A localhost UI + daily agent wrapped around the `ai-resource-carousel` skill engine
(GitHub pull → Pexels background → Playwright screenshot → PIL slide compositor).

## Run the app
```bash
# from the project root
.venv/bin/uvicorn webapp.app:app --reload --port 8000
# open http://localhost:8000
```

Flow: pick a **mode** → **Find resources** → check/uncheck the shortlist and tweak
each hook → **Build carousel** → previews render, click to open/download PNGs (in `out/`).

### Modes
- **Type a topic** — e.g. "vibe coding tools" → trending GitHub repos → carousel. ✅
- **Paste links** — GitHub repos / tool URLs, one per line → one slide each. ✅
- **Reference mimic** — paste a TikTok/IG URL → copy its look + hook structure. 🚧 Phase 2, stubbed.

## Daily draft agent (Mac cron, draft-only — never auto-posts)
```bash
.venv/bin/python webapp/daily_agent.py                 # build one draft now
.venv/bin/python webapp/daily_agent.py --install-cron 08:00   # daily at 8am
```
Drafts land in `inbox/YYYY-MM-DD/` with a `manifest.json`. Review + rewrite hooks
before posting — taste stays human.

## Known polish items
- Long title hooks overflow the slide (compose_fullbleed draws the title on one
  line with no wrap/auto-shrink). Fix in `compose_fullbleed.py:build`.
- GitHub topic search returns some mislabeled high-star repos — add a quality filter.
- Reference-mimic (Phase 2) not wired: needs post screenshot → palette extract +
  best-effort caption scrape for hook structure.
