#!/usr/bin/env python3
"""
Thin wrapper around the ai-resource-carousel skill scripts so the web app and
the daily agent share one engine. Everything reads/writes the project-root
folders (backgrounds/, screenshots/, out/) exactly like the CLI skill does.
"""
import os, re, json, sys, urllib.request, urllib.parse, urllib.error, tempfile
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_VERCEL = bool(os.environ.get("VERCEL"))
DATA_ROOT = os.environ.get("AICAROUSEL_DATA_DIR", "").strip()
if not DATA_ROOT:
    DATA_ROOT = (
        os.path.join(tempfile.gettempdir(), "aicarousel")
        if IS_VERCEL else PROJECT_ROOT
    )
os.environ.setdefault("AICAROUSEL_DATA_DIR", DATA_ROOT)

# ROOT remains the source checkout for backwards compatibility with the local
# cron helper. Generated media is written under DATA_ROOT instead.
ROOT = PROJECT_ROOT
SKILL = os.path.join(PROJECT_ROOT, ".claude", "skills", "ai-resource-carousel")
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
sys.path.insert(0, SKILL)

from fetch_pexels import fetch_background, fetch_backgrounds  # noqa: E402
from capture_screenshot import capture             # noqa: E402
import compose_fullbleed as C                      # noqa: E402

OUT = os.path.join(DATA_ROOT, "out")
os.makedirs(OUT, exist_ok=True)

# Product sites belong beside open-source projects in a useful AI-tool roundup.
# Keep this small and editorial: these are real homepages that screenshot well.
PRODUCTS = [
    {"name": "Lovable", "url": "https://lovable.dev", "desc": "Build full-stack apps by describing what you want.", "why": "Best when you want a polished MVP without stitching the frontend and backend together yourself.", "tags": "vibe coding app builder website no code"},
    {"name": "Replit", "url": "https://replit.com", "desc": "Turn an idea into a deployed app from your browser.", "why": "Use it when you want to code, test and publish without setting up a local development environment.", "tags": "vibe coding app builder cloud ide coding"},
    {"name": "Bolt", "url": "https://bolt.new", "desc": "Prompt, run, edit and deploy web apps in one place.", "why": "Great for testing an app idea quickly because the preview and code stay in the same workflow.", "tags": "vibe coding app builder website no code"},
    {"name": "v0", "url": "https://v0.dev", "desc": "Generate polished interfaces and working web apps with AI.", "why": "Use it to turn a rough UI idea into a strong first draft you can refine instead of starting blank.", "tags": "vibe coding ui design app builder website"},
    {"name": "Cursor", "url": "https://cursor.com", "desc": "An AI code editor for understanding and changing real codebases.", "why": "It is most useful once your project grows and you need AI that can reason across many existing files.", "tags": "vibe coding code editor developer"},
    {"name": "Windsurf", "url": "https://windsurf.com", "desc": "An agentic IDE that can plan and implement changes with you.", "why": "Choose it for longer coding tasks where you want the agent to keep context while it works across files.", "tags": "vibe coding code editor developer"},
    {"name": "Framer", "url": "https://framer.com", "desc": "Design and publish expressive websites without a handoff.", "tags": "website design no code landing page"},
    {"name": "Perplexity", "url": "https://perplexity.ai", "desc": "Research the web with concise answers and linked sources.", "tags": "research search productivity ai tool"},
]


def _product_matches(topic, n=6):
    words = set(re.findall(r"[a-z0-9]+", topic.lower()))
    scored = []
    for item in PRODUCTS:
        haystack = set(re.findall(r"[a-z0-9]+", item["tags"].lower()))
        score = len(words & haystack)
        if score:
            r = {k: v for k, v in item.items() if k != "tags"}
            r.update({"stars": 0, "kind": "product"})
            scored.append((score, r))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [r for _, r in scored[:n]]


def pull_resources(topic, n=12):
    """Blend polished product websites with relevant GitHub projects."""
    products = _product_matches(topic, min(6, n))
    repos = pull_github(topic, max(0, n - len(products)))
    return products + repos


