---
name: ai-resource-carousel
description: >
  Research and generate source-accurate editorial social carousels about AI
  tools, GitHub projects, YouTube videos or channels, Substack articles,
  motivation, and self-education. Use when the user requests a carousel,
  content roundup, reference-led visual style, video breakdown, or uploaded
  screen-recording analysis for their personal brand.
---

# AI Resource Carousel

## What this does
Turns the tedious 80% of content creation into one run, while keeping the
human 20% (taste + hook voice) with the user. Never fully auto-post: the user
approves the shortlist and tweaks hooks before anything is generated.

## The pipeline (run in order)

### 1. PULL: gather live candidates
Use real APIs, never memory, for anything trend-based. Default sources:
- **GitHub trending**: `https://api.github.com/search/repositories?q={topic}&sort=stars&order=desc&per_page=15`
  Good topics: `claude+skills`, `mcp+server`, `llm+agent`, `ai+tools`.
- **Hugging Face**: `https://huggingface.co/api/models?sort=likes&limit=15`
  and `.../api/datasets` for datasets.
- **Anthropic skills / docs**: web_search `site:github.com/anthropics` or docs.claude.com.
- Optionally: Hacker News Algolia API `https://hn.algolia.com/api/v1/search?query=llm&tags=story`.
- **YouTube videos**: web search with `site:youtube.com/watch` or
  `site:youtube.com/shorts`, then verify the title, channel, description, and
  visible topic match the editorial theme. Require a successful YouTube oEmbed
  response containing both a public title and thumbnail. A watch-page HTTP 200
  is not sufficient because private and unavailable players also return 200.
  A valid YouTube URL alone does not prove that a result is a video essay.
- **YouTube channels**: web search with `site:youtube.com/@`, then verify the
  channel description and recent uploads match the requested niche.
- **Substack articles**: web search with `site:*.substack.com/p/`, then verify
  the individual title, writer, publication, and article excerpt.

Select one source lane before research and enforce it after generation:

- `mixed_sources`: use OpenAI web research across verified YouTube, Substack,
  GitHub, and official product sources. Validate each result with the adapter
  for its actual platform before it reaches the shortlist.
- `youtube_video`: accept only `youtube.com/watch`, `/shorts/`, `/live/`, or `youtu.be`.
- `youtube_channel`: accept only `youtube.com/@handle`, `/channel/`, `/c/`, or `/user/`.
- `substack_article`: accept only individual articles on Substack, never publication home, archive, or subscribe pages.
- `github_repo`: accept only canonical owner/repository pages.
- `tool_website`: accept only official product pages, never listicles or affiliate roundups.

If the user says only YouTube, Substack, GitHub, or tools, treat “only” as a
hard filter. Never fill a weak shortlist with a different source type. Return a
clear “not enough valid sources” message instead.

Dedupe by name. Capture: name, description, count, URL, author, publication
date, evidence, and screenshot target. Evidence must prove semantic fit, not
just platform membership. For “projects I can run,” fetch the README and
require an exact Docker, npm, uv, Python, Cargo, Go, or Make command. Reject
libraries, lists, and source archives without a runnable path.

For a carousel derived from one video, accept public YouTube videos/Shorts, TikTok posts, and
Instagram Reels. Prefer platform captions when available. Otherwise extract the
audio and transcribe it, then base the carousel only on the transcript. Clearly
reject private, login-only, removed, or region-blocked posts instead of guessing.
For a roundup of several videos, do not transcribe every recommendation. Verify
each item from its title, channel, description, thumbnail, and supporting page.

### 2. SHORTLIST: user picks
Present 8–12 candidates as a numbered list with stars + one-liner.
Ask the user which 5–7 make the cut. DO NOT proceed without their pick —
this is where their brand taste lives.
Candidates must start unselected. Validate every supporting URL before showing
it; discard broken or invented resources. A 401/403 may still indicate a real,
protected page, but malformed domains and unreachable links must not pass.

### 3. DRAFT: copy in their voice
For each chosen resource write:
- **Slide hook** (≤7 words, punchy, lowercase optional — match the reference
  style e.g. "your phone is the reason you have no identity").
- **One-line description** (what it is + why it matters, ≤20 words).
Also draft: cover-slide hook, and the post caption with 3–5 hashtags.
Keep the user's voice notes in `voice.md` (see below) and read it every run.
Do not use em dashes or en dashes. Avoid stacked fragments, fake contrast,
generic claims, “game changer,” “unlock,” “delve,” and “revolutionize.” A
recommendation must say what it is and why this specific viewer might care.

