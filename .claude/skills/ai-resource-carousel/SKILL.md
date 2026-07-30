---
name: ai-resource-carousel
description: >
  Generate aesthetic social-media carousels that share AI resources (Claude
  skills, GitHub repos, courses, tools). Pulls live trending sources, drafts
  hook copy in the user's voice, produces cozy "attached-card on ambient
  background" slide art, and exports editable slides to Canva. Trigger when the
  user wants to make a carousel, content post, or resource roundup about AI
  tools/skills/repos for their personal brand.
---

# AI Resource Carousel

## What this does
Turns the tedious 80% of content creation into one run, while keeping the
human 20% (taste + hook voice) with the user. Never fully auto-post: the user
approves the shortlist and tweaks hooks before anything is generated.

## The pipeline (run in order)

### 1. PULL — gather live candidates
Use real APIs, never memory, for anything trend-based. Default sources:
- **GitHub trending**: `https://api.github.com/search/repositories?q={topic}&sort=stars&order=desc&per_page=15`
  Good topics: `claude+skills`, `mcp+server`, `llm+agent`, `ai+tools`.
- **Hugging Face**: `https://huggingface.co/api/models?sort=likes&limit=15`
  and `.../api/datasets` for datasets.
- **Anthropic skills / docs**: web_search `site:github.com/anthropics` or docs.claude.com.
- Optionally: Hacker News Algolia API `https://hn.algolia.com/api/v1/search?query=llm&tags=story`.

Dedupe by name. Capture: name, one-line description, star/like count, URL.

For video-led carousels, accept public YouTube videos/Shorts, TikTok posts, and
Instagram Reels. Prefer platform captions when available. Otherwise extract the
audio and transcribe it, then base the carousel only on the transcript. Clearly
reject private, login-only, removed, or region-blocked posts instead of guessing.

### 2. SHORTLIST — user picks
Present 8–12 candidates as a numbered list with stars + one-liner.
Ask the user which 5–7 make the cut. DO NOT proceed without their pick —
this is where their brand taste lives.
Candidates must start unselected. Validate every supporting URL before showing
it; discard broken or invented resources. A 401/403 may still indicate a real,
protected page, but malformed domains and unreachable links must not pass.

### 3. DRAFT — copy in their voice
For each chosen resource write:
- **Slide hook** (≤7 words, punchy, lowercase optional — match the reference
  style e.g. "your phone is the reason you have no identity").
- **One-line description** (what it is + why it matters, ≤20 words).
Also draft: cover-slide hook, and the post caption with 3–5 hashtags.
Keep the user's voice notes in `voice.md` (see below) and read it every run.

Before presenting the draft, make an editorial series decision. Split when one
carousel would feel dense or there are two coherent arcs; seven or more tools or
resources should default to two balanced parts. Give every part its own cover
and short part title. Do not create an orphan part with only one slide.

### 4. ART — build the slide look
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
Card = rounded dark rectangle, resource title bold, description below,
star count + source badge. Export PNGs at 1080x1350 (IG 4:5).

Screenshot rules:
- Capture the real public homepage for products and websites, not only GitHub.
- Detect block/challenge pages (Cloudflare, "verify you are human", HTTP 4xx)
  and never use them as the resource image.
- When automation is blocked, render an honest branded metadata preview with
  the resource name, one-line description and domain. Do not fabricate a UI.
- Do not repeat the same description under the title and in the reason block.
  Detail slides use the resource name/hook at top and one distinct, concrete
  outcome sentence below the screenshot.
- For video-derived slides, decide per slide whether a screenshot materially
  helps. Include a verified real website/repository/interface screenshot only
  when that entity is discussed. Never repeat the source video page as filler;
  use the editorial photo layout without a screenshot for conceptual lessons.

### 5. EXPORT — send to Canva for editing
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
- The first slide needs a generated, specific viral hook. Do not show a swipe
  button or 1/4-style page counters anywhere.
- Treat the background prompt as optional. If it is blank, do not call a photo
  API and use the clean neutral canvas. If supplied, fetch distinct aesthetically
  relevant photos for the cover and every detail slide, then apply the same
  editorial grade across the set.
- Before building, allow direct edits to each slide hook, explanation, and
  practical takeaway. Also accept a natural-language revision prompt for the
  entire draft while preserving validated source URLs and existing selections.
- One resource per slide. Cover slide first. Keep captions skimmable.