def cover_hook_for(topic, count=5):
    subject = topic.strip().rstrip(".?!") or "AI tools"
    return f"{count} {subject} that feel like cheating"


def _openai_json(prompt, use_web_search=True):
    # Re-read the local file so a key pasted while the dev server is running
    # is picked up without requiring a restart.
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Add OPENAI_API_KEY to .env to generate topic or video carousels")
    request_data = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-5.2"),
        "input": prompt + "\nReturn valid JSON only, with no markdown fences.",
    }
    if use_web_search:
        request_data["tools"] = [{"type": "web_search"}]
    payload = json.dumps(request_data).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    text = data.get("output_text")
    if not text:
        chunks = []
        for item in data.get("output", []):
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    chunks.append(part.get("text", ""))
        text = "".join(chunks)
    return json.loads(text)


def _url_is_valid(url):
    if not url or not url.startswith(("http://", "https://")):
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.status < 400
    except urllib.error.HTTPError as e:
        # Auth/security responses still prove that the domain and page exist.
        return e.code in (401, 403, 405, 429)
    except Exception:
        return False


def generate_topic_carousel(topic, count=7):
    """Research any topic and draft selectable carousel slides."""
    source_match = re.search(r"https?://[^\s]+", topic)
    source_url = source_match.group(0).rstrip(".,)") if source_match else ""
    guided_single_source = bool(source_url and re.search(
        r"\b(what is|how to|install|setup|configure|configuration|use cases?|guide|tutorial)\b",
        topic, re.I))
    github_context = []
    if source_url and "github.com/" in source_url.lower():
        try:
            github_context = [resource_from_url(source_url)]
        except Exception as e:
            print("GitHub URL context unavailable:", e)
    elif re.search(r"\b(github|repos?|repositories|open[ -]source)\b", topic, re.I):
        try:
            github_context = pull_github(topic, min(10, count + 2))
        except Exception as e:
            print("GitHub context unavailable:", e)
    github_note = (f"\nVERIFIED GITHUB API CANDIDATES:\n{json.dumps(github_context, ensure_ascii=False)}\n"
                   if github_context else "")
    tutorial_note = ""
    if guided_single_source:
        tutorial_note = f"""
This is a single-source guide about {source_url}. Create 5-6 distinct slides,
not one summary slide. Cover, in a logical order: what it is, prerequisites,
installation, configuration or verification, practical use cases, and an
important limitation or tip when supported by the source. Multiple slides may
use the same source URL because they are separate tutorial steps. Set
carousel_type to tutorial. Do not invent commands absent from official sources.
"""
    prompt = f"""Create a factual Instagram carousel outline about: {topic}
First infer the user's intent. If the query asks for tools, plugins, apps,
websites, resources, or alternatives, create a curated list of distinct named
products—one actual product per slide, with its official product URL. Do not
return generic lessons, installation steps, list-of-lists repositories, or
multiple slides about the same tool. If the query starts with how to/install,
create an ordered tutorial instead. Otherwise create a focused explainer.
Research current primary/official sources.{tutorial_note}
For resource lists, every slide must cover a distinct canonical product. Never
list a product page, connector page, documentation page, and help-center page
separately when they describe the same core workflow. Compare the complete list
before returning it and remove semantic duplicates. This restriction does not
apply to distinct steps in a tutorial about one product or repository.
Return an object with carousel_type (resource_list, tutorial, or explainer),
cover_hook (specific, curiosity-driven, not clickbait),
split_recommended, part_count, and slides (maximum {count}). Split only when one
carousel would feel dense or when there are two clear editorial arcs. If there
are 7 or more tools/resources, use two parts. Each slide needs: name (short slide heading),
desc (one accurate sentence explaining what the tool, GitHub repo, website, or
concept literally does), why (one practical best-use case, different from desc),
url (a valid supporting source), kind (step, insight, or resource), part
(1 or 2), part_title (short shared title for that part), needs_screenshot
(true for named tools, websites, repos, or documentation), and visual_url
(normally the same official URL).
Also return dedupe_key for every resource-list slide: a lowercase canonical
identifier for the actual product, independent of page title or URL.
For GitHub repos, desc must summarize the repository's actual purpose from its
README/about text, not a broad category guess. For products, desc must explain
the product workflow briefly. For a tutorial, order the steps. Do not force
GitHub results unless directly relevant.{github_note}"""
    result = _openai_json(prompt)
    slides = []
    raw_slides = result.get("slides", [])
    carousel_type = str(result.get("carousel_type", "")).strip().lower()
    if carousel_type not in ("resource_list", "tutorial", "explainer"):
        carousel_type = "tutorial" if guided_single_source else "resource_list"
    force_two_parts = carousel_type == "resource_list" and len(raw_slides) >= 7
    seen_subjects = set()
    seen_step_names = set()
    valid_urls = {}
    for idx, slide in enumerate(raw_slides):
        url = str(slide.get("url", "")).strip()
        if url not in valid_urls:
            valid_urls[url] = _url_is_valid(url)
        if not valid_urls[url]:
            continue
        name = str(slide.get("name", "")).strip()[:90]
        dedupe_key = str(slide.get("dedupe_key", "")).strip().lower()
        dedupe_key = re.sub(r"[^a-z0-9]+", "-", dedupe_key or name.lower()).strip("-")
        if carousel_type == "resource_list":
            canonical_url = url.lower().split("#", 1)[0].rstrip("/")
            subject_keys = {dedupe_key, canonical_url}
            if seen_subjects & subject_keys:
                continue
            seen_subjects.update(subject_keys)
        else:
            step_key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            if step_key in seen_step_names:
                continue
            seen_step_names.add(step_key)
        part = int(slide.get("part", 1) or 1)
        if force_two_parts and part == 1:
            part = 1 if idx < (len(raw_slides) + 1) // 2 else 2
        visual_url = str(slide.get("visual_url") or url).strip()
        slides.append({
            "name": name,
            "desc": str(slide.get("desc", "")).strip()[:220],
            "why": str(slide.get("why", "")).strip()[:220],
            "url": url, "stars": 0,
            "kind": str(slide.get("kind", "insight")),
            "part": max(1, min(2, part)),
            "part_title": str(slide.get("part_title", "")).strip()[:70],
            "needs_screenshot": bool(slide.get("needs_screenshot", True)),
            "visual_url": visual_url if _url_is_valid(visual_url) else url,
            "dedupe_key": dedupe_key,
        })
    if not slides:
        raise RuntimeError("No valid sourced slides were returned. Try a more specific topic.")
    return {"candidates": slides,
            "cover_hook": result.get("cover_hook") or cover_hook_for(topic, len(slides)),
            "carousel_type": carousel_type,
            "part_count": 2 if any(s["part"] == 2 for s in slides) else 1}


