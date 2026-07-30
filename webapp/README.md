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

## Deploy on Vercel

The repository includes a root `app.py` entrypoint for Vercel's FastAPI
runtime. Import the GitHub repository with:

- Application preset: **FastAPI**
- Root directory: `/`
- Build command: leave blank
- Output directory: leave blank
- Install command: `pip install -r requirements.txt`

Add `OPENAI_API_KEY` and `PEXELS_API_KEY` in Vercel's Environment Variables.
`GITHUB_TOKEN` and `OPENAI_MODEL` are optional.

After the first deployment, open the project's **Storage** tab and connect a
**public Vercel Blob** store. New connections add `BLOB_STORE_ID` and inject a
short-lived OIDC token into Vercel Function requests automatically. Redeploy
once so generated slides and ZIP downloads use durable storage. A legacy
`BLOB_READ_WRITE_TOKEN` is also supported, but is not required for new stores.

Vercel uses generated resource cards instead of Playwright browser captures.
The Remotion repo-video renderer is hidden there because it requires a
persistent worker and the separate local Remotion project. Both features remain
available in the local Mac workflow.

### Modes
- **Type a topic** — researched tutorial, explainer, or resource roundup with validated sources. ✅
- **Video link** — public YouTube/Shorts, TikTok, or Instagram Reel → captions/audio transcript → carousel. ✅

### Repo explainer video (separate section at the bottom of the page)
Paste any GitHub repo URL → **Analyze repo** reads the README + stats via the
GitHub API and drafts a 6-scene script (editable voiceover, name, tagline,
accent colors) → **Generate explainer video** renders a 38s animated 9:16 mp4.

Under the hood (`webapp/repo_video.py`):
- LLM plan via the same OpenAI helper as topic mode; star/fork/language stats
  are injected from the GitHub API so numbers are never hallucinated.
- Voiceover: `edge-tts` (en-US-AndrewNeural), auto re-paced if a line runs long.
- Render: `RepoExplainer` composition in the shared Remotion project
  (`REMOTION_DIR`, default `/Users/eevontan/my-video`,
  `src/RepoExplainerComposition.tsx`) driven entirely by `--props`; the mp4
  lands in `out/` and streams back in the UI. Render runs as a background job,
  polled at `/repo/status/{job}` (takes a few minutes).
- Optional `GITHUB_TOKEN` in `.env` raises the GitHub API rate limit.

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
