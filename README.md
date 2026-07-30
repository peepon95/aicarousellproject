# AI Resource Carousel

Generate aesthetic, full-bleed carousel slides that share AI resources
(Claude skills, GitHub repos, courses, tools) for a personal brand — the
"real photo background + screenshot + caption" look.

## What it does
Pull trending resources → you pick the good ones → fetch a real stock photo
per slide → screenshot each resource page → composite the volkan-style slide
→ export PNGs (and optionally push to Canva to tweak before posting).

## One-time setup (~30 min)

1. **Install Node.js + Claude Code** (if using the agent workflow):
   https://docs.claude.com  →  then `npm install -g @anthropic-ai/claude-code`

2. **Python deps:**
   ```
   pip install pillow playwright requests python-dotenv
   playwright install chromium
   ```

3. **API keys:** copy `.env.example` to `.env` and add your free Pexels key
   (instant, from https://www.pexels.com/api/). GitHub token optional.

4. **Backgrounds:** the skill auto-fetches + caches photos into `backgrounds/`.
   Over time this becomes your curated visual library. Tweak the search terms
   in `run.py` (e.g. "cozy interior warm light", "autumn forest moody") to
   lock in your aesthetic.

## Run it

**With Claude Code (recommended):** open this folder in Claude Code and say
*"make me a 5-slide carousel about free AI courses."* The agent runs the
pipeline, shows you a shortlist to approve, then builds the slides.

**Standalone:** `python .claude/skills/ai-resource-carousel/run.py`

## Deploy the web studio on Vercel

Import this repository with the **FastAPI** preset, keep the root directory at
`/`, and leave the build/output overrides disabled. Add `OPENAI_API_KEY` and
`PEXELS_API_KEY` in Vercel's Environment Variables.

After the first deployment, connect a **public Vercel Blob** store from the
project's Storage tab and redeploy. Blob storage keeps generated slides and ZIP
downloads available across serverless requests. The hosted version uses
generated resource preview cards instead of Playwright screenshots and hides
the local-only Remotion video renderer.

See `webapp/README.md` for the complete deployment settings and local web-app
commands.

## The 20% that stays yours
- Which resources make the cut (your taste).
- Final Canva tweaks before posting.
- Your background search terms (your visual signature).

## Attribution
Pexels asks you to credit photographers. The fetch step records
"Photo by X on Pexels" per image in `backgrounds/_attribution.json` — drop
these credits in your caption or a final slide.

## Files
- `.claude/skills/ai-resource-carousel/SKILL.md` — pipeline definition
- `fetch_pexels.py` — free stock photo fetch + cache + attribution
- `capture_screenshot.py` — Playwright page screenshots
- `compose_fullbleed.py` — the full-bleed slide compositor
- `run.py` — orchestrator (pull → pick → build)
- `voice.md` — your tone rules (edit over time)
- `sources.yaml` — configurable pull sources