def revise_carousel(resources, cover_hook, instruction):
    """Prompt-edit an existing draft without changing its validated sources."""
    compact = []
    for i, r in enumerate(resources):
        compact.append({"id": i, "name": r.get("name", ""),
                        "hook": r.get("hook", ""), "desc": r.get("desc", ""),
                        "why": r.get("why", ""), "kind": r.get("kind", ""),
                        "what_title": r.get("what_title", "WHAT IT DOES"),
                        "why_title": r.get("why_title", "WHY YOU'LL NEED IT"),
                        "dedupe_key": r.get("dedupe_key", ""),
                        "part": r.get("part", 1), "part_title": r.get("part_title", ""),
                        "needs_screenshot": r.get("needs_screenshot", True),
                        "visual_url": r.get("visual_url", "")})
    prompt = f"""Edit this carousel draft according to the user's instruction.
USER INSTRUCTION: {instruction}
CURRENT COVER HOOK: {cover_hook}
CURRENT SLIDES: {json.dumps(compact, ensure_ascii=False)}

Return cover_hook and slides. Keep every slide id exactly once and in the same
order unless the instruction explicitly asks to remove or reorder slides.
For resource-list slides, keep each named product distinct. Make hooks specific,
short, and non-generic. desc explains what the tool/repo/product actually does
briefly; why gives a different concrete best-use case. Do not invent new factual
claims or URLs."""
    result = _openai_json(prompt, use_web_search=False)
    originals = {i: r for i, r in enumerate(resources)}
    revised = []
    for item in result.get("slides", []):
        try:
            idx = int(item.get("id"))
        except Exception:
            continue
        if idx not in originals:
            continue
        base = dict(originals[idx])
        for field in ("name", "hook", "desc", "why", "what_title", "why_title",
                      "dedupe_key", "kind",
                      "part_title", "visual_url"):
            if field in item:
                base[field] = str(item[field]).strip()
        if "part" in item:
            base["part"] = max(1, min(2, int(item["part"] or 1)))
        if "needs_screenshot" in item:
            base["needs_screenshot"] = bool(item["needs_screenshot"])
        revised.append(base)
    if not revised:
        raise RuntimeError("The edit did not return any usable slides")
    return {"resources": revised,
            "cover_hook": str(result.get("cover_hook") or cover_hook).strip()}


