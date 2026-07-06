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

### 2. SHORTLIST — user picks
Present 8–12 candidates as a numbered list with stars + one-liner.
Ask the user which 5–7 make the cut. DO NOT proceed without their pick —
this is where their brand taste lives.

### 3. DRAFT — copy in their voice
For each chosen resource write:
- **Slide hook** (≤7 words, punchy, lowercase optional — match the reference
  style e.g. "your phone is the reason you have no identity").
- **One-line description** (what it is + why it matters, ≤20 words).
Also draft: cover-slide hook, and the post caption with 3–5 hashtags.
Keep the user's voice notes in `voice.md` (see below) and read it every run.

### 4. ART — build the slide look
The signature look = ambient photographic background + a floating "card"
holding the resource. Two ways to make backgrounds:
- Fastest: a solid/gradient dark aesthetic bg generated with PIL (offline,
  reliable) — see `generate_slides.py`.
- Richer: if an image-gen skill/tool is available, prompt for "cozy sunlit
  wood-panel room, warm bokeh, cinematic, no text" style plates.
Card = rounded dark rectangle, resource title bold, description below,
star count + source badge. Export PNGs at 1080x1350 (IG 4:5).

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
- Match the reference aesthetic: warm ambient bg, dark floating card,
  big bold hook, tiny source attribution.
- One resource per slide. Cover slide first. Keep captions skimmable.