Keep each draft as one standalone carousel by default. Do not add Part 1,
Part 2, numbered series language, or a part badge to the cover. Create two
separate exports only when the user explicitly chooses that option.

### 4. ART: build the slide look
The screenshot or resource card is the visual priority. Use a clean warm-neutral
canvas when the screenshot already has strong color or detail. Add an ambient
photographic background only when it improves an otherwise sparse slide (cover,
missing screenshot, or intentionally minimal resource). Never add a photo merely
to fill space.

Two ways to make backgrounds when one is actually useful:
- Fastest: a solid/gradient dark aesthetic bg generated with PIL (offline,
  reliable) — see `generate_slides.py`.
- Richer: if an image-gen skill/tool is available, prompt for "cozy sunlit
  wood-panel room, warm bokeh, cinematic, no text" style plates.
Read `references/editorial-style.md` when using the editorial reference mode.
Choose the canvas intentionally:

- 1080 × 1440 for Substack, reading lists, GitHub projects, tools, and general
  editorial photo carousels.
- 1080 × 1920 for YouTube video or channel lists and story-first posts.
- 1080 × 1350 only when the user explicitly wants Instagram 4:5.

Screenshot rules:
- Capture the real public homepage for products and websites, not only GitHub.
- Detect block/challenge pages (Cloudflare, "verify you are human", HTTP 4xx)
  and never use them as the resource image.
- When automation is blocked, render an honest branded metadata preview with
  the resource name, one-line description and domain. Do not fabricate a UI.
- Crop around recognizable primary content. Use the repository body for
  GitHub, the channel header for YouTube channels, the article for Substack,
  and the main product surface for tools. Do not show browser chrome, cookie
  dialogs, sign-in walls, or blank hero space when useful content exists.
- For individual YouTube videos, never use Playwright watch-page capture. Build
  the source card from verified oEmbed metadata and the real public thumbnail.
  This prevents consent, private-video, unavailable-video, and regional error
  states from entering the carousel.
- Capture at a 1280-pixel browser viewport with a high-density scale. Keep the
  repository name and About panel, channel identity, article title and writer,
  or product headline in frame. Prefer the main semantic container.
- Do not repeat the same description under the title and in the reason block.
  Detail slides use the resource name/hook at top and one distinct, concrete
  outcome sentence below the screenshot.
- For a carousel derived from one YouTube video, repeat the verified thumbnail,
  title, channel, and URL source card on every lesson slide. The card is source
  attribution, not filler. Never allow a YouTube-derived slide to render blank
  or text-only. For non-YouTube video sources, include a verified official
  website, repository, or interface only when that entity is discussed.

For uploaded video or screen recordings, sample visible frames and transcribe
speech. Use both signals. Do not infer a product, command, URL, or claim that is
not visible or spoken. Delete the temporary upload after analysis.

### 5. EXPORT: send to Canva for editing
The user wants to tweak before posting, so hand off editable slides:
- Call `Canva:request-outline-review` with one page per slide (title = hook,
  description = the one-liner). After the user approves in the widget, call
  `Canva:generate-design-structured` with design_type "presentation".
- Also save the PNGs locally via present_files as a backup / reference.

## Files in this skill
- `generate_slides.py` — offline PNG generator for the card-on-bg look.
- `voice.md` — the user's tone rules; read + update every run.
- `sources.yaml` — configurable list of pull sources & topics.

## Rules
- Live data only for trends; never invent star counts or repo names.
- Always stop at step 2 for human approval.
- Match the reference aesthetic: warm editorial palette, big bold hook, clean
  hierarchy, and backgrounds only where they add useful visual context.
- The first slide needs a generated, specific hook. Do not show a swipe
  button or 1/4-style page counters anywhere.
- Treat the background prompt as optional. If it is blank, do not call a photo
  API and use the clean neutral canvas. If supplied, fetch exactly two distinct
  photographs: one used only for the cover, and one repeated across every source
  card and CTA. Do not fetch a new photograph for each recommendation.
- Before building, allow direct edits to each slide hook, explanation, and
  practical takeaway. Also accept a natural-language revision prompt for the
  entire draft while preserving validated source URLs and existing selections.
- One resource per slide. Cover slide first. Keep captions skimmable.