def _youtube_id(url):
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.netloc in ("youtu.be", "www.youtu.be"):
        video_id = parsed.path.strip("/")
    elif "youtube.com" in parsed.netloc:
        video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        if not video_id and parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/")[2]
    else:
        video_id = ""
    return video_id if re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_id or "") else ""


def _video_transcript(url):
    """Use existing YouTube captions first; otherwise download public audio
    from YouTube, TikTok, or Instagram and transcribe it."""
    video_id = _youtube_id(url)
    if video_id:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            transcript = YouTubeTranscriptApi().fetch(
                video_id, languages=("en", "en-US", "en-GB"))
            text = " ".join(snippet.text for snippet in transcript)
            if len(text) >= 80:
                return text, "YouTube captions"
        except Exception:
            pass

    host = urllib.parse.urlparse(url.strip()).netloc.lower().replace("www.", "")
    allowed = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com")
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise RuntimeError("Use a YouTube, YouTube Shorts, TikTok, or Instagram Reel URL")

    from yt_dlp import YoutubeDL
    from openai import OpenAI
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is empty in the saved .env file")
    with tempfile.TemporaryDirectory(prefix="carousel-video-") as tmp:
        template = os.path.join(tmp, "source.%(ext)s")
        options = {
            "format": "bestaudio/best", "outtmpl": template,
            "noplaylist": True, "quiet": True, "no_warnings": True,
            "postprocessors": [{"key": "FFmpegExtractAudio",
                                 "preferredcodec": "mp3", "preferredquality": "64"}],
        }
        try:
            with YoutubeDL(options) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as e:
            raise RuntimeError(
                "The platform would not provide this public video. Private, login-only, "
                f"region-blocked, or removed posts cannot be imported. ({e})") from e
        audio = os.path.join(tmp, "source.mp3")
        if not os.path.exists(audio):
            matches = [os.path.join(tmp, n) for n in os.listdir(tmp) if n.endswith(".mp3")]
            audio = matches[0] if matches else ""
        if not audio or not os.path.exists(audio):
            raise RuntimeError("Audio extraction did not produce a usable file")
        if os.path.getsize(audio) > 24 * 1024 * 1024:
            raise RuntimeError("The extracted audio is too long to transcribe in one request")
        with open(audio, "rb") as f:
            result = OpenAI(api_key=key).audio.transcriptions.create(
                model="gpt-4o-mini-transcribe", file=f)
        text = result.text.strip()
        if len(text) < 80:
            raise RuntimeError("The video did not contain enough spoken content")
        return text, "audio transcription"


