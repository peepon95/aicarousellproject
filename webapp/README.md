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

Topic research uses the Responses API in background mode so OpenAI web search
can finish without a long-lived read timing out. The local defaults allow ten
minutes and retry two transient status checks. Override them when needed with
`OPENAI_BACKGROUND_MODE`, `OPENAI_TIMEOUT_SECONDS`, and `OPENAI_MAX_RETRIES`.

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
- **Type a topic**: choose Auto, YouTube videos, YouTube channels, Substack
  articles, GitHub repositories, official tools, or Mixed public sources.
  Strict modes reject every result outside the selected lane. Mixed mode uses
  OpenAI web research and then applies the validator for each returned platform.
- **Video link**: public YouTube/Shorts, TikTok, or Instagram Reel, then
  captions or audio transcript to carousel.
- **Upload recording**: local MP4, MOV, M4V, WebM, or MKV up to 300 MB. The app
  samples up to 12 frames, transcribes speech, analyzes both, and deletes the
  temporary upload. This requires `ffmpeg` and is local-only.

### Source previews and visual style

Playwright uses a source-specific crop instead of one generic browser crop:

- GitHub captures the repository name, navigation, files, and About panel.
- YouTube videos use verified oEmbed metadata and the real public thumbnail;
  channels use the recognizable channel header.
- Substack captures the article header and readable article body.
- Tool sites capture the main product surface.

The default `Editorial source card` treatment is based on the supplied
reference system: real source card, tactile photographic background, quiet
italic source credit. Choose 3:4 at 1080 × 1440, 9:16 at 1080 × 1920, or the
older 4:5 at 1080 × 1350. `Detailed explainer card` keeps the existing title,
description, and takeaway layout. Both treatments use one distinct cover photo,
then lock a second exact background across every source slide and CTA.

The default export is one standalone carousel. Covers contain no Part 1/2 badge
or list count. Their topic phrase uses an italic serif and the remaining hook
uses an oversized bold sans serif, following the supplied reference covers.

### Telegram carousel agent

The optional private Telegram agent supports two workflows:

- At 9 PM Malaysia time, Vercel Cron calls `/telegram/daily` and sends one AI
  topic suggestion with **Approve and build** and **Another idea** buttons.
- Any normal message sent to the bot is treated as a topic. Approvals and
  messages dispatch the `Telegram carousel agent` GitHub Action, which performs
  the slower research and rendering, then sends every slide plus a ZIP back to
  Telegram.

Telegram keeps the preview images and ZIP in the chat. On iPhone or Android,
open the ZIP and choose **Save to Files**. Telegram's own automatic media
download setting controls whether previews are also cached on the phone.

#### Private setup

1. Create a bot with Telegram's `@BotFather` and copy the token.
2. Add these Vercel production environment variables first:
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `GITHUB_DISPATCH_TOKEN`,
   and `CRON_SECRET`. Use a fine-grained GitHub token restricted to
   `aicarousellproject` with **Contents: Read and write**, which is the permission
   GitHub requires for the repository-dispatch endpoint. The Telegram webhook
   secret must use only letters, numbers, underscores, or hyphens. Redeploy
   after adding them.
3. Add GitHub Actions repository secrets: `TELEGRAM_BOT_TOKEN`,
   `OPENAI_API_KEY`, and `PEXELS_API_KEY`. `OPENAI_MODEL` is optional.
4. Register the webhook once from a machine whose `.env` contains the bot token
   and the same webhook secret:

   ```bash
   python -m webapp.telegram_worker setup-webhook \
     --url https://aicarousellproject.vercel.app
   ```

5. Send `/start` to the bot. It replies with your chat ID. Add that value as
   `TELEGRAM_CHAT_ID` and `TELEGRAM_ALLOWED_CHAT_ID` in Vercel, and as the
   `TELEGRAM_CHAT_ID` GitHub Actions secret. Redeploy once more. Restricting the
   allowed chat ID makes the bot private to you.

The cron expression in `vercel.json` is `0 13 * * *`: 13:00 UTC is 21:00 in
Malaysia. The cron route requires Vercel's `Authorization: Bearer CRON_SECRET`
header. The webhook separately verifies Telegram's secret-token header.
Repository-dispatch workflows only become callable after this workflow file is
on the repository's default branch, so merge and deploy the agent branch only
after its private secrets are ready.

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