def generate_video_carousel(url, count=7):
    """Turn a supported public short-form or long-form video into slides."""
    text, transcript_source = _video_transcript(url.strip())
    # Keep within a practical request size while retaining the full arc.
    text = text[:45000]
    prompt = f"""Turn this video transcript into a useful Instagram carousel.
Do not merely summarize chronologically: identify the strongest thesis, key
lessons, and actionable steps. Create at most {count} slides. Return an object
with cover_hook, split_recommended, part_count, and slides. Split when there are
two strong editorial arcs or the content would be too dense in one carousel;
seven or more items should become two parts. Each slide needs
name (short heading), desc (one accurate sentence explaining what the referenced
tool, website, repo, concept, or step actually does), why (a distinct practical takeaway),
url (always {url}), kind (insight or step), part, part_title, needs_screenshot,
and visual_url. Set needs_screenshot true only when that slide discusses a
specific website, product, GitHub repository, or interface whose real screenshot
would improve understanding. Resolve visual_url to its official page. Otherwise
set it false and visual_url to an empty string. Never repeat the source video
page as a screenshot. Do not add factual claims absent from the transcript.

TRANSCRIPT:\n{text}"""
    result = _openai_json(prompt, use_web_search=True)
    slides = []
    raw_slides = result.get("slides", [])[:count]
    force_two_parts = len(raw_slides) >= 7
    for idx, slide in enumerate(raw_slides):
        needs_screenshot = bool(slide.get("needs_screenshot", False))
        visual_url = str(slide.get("visual_url", "")).strip()
        if needs_screenshot and not _url_is_valid(visual_url):
            needs_screenshot, visual_url = False, ""
        part = int(slide.get("part", 1) or 1)
        if force_two_parts and part == 1:
            part = 1 if idx < (len(raw_slides) + 1) // 2 else 2
        slides.append({
            "name": str(slide.get("name", "")).strip()[:90],
            "desc": str(slide.get("desc", "")).strip()[:220],
            "why": str(slide.get("why", "")).strip()[:220],
            "url": url, "stars": 0, "kind": str(slide.get("kind", "insight")),
            "part": max(1, min(2, part)),
            "part_title": str(slide.get("part_title", "")).strip()[:70],
            "needs_screenshot": needs_screenshot,
            "visual_url": visual_url,
        })
    if not slides:
        raise RuntimeError("The transcript could not be converted into slides")
    return {"candidates": slides,
            "cover_hook": result.get("cover_hook") or "The part of this video you should not skip",
            "transcript_source": transcript_source,
            "part_count": 2 if any(s["part"] == 2 for s in slides) else 1}


# Backward compatibility for older callers.
generate_youtube_carousel = generate_video_carousel


# ---------- PULL ----------
def pull_github(topic, n=12):
    """Trending repos for a topic. topic can be free text ('vibe coding')."""
    q = topic.strip().replace(" ", "+")
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": q, "sort": "stars", "order": "desc", "per_page": n})
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ai-carousel"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=headers)
    data = json.load(urllib.request.urlopen(req, timeout=30))
    return [{"name": r["full_name"], "url": r["html_url"],
             "desc": (r["description"] or "")[:110], "stars": r["stargazers_count"],
             "kind": "github"} for r in data.get("items", [])]


def resource_from_url(url):
    """Turn any pasted URL into a candidate dict (best-effort metadata)."""
    url = url.strip()
    m = re.match(r"https?://github\.com/([^/]+/[^/?#]+)", url)
    if m:
        slug = m.group(1)
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{slug}",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "ai-carousel"})
            r = json.load(urllib.request.urlopen(req, timeout=20))
            return {"name": r["full_name"], "url": r["html_url"],
                    "desc": (r.get("description") or "")[:110],
                    "stars": r.get("stargazers_count", 0), "kind": "github"}
        except Exception:
            pass
    host = urllib.parse.urlparse(url).netloc.replace("www.", "")
    return {"name": host, "url": url, "desc": "", "stars": 0, "kind": "web"}


# ---------- BUILD ----------
def _why_sentence(r):
    """Backward-compatible combined slide copy."""
    desc, need = _slide_copy(r)
    if desc and need:
        return f"{desc} Why you'll need it: {need}"
    return desc or need or f"Use {r['name']} to move from an idea to a working result faster."


def _slide_copy(r):
    """Return editor-aligned What it does and Why you'll need it text."""
    desc = (r.get("desc") or "").strip().rstrip(".")
    why = (r.get("why") or "").strip().rstrip(".")
    dangling = (" and", " or", " with", " for", " to", " then", " a", " an", " the")
    if desc.lower().endswith(dangling):
        desc = desc.rsplit(" ", 1)[0].rstrip(",;:")
    if why.lower().endswith(dangling):
        why = why.rsplit(" ", 1)[0].rstrip(",;:")
    why = re.sub(r"^(?:best\s+(?:when|for)|use\s+it\s+when)\s*[:,-]?\s*", "", why,
                 flags=re.IGNORECASE)
    if why:
        why = why[0].upper() + why[1:]
    return ((desc + ".") if desc else "", (why + ".") if why else "")


def _series_groups(resources, split_mode="suggested"):
    """Respect the agent's editorial plan, with a deterministic seven-item
    safety net. Avoid creating a part with only one orphaned slide."""
    items = [dict(r) for r in resources]
    if split_mode == "single":
        for r in items:
            r["part"] = 1
    elif split_mode == "two":
        cut = (len(items) + 1) // 2
        for i, r in enumerate(items):
            r["part"] = 1 if i < cut else 2
    elif len(items) >= 7 and not any(int(r.get("part", 1) or 1) > 1 for r in items):
        cut = (len(items) + 1) // 2
        for i, r in enumerate(items):
            r["part"] = 1 if i < cut else 2
    grouped = {}
    for r in items:
        part = max(1, int(r.get("part", 1) or 1))
        grouped.setdefault(part, []).append(r)
    groups = [grouped[k] for k in sorted(grouped)]
    if len(groups) > 1 and any(len(g) < 2 for g in groups):
        return [items]
    return groups


def build_carousel(resources, bg_query="cozy interior warm light",
                   cover_title="AI RESOURCES", cover_hook=None, run_id="web",
                   include_what_it_does=True, include_why_youll_need_it=True,
                   split_mode="suggested", comment_keyword="CLAUDE"):
    """resources: list of dicts (name, url, desc, stars, optional hook/bullets).
    Returns list of output PNG paths (relative to OUT)."""
    slides, credits, background_files = [], set(), []
    prefix = f"{run_id}_"
    groups = _series_groups(resources, split_mode)

    # A supplied aesthetic prompt applies across the whole carousel. Blank is
    # the explicit opt-out and uses the clean neutral canvas instead.
    use_photo_background = bool(bg_query.strip())
    if use_photo_background:
        bgs = fetch_backgrounds(bg_query.strip(), len(resources) + len(groups) * 2)
    else:
        bgs = [(None, "")] * (len(resources) + len(groups) * 2)
    for _, attr in bgs:
        if attr:
            credits.add(attr)
    background_files = list(dict.fromkeys(
        os.path.basename(path) for path, _ in bgs if path))

    series, bg_idx = [], 0
    multi = len(groups) > 1
    for part_index, group in enumerate(groups, start=1):
        group_files = []
        cover_name = os.path.basename(bgs[bg_idx][0]) if bgs[bg_idx][0] else None
        bg_idx += 1
        part_title = next((r.get("part_title", "").strip() for r in group
                           if r.get("part_title", "").strip()), "")
        # The editable cover field is the source of truth. Generated part
        # titles are only a fallback when the user leaves it blank.
        part_hook = (cover_hook or "").strip() or part_title or cover_title
        kicker = f"PART {part_index} OF {len(groups)}" if multi else ""
        cover_out = (f"{prefix}part{part_index}_00_cover.png" if multi
                     else f"{prefix}00_cover.png")
        cover = C.build_cover(cover_name, kicker, part_hook, "", swipe="", out=cover_out)
        cover_file = os.path.basename(cover)
        slides.append(cover_file); group_files.append(cover_file)

        for slide_index, r in enumerate(group, start=1):
            shot_name = None
            needs_screenshot = bool(r.get("needs_screenshot", True))
            visual_url = (r.get("visual_url") or r.get("url") or "").strip()
            if needs_screenshot and visual_url:
                try:
                    shot_path = capture(
                        visual_url,
                        f"{prefix}p{part_index}_{r['name'].replace('/', '_')}")
                    shot_name = os.path.basename(shot_path)
                except Exception as e:
                    print("screenshot fallback:", e)
                    shot_path = C.build_resource_preview(
                        r["name"], visual_url, r.get("desc", ""),
                        out=f"{prefix}p{part_index}_{r['name'].replace('/', '_')}_fallback.png")
                    shot_name = os.path.basename(shot_path)
            detail_bg = os.path.basename(bgs[bg_idx][0]) if bgs[bg_idx][0] else None
            bg_idx += 1
            detail_out = (f"{prefix}part{part_index}_{slide_index:02d}.png" if multi
                          else f"{prefix}{slide_index:02d}.png")
            what_text, best_for_text = _slide_copy(r)
            out = C.build(detail_bg, "",
                          r.get("hook") or r["name"],
                          "",
                          shot_name, what_text,
                          use_photo_background=use_photo_background,
                          out=detail_out, source_url=r.get("url", ""),
                          include_what_it_does=include_what_it_does,
                          best_for_text=best_for_text,
                          include_why_youll_need_it=include_why_youll_need_it,
                          what_title=r.get("what_title") or "WHAT IT DOES",
                          why_title=r.get("why_title") or "WHY YOU'LL NEED IT")
            out_file = os.path.basename(out)
            slides.append(out_file); group_files.append(out_file)
        cta_bg = os.path.basename(bgs[bg_idx][0]) if bgs[bg_idx][0] else None
        bg_idx += 1
        cta_out = (f"{prefix}part{part_index}_{len(group)+1:02d}_cta.png" if multi
                   else f"{prefix}{len(group)+1:02d}_cta.png")
        cta = C.build_cta(cta_bg, "FOLLOW US @vonn.gpt FOR MORE", "vonn.gpt",
                          comment_keyword=comment_keyword,
                          use_photo_background=use_photo_background,
                          out=cta_out)
        cta_file = os.path.basename(cta)
        slides.append(cta_file); group_files.append(cta_file)
        series.append({"part": part_index, "title": part_hook, "slides": group_files})

    outline = make_canva_outline(resources, cover_title, cover_hook)
    with open(os.path.join(OUT, f"{prefix}outline.json"), "w") as f:
        json.dump(outline, f, indent=2)

    return {"slides": slides, "series": series, "photos": background_files,
            "credits": sorted(credits), "outline": outline}


def make_canva_outline(resources, cover_title="AI RESOURCES", cover_hook=None):
    """Canva-native editable path: one page of editable text per resource.
    Feeds request-outline-review -> generate-design-structured. Hyphen bullets
    only (Canva rejects unicode bullets)."""
    pages = [{
        "title": cover_hook or cover_title,
        "description": "- AI resources worth saving\n- Swipe for the full list\n- Links in every slide",
    }]
    for r in resources:
        desc = r.get("desc", "").strip()
        lines = []
        if desc:
            lines.append(f"- {desc}")
        if r.get("stars"):
            lines.append(f"- ★ {r['stars']:,} on GitHub")
        lines.append(f"- {r['url']}")
        pages.append({
            "title": (r.get("hook") or r["name"]).strip(),
            "description": "\n".join(lines),
        })
    pages.append({
        "title": "Follow for more",
        "description": "- Follow @vonn.gpt\n- Part 2 soon\n- Save this for later",
    })
    caption = (f"{cover_hook or cover_title} 🧵\n\n"
               + "\n".join(f"• {r.get('hook') or r['name']} — {r['url']}" for r in resources)
               + "\n\n#ai #aitools #buildinpublic #claude #opensource")
    return {"topic": cover_title, "pages": pages, "caption": caption}


if __name__ == "__main__":
    print(json.dumps(pull_github("claude skills", 5), indent=2))
