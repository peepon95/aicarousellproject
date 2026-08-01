#!/usr/bin/env python3
"""
Thin wrapper around the ai-resource-carousel skill scripts so the web app and
the daily agent share one engine. Everything reads/writes the project-root
folders (backgrounds/, screenshots/, out/) exactly like the CLI skill does.
"""
import base64, os, re, json, sys, socket, time, urllib.request, urllib.parse, urllib.error, tempfile, subprocess
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

from fetch_pexels import fetch_backgrounds  # noqa: E402
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

SOURCE_TYPES = {
    "auto": "the strongest primary sources for the request",
    "mixed_sources": (
        "a verified mix of YouTube videos or channels, Substack articles, "
        "GitHub repositories, and official tool websites"),
    "youtube_video": "YouTube video pages only",
    "youtube_channel": "YouTube channel pages only",
    "substack_article": "individual Substack article pages only",
    "github_repo": "GitHub repository pages only",
    "tool_website": "official product or tool websites only",
}


def infer_source_type(topic, requested="auto"):
    """Choose a strict source lane from an explicit UI choice or plain language."""
    if requested in SOURCE_TYPES and requested != "auto":
        return requested
    text = topic.lower()
    if "youtube channel" in text or "youtube creator" in text:
        return "youtube_channel"
    if "youtube" in text or "video essay" in text or "videos to watch" in text:
        return "youtube_video"
    if "substack" in text or "newsletters" in text:
        return "substack_article"
    if ("github" in text or re.search(r"\b(repos?|repositories)\b", text)
            or re.search(r"\bprojects? (?:you can|to) run\b", text)):
        return "github_repo"
    if re.search(r"\b(ai tools?|apps?|websites?|software)\b", text):
        return "tool_website"
    return "auto"


def _host_and_path(url):
    parsed = urllib.parse.urlparse((url or "").strip())
    return parsed.netloc.lower().removeprefix("www."), parsed.path.rstrip("/")


def source_type_for_url(url):
    host, path = _host_and_path(url)
    if host in ("youtube.com", "m.youtube.com", "youtu.be"):
        if host == "youtu.be" or path == "/watch" or path.startswith(("/shorts/", "/live/")):
            return "youtube_video"
        if path.startswith(("/@", "/channel/", "/c/", "/user/")):
            return "youtube_channel"
    if host == "substack.com" or host.endswith(".substack.com"):
        if path.startswith("/p/") or (host == "substack.com" and "/p-" in path):
            return "substack_article"
    if host == "github.com" and len([part for part in path.split("/") if part]) == 2:
        return "github_repo"
    return "tool_website" if host else "unknown"


def source_matches(url, source_type):
    if source_type in ("auto", "mixed_sources"):
        return source_type_for_url(url) != "unknown"
    return source_type_for_url(url) == source_type


def _source_prompt(source_type):
    rules = {
        "youtube_video": (
            "Return only real YouTube video or Shorts URLs. Each URL must be a "
            "youtube.com/watch, youtube.com/shorts, or youtu.be page. Do not return "
            "channels, playlists, articles, GitHub repos, or general websites."
        ),
        "youtube_channel": (
            "Return only real YouTube channel URLs using youtube.com/@handle or a "
            "canonical /channel/ URL. Do not return individual videos or other sites."
        ),
        "substack_article": (
            "Return only individual articles hosted on Substack. Do not return a "
            "publication homepage, archive, subscribe page, or a non-Substack article."
        ),
        "github_repo": (
            "Return only canonical GitHub repository URLs with exactly an owner and "
            "repository as the core path. Do not return topics, searches, issues, or docs."
        ),
        "tool_website": (
            "Return only official homepages or primary product pages for distinct tools. "
            "Do not return listicles, social posts, affiliate roundups, or GitHub mirrors."
        ),
        "mixed_sources": (
            "Research across public primary sources using OpenAI web search. Return a "
            "useful mix chosen from public YouTube videos or channels, individual "
            "Substack articles, canonical GitHub repositories, and official product "
            "websites. Use at least two source families, and at least three when five "
            "or more items are requested. Verify every item with its platform-specific metadata. Do not "
            "include listicles, search pages, private sources, or duplicate subjects."
        ),
        "auto": "Use a primary, directly supporting source for every slide.",
    }
    return rules[source_type]


def clean_editorial_text(value):
    """Remove model-y punctuation while preserving normal hyphens inside words."""
    text = str(value or "").replace("—", ",").replace("–", ",")
    text = re.sub(r"\s+-\s+", ": ", text)
    text = re.sub(r"^[\s•*-]+", "", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def clean_cover_hook(value):
    """Keep covers topic-led, without list counts or Part 1/2 language."""
    text = clean_editorial_text(value)
    text = re.sub(r"^part\s+\d+(?:\s+of\s+\d+)?\s*[:,-]?\s*", "", text, flags=re.I)
    return re.sub(r"^\d+\s+", "", text).strip()


def _github_run_evidence(url):
    """Return an exact README command that proves a repo can run locally."""
    match = re.match(r"https?://github\.com/([^/]+)/([^/?#]+)", url)
    if not match:
        return ""
    owner, repo = match.group(1), match.group(2).removesuffix(".git")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ai-carousel"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repo}/readme", headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
        readme = base64.b64decode(payload.get("content", "")).decode("utf-8", "ignore")
    except Exception:
        return ""
    command = re.compile(
        r"(?:docker\s+(?:compose\s+up|run)|npm\s+(?:install|run)|pnpm\s+"
        r"(?:install|run)|yarn\s+(?:install|start|dev)|bun\s+(?:install|run)|"
        r"pipx?\s+install|uv\s+(?:sync|run)|python\s+-m|cargo\s+run|go\s+run|"
        r"make\s+(?:run|start|dev))",
        re.IGNORECASE,
    )
    for line in readme.splitlines():
        cleaned = line.strip().strip("`$> ")
        if command.search(cleaned):
            return clean_editorial_text(cleaned)[:180]
    return ""


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


def _bounded_env_int(name, default, minimum, maximum):
    """Read an integer setting without letting a typo break generation."""
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _response_output_text(data):
    text = data.get("output_text")
    if text:
        return text
    return "".join(
        part.get("text", "")
        for item in data.get("output", [])
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


def _openai_json(prompt, use_web_search=True):
    # Re-read the local file so a key pasted while the dev server is running
    # is picked up without requiring a restart.
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Add OPENAI_API_KEY to .env to generate topic or video carousels")
    request_data = {
        "model": os.environ.get("OPENAI_MODEL", "").strip() or "gpt-5.2",
        "input": prompt + "\nReturn valid JSON only, with no markdown fences.",
        "max_output_tokens": 5000,
    }
    if use_web_search:
        request_data["tools"] = [{"type": "web_search"}]
    # Web research can run for several minutes. Start one asynchronous Response
    # and poll its stable ID so a slow read never launches duplicate research.
    use_background = use_web_search and os.environ.get(
        "OPENAI_BACKGROUND_MODE", "true").strip().lower() not in (
            "0", "false", "no", "off")
    if use_background:
        request_data["background"] = True
    payload = json.dumps(request_data).encode()
    timeout_seconds = _bounded_env_int(
        "OPENAI_TIMEOUT_SECONDS", 600, 30, 1800)
    max_retries = _bounded_env_int("OPENAI_MAX_RETRIES", 2, 0, 5)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    if use_background:
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses", data=payload,
            headers=headers)
        try:
            with urllib.request.urlopen(
                    request, timeout=min(30, timeout_seconds)) as response:
                data = json.load(response)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            raise RuntimeError(
                "OpenAI did not acknowledge the research job. Try again."
            ) from exc

        response_id = data.get("id", "")
        deadline = time.monotonic() + timeout_seconds
        poll_errors = 0
        while data.get("status") in ("queued", "in_progress"):
            if not response_id:
                raise RuntimeError("OpenAI research started without a response ID")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"OpenAI research is still running after {timeout_seconds} seconds. "
                    "Try again, narrow the topic, or increase "
                    "OPENAI_TIMEOUT_SECONDS in .env."
                )
            time.sleep(min(2, remaining))
            poll_request = urllib.request.Request(
                f"https://api.openai.com/v1/responses/{response_id}",
                headers=headers)
            try:
                with urllib.request.urlopen(
                        poll_request, timeout=min(30, remaining)) as response:
                    data = json.load(response)
                poll_errors = 0
            except urllib.error.HTTPError as exc:
                retryable = exc.code in (408, 409, 429) or exc.code >= 500
                if not retryable or poll_errors >= max_retries:
                    raise
                poll_errors += 1
            except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
                if poll_errors >= max_retries:
                    raise RuntimeError(
                        "OpenAI research finished, but its status could not be read. "
                        "Try again."
                    ) from exc
                poll_errors += 1

        if data.get("status") != "completed":
            detail = data.get("error") or data.get("incomplete_details") or data.get("status")
            raise RuntimeError(f"OpenAI research ended before completion: {detail}")

        text = _response_output_text(data)
        if not text:
            raise RuntimeError("OpenAI research completed without carousel content")
        return json.loads(text)

    data = None
    last_error = None
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses", data=payload,
            headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                data = json.load(resp)
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            retryable = exc.code in (408, 409, 429) or exc.code >= 500
            if not retryable or attempt >= max_retries:
                raise
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            last_error = exc
            if attempt >= max_retries:
                raise RuntimeError(
                    f"OpenAI research timed out after {attempt + 1} attempts. "
                    "Try again, narrow the topic, or increase "
                    "OPENAI_TIMEOUT_SECONDS in .env."
                ) from exc
        time.sleep(min(2 ** attempt, 4))
    if data is None:
        raise RuntimeError(f"OpenAI research did not return a response: {last_error}")
    text = _response_output_text(data)
    return json.loads(text)


def _openai_json_with_images(prompt, image_paths):
    """Ask the Responses API to analyze sampled local video frames."""
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Add OPENAI_API_KEY to .env to analyze uploaded video")
    content = [{"type": "input_text", "text": prompt + "\nReturn valid JSON only."}]
    for path in image_paths[:12]:
        with open(path, "rb") as source:
            encoded = base64.b64encode(source.read()).decode("ascii")
        content.append({
            "type": "input_image",
            "image_url": f"data:image/jpeg;base64,{encoded}",
        })
    payload = json.dumps({
        "model": os.environ.get("OPENAI_MODEL", "").strip() or "gpt-5.2",
        "input": [{"role": "user", "content": content}],
    }).encode()
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        data = json.load(response)
    text = data.get("output_text", "")
    if not text:
        text = "".join(
            part.get("text", "")
            for item in data.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
    return json.loads(text)


def _url_is_valid(url):
    if not url or not url.startswith(("http://", "https://")):
        return False
    # A YouTube watch page returns HTTP 200 even when the video is private,
    # removed, region-blocked, or replaced by an error player. oEmbed is a
    # stricter public-video check and also guarantees a real thumbnail exists.
    if source_type_for_url(url) == "youtube_video":
        try:
            endpoint = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({
                "url": url, "format": "json",
            })
            req = urllib.request.Request(
                endpoint, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.load(resp)
            return bool(data.get("title") and data.get("thumbnail_url"))
        except Exception:
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


def generate_topic_carousel(
        topic, count=7, source_type="auto", _allow_partial_youtube=False):
    """Research any topic and draft selectable carousel slides."""
    source_type = infer_source_type(topic, source_type)
    if source_type == "youtube_video":
        # Video-essay roundups are intentionally a compact set of four. Keeping
        # this invariant here makes Telegram and the web UI behave identically.
        count = 4
    runnable_only = source_type == "github_repo" and bool(re.search(
        r"\b(run|runnable|locally|self[ -]?host)\b", topic, re.I))
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
    elif (source_type == "github_repo"
          or re.search(r"\b(github|repos?|repositories|open[ -]source)\b", topic, re.I)):
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
    youtube_count_note = ""
    if source_type == "youtube_video":
        youtube_count_note = """
Return exactly 4 distinct, directly relevant YouTube videos from 4 unique video
URLs. Do not return fewer than 4, repeat a video, or use a channel or playlist.
"""
    prompt = f"""Create a factual Instagram carousel outline about: {topic}
SOURCE LANE: {SOURCE_TYPES[source_type]}.
HARD SOURCE RULE: {_source_prompt(source_type)}
{youtube_count_note}
First infer the user's intent. If the query asks for tools, plugins, apps,
websites, resources, or alternatives, create a curated list of distinct named
products—one actual product per slide, with its official product URL. Do not
return generic lessons, installation steps, list-of-lists repositories, or
multiple slides about the same tool. If the query starts with how to/install,
create an ordered tutorial instead. Otherwise create a focused explainer.
When the source lane is YouTube videos, YouTube channels, Substack articles, or
GitHub repositories, treat each distinct source item as the resource instead of
forcing it into a product list.
Research current primary/official sources.{tutorial_note}
For resource lists, every slide must cover a distinct canonical product. Never
list a product page, connector page, documentation page, and help-center page
separately when they describe the same core workflow. Compare the complete list
before returning it and remove semantic duplicates. This restriction does not
apply to distinct steps in a tutorial about one product or repository.
Return an object with carousel_type (resource_list, tutorial, or explainer),
cover_hook (specific, curiosity-driven, not clickbait), and slides (maximum
{count}). This is one standalone carousel. Do not add Part 1, Part 2, numbered
series language, or a numeric list count to the cover. Each slide needs: name (short slide heading),
desc (one accurate sentence explaining what the tool, GitHub repo, website, or
concept literally does), why (one practical best-use case, different from desc),
url (a valid supporting source), kind (step, insight, or resource), part
(always 1), part_title (always empty), needs_screenshot
(true for named tools, websites, repos, or documentation), and visual_url
(normally the same official URL).
Each slide also needs author (channel, writer, publisher, or repository owner),
published_at when the source exposes a date, and evidence (one short factual
detail from the source proving why it belongs in this exact roundup). For a
video-essay request, evidence must describe the essay's subject or thesis, not
its platform. For a runnable-project request, evidence must be an exact install
or run command found in the repository README.
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
    seen_subjects = set()
    seen_step_names = set()
    valid_urls = {}
    for idx, slide in enumerate(raw_slides):
        url = str(slide.get("url", "")).strip()
        if not source_matches(url, source_type):
            continue
        if url not in valid_urls:
            valid_urls[url] = _url_is_valid(url)
        if not valid_urls[url]:
            continue
        name = clean_editorial_text(slide.get("name", ""))[:90]
        dedupe_key = str(slide.get("dedupe_key", "")).strip().lower()
        dedupe_key = re.sub(r"[^a-z0-9]+", "-", dedupe_key or name.lower()).strip("-")
        if carousel_type == "resource_list":
            canonical_url = url.lower().split("#", 1)[0].rstrip("/")
            if source_type == "youtube_video":
                canonical_url = _youtube_id(url) or canonical_url
            subject_keys = {dedupe_key, canonical_url}
            if seen_subjects & subject_keys:
                continue
            seen_subjects.update(subject_keys)
        else:
            step_key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            if step_key in seen_step_names:
                continue
            seen_step_names.add(step_key)
        part = 1
        visual_url = str(slide.get("visual_url") or url).strip()
        if not source_matches(visual_url, source_type):
            visual_url = url
        evidence = clean_editorial_text(slide.get("evidence", ""))[:180]
        if runnable_only:
            evidence = _github_run_evidence(url)
            if not evidence:
                continue
        slides.append({
            "name": name,
            "desc": clean_editorial_text(slide.get("desc", ""))[:220],
            "why": clean_editorial_text(slide.get("why", ""))[:220],
            "url": url, "stars": 0,
            "kind": str(slide.get("kind", "insight")),
            "source_type": source_type_for_url(url),
            "author": clean_editorial_text(slide.get("author", ""))[:100],
            "published_at": clean_editorial_text(slide.get("published_at", ""))[:40],
            "evidence": evidence,
            "part": max(1, min(2, part)),
            "part_title": "",
            "needs_screenshot": bool(slide.get("needs_screenshot", True)),
            "visual_url": visual_url if _url_is_valid(visual_url) else url,
            "dedupe_key": dedupe_key,
        })
    if not slides and not (source_type == "youtube_video" and _allow_partial_youtube):
        raise RuntimeError(
            f"No valid {SOURCE_TYPES[source_type]} were returned. Try a more specific topic."
        )
    if (source_type == "mixed_sources"
            and len({slide["source_type"] for slide in slides}) < 2):
        raise RuntimeError(
            "Mixed research returned only one source family. Try a broader topic so "
            "OpenAI can verify results across at least two public platforms."
        )
    if (source_type == "youtube_video" and len(slides) < 4
            and not _allow_partial_youtube):
        excluded = ", ".join(slide["url"] for slide in slides)
        supplement = generate_topic_carousel(
            f"{topic}. Find additional distinct videos so the final list has four. "
            f"Do not use these URLs: {excluded or 'none'}",
            count=4,
            source_type="youtube_video",
            _allow_partial_youtube=True,
        )
        seen_urls = {
            _youtube_id(slide["url"]) or slide["url"].lower().rstrip("/")
            for slide in slides
        }
        for candidate in supplement["candidates"]:
            canonical = (
                _youtube_id(candidate["url"])
                or candidate["url"].lower().rstrip("/")
            )
            if canonical not in seen_urls:
                slides.append(candidate)
                seen_urls.add(canonical)
            if len(slides) == 4:
                break
    if (source_type == "youtube_video" and len(slides) < 4
            and not _allow_partial_youtube):
        raise RuntimeError(
            "YouTube research could not verify four distinct videos. "
            "Try a more specific video-essay topic."
        )
    if source_type == "youtube_video":
        slides = slides[:4]
    return {"candidates": slides,
            "cover_hook": clean_cover_hook(
                result.get("cover_hook") or cover_hook_for(topic, len(slides))),
            "carousel_type": carousel_type,
            "source_type": source_type,
            "recommended_canvas": (
                "story_9_16" if source_type in ("youtube_video", "youtube_channel")
                else "editorial_3_4"),
            "part_count": 1}


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
                        "visual_url": r.get("visual_url", ""),
                        "author": r.get("author", ""),
                        "published_at": r.get("published_at", ""),
                        "evidence": r.get("evidence", "")})
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
                      "part_title", "visual_url", "author", "published_at", "evidence"):
            if field in item:
                base[field] = (str(item[field]).strip() if field == "visual_url"
                               else clean_editorial_text(item[field]))
        base["part"] = 1
        base["part_title"] = ""
        if "needs_screenshot" in item:
            base["needs_screenshot"] = bool(item["needs_screenshot"])
        revised.append(base)
    if not revised:
        raise RuntimeError("The edit did not return any usable slides")
    return {"resources": revised,
            "cover_hook": clean_cover_hook(result.get("cover_hook") or cover_hook)}


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


def _transcribe_local_media(path):
    """Transcribe an uploaded recording, extracting compact audio when needed."""
    from openai import OpenAI
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is empty in the saved .env file")
    source = path
    temporary = None
    try:
        if os.path.getsize(path) > 24 * 1024 * 1024:
            temporary = tempfile.TemporaryDirectory(prefix="carousel-upload-audio-")
            source = os.path.join(temporary.name, "audio.mp3")
            try:
                subprocess.run([
                    "ffmpeg", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                    "-b:a", "48k", source,
                ], check=True, capture_output=True, timeout=180)
            except (FileNotFoundError, subprocess.CalledProcessError) as exc:
                raise RuntimeError(
                    "Large uploads need ffmpeg installed so their audio can be compressed."
                ) from exc
        if os.path.getsize(source) > 24 * 1024 * 1024:
            raise RuntimeError("The recording is too long to transcribe in one request")
        with open(source, "rb") as media:
            result = OpenAI(api_key=key).audio.transcriptions.create(
                model="gpt-4o-mini-transcribe", file=media)
        return result.text.strip()
    except Exception as exc:
        # Silent screen recordings are still useful because sampled frames are
        # analyzed below. Only preserve actionable configuration failures.
        if isinstance(exc, RuntimeError):
            raise
        return ""
    finally:
        if temporary:
            temporary.cleanup()


def _sample_video_frames(path, folder):
    """Extract a bounded visual story from a screen recording or video file."""
    pattern = os.path.join(folder, "frame_%02d.jpg")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", path, "-vf", "fps=1/6,scale=960:-2",
            "-frames:v", "12", "-q:v", "3", pattern,
        ], check=True, capture_output=True, timeout=180)
    except FileNotFoundError as exc:
        raise RuntimeError("Install ffmpeg to analyze uploaded videos and screen recordings") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace")[-500:]
        raise RuntimeError(f"The uploaded recording could not be decoded. {detail}") from exc
    frames = [os.path.join(folder, name) for name in sorted(os.listdir(folder))
              if name.startswith("frame_") and name.endswith(".jpg")]
    if not frames:
        raise RuntimeError("No readable frames were found in the uploaded recording")
    return frames


def generate_uploaded_video_carousel(path, count=8):
    """Analyze both the spoken and visible content in a user-owned recording."""
    with tempfile.TemporaryDirectory(prefix="carousel-upload-frames-") as folder:
        frames = _sample_video_frames(path, folder)
        transcript = _transcribe_local_media(path)
        prompt = f"""Analyze this uploaded video or screen recording and turn it into a
useful Instagram carousel with at most {count} slides. Use the sampled frames to
understand visible interfaces, websites, captions, demonstrations, and sequence.
Use the transcript when speech is present. Do not invent a product name, URL,
feature, or claim that is not visible or spoken. Focus on what the viewer can
learn, try, or run. Return cover_hook and slides. Each slide needs name, desc,
why and kind. Keep this as one carousel with no Part 1 or Part 2 language.
Write like a thoughtful person, not an ad.
Do not use em dashes, en dashes, canned hype, or vague claims.

TRANSCRIPT:
{transcript[:35000] or "(No usable speech. Rely on the visible frames.)"}"""
        result = _openai_json_with_images(prompt, frames)
    raw_slides = result.get("slides", [])[:count]
    slides = []
    for index, slide in enumerate(raw_slides):
        slides.append({
            "name": clean_editorial_text(slide.get("name", ""))[:90],
            "desc": clean_editorial_text(slide.get("desc", ""))[:220],
            "why": clean_editorial_text(slide.get("why", ""))[:220],
            "url": "", "visual_url": "", "stars": 0,
            "kind": clean_editorial_text(slide.get("kind", "insight")),
            "part": 1,
            "part_title": "",
            "needs_screenshot": False,
            "source_type": "uploaded_video",
            "author": "", "published_at": "", "evidence": "",
        })
    if not slides:
        raise RuntimeError("The uploaded recording did not produce a usable carousel outline")
    return {
        "candidates": slides,
        "cover_hook": clean_cover_hook(
            result.get("cover_hook") or "What this recording is really showing"),
        "transcript_source": "uploaded video and sampled frames",
        "recommended_canvas": "story_9_16",
        "part_count": 1,
    }


def generate_video_carousel(url, count=7):
    """Turn a supported public short-form or long-form video into slides."""
    url = url.strip()
    source_video_type = source_type_for_url(url)
    if source_video_type == "youtube_video" and not _url_is_valid(url):
        raise RuntimeError(
            "This YouTube video does not expose a public title and thumbnail. "
            "Choose a public, available video."
        )
    text, transcript_source = _video_transcript(url)
    # Keep within a practical request size while retaining the full arc.
    text = text[:45000]
    prompt = f"""Turn this video transcript into a useful Instagram carousel.
Do not merely summarize chronologically: identify the strongest thesis, key
lessons, and actionable steps. Create at most {count} slides. Return an object
with cover_hook and slides. This is one standalone carousel. Do not add Part 1,
Part 2, numbered series language, or a numeric list count to the cover. Each slide needs
name (short heading), desc (one accurate sentence explaining what the referenced
tool, website, repo, concept, or step actually does), why (a distinct practical takeaway),
url (always {url}), kind (insight or step), needs_screenshot,
and visual_url. When the source is YouTube, every slide must use the same verified
source video card: set needs_screenshot true and visual_url to {url}. This visually
anchors each lesson to the video it came from. For non-YouTube videos, use a real
official product or interface screenshot only when it improves understanding.
Do not add factual claims absent from the transcript.

TRANSCRIPT:\n{text}"""
    result = _openai_json(prompt, use_web_search=True)
    slides = []
    raw_slides = result.get("slides", [])[:count]
    for idx, slide in enumerate(raw_slides):
        needs_screenshot = bool(slide.get("needs_screenshot", False))
        visual_url = str(slide.get("visual_url", "")).strip()
        if source_video_type == "youtube_video":
            needs_screenshot, visual_url = True, url
        elif needs_screenshot and not _url_is_valid(visual_url):
            needs_screenshot, visual_url = False, ""
        part = 1
        slides.append({
            "name": clean_editorial_text(slide.get("name", ""))[:90],
            "desc": clean_editorial_text(slide.get("desc", ""))[:220],
            "why": clean_editorial_text(slide.get("why", ""))[:220],
            "url": url, "stars": 0, "kind": str(slide.get("kind", "insight")),
            "part": max(1, min(2, part)),
            "part_title": "",
            "needs_screenshot": needs_screenshot,
            "visual_url": visual_url,
            "source_type": (
                "youtube_video" if source_video_type == "youtube_video"
                else source_type_for_url(visual_url) if visual_url else "video_source"),
            "author": clean_editorial_text(slide.get("author", ""))[:100],
            "published_at": clean_editorial_text(slide.get("published_at", ""))[:40],
            "evidence": clean_editorial_text(slide.get("evidence", ""))[:180],
        })
    if not slides:
        raise RuntimeError("The transcript could not be converted into slides")
    return {"candidates": slides,
            "cover_hook": clean_cover_hook(
                result.get("cover_hook") or "The part of this video you should not skip"),
            "transcript_source": transcript_source,
            "recommended_canvas": "story_9_16",
            "part_count": 1}


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


def _series_groups(resources, split_mode="single"):
    """Keep one carousel unless the user explicitly requests two exports."""
    items = [dict(r) for r in resources]
    if split_mode != "two":
        for r in items:
            r["part"] = 1
    else:
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
                   split_mode="single", comment_keyword="CLAUDE",
                   visual_style="editorial_reference",
                   canvas_format="editorial_3_4"):
    """resources: list of dicts (name, url, desc, stars, optional hook/bullets).
    Returns list of output PNG paths (relative to OUT)."""
    C.configure_canvas(canvas_format)
    slides, credits, background_files = [], set(), []
    prefix = f"{run_id}_"
    groups = _series_groups(resources, split_mode)

    # Use one distinct cover photograph, then lock a second photograph across
    # every recommendation and CTA. This matches the reference grid without
    # letting individual source slides drift between unrelated visual worlds.
    use_photo_background = bool(bg_query.strip())
    if use_photo_background:
        cover_bg, detail_bg = fetch_backgrounds(bg_query.strip(), 2)
        bgs = []
        for group in groups:
            bgs.extend([cover_bg] + [detail_bg] * len(group) + [detail_bg])
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
        part_hook = (cover_hook or "").strip() or cover_title
        kicker = ""
        cover_out = (f"{prefix}part{part_index}_00_cover.png" if multi
                     else f"{prefix}00_cover.png")
        cover = C.build_cover(
            cover_name, kicker, part_hook, "", swipe="", out=cover_out,
            visual_style=visual_style)
        cover_file = os.path.basename(cover)
        slides.append(cover_file); group_files.append(cover_file)

        for slide_index, r in enumerate(group, start=1):
            shot_name = None
            needs_screenshot = bool(r.get("needs_screenshot", True))
            visual_url = (r.get("visual_url") or r.get("url") or "").strip()
            source_type = r.get("source_type") or "auto"
            if source_type in ("auto", "video_source", "unknown"):
                source_type = source_type_for_url(visual_url)
            # A lesson derived from a YouTube video must still show the source.
            # Do not let an older draft's needs_screenshot=false flag create a
            # text-only slide or make the model choose an unrelated URL.
            if source_type_for_url(r.get("url", "")) == "youtube_video":
                source_type = "youtube_video"
                visual_url = r.get("url", "").strip()
                needs_screenshot = True
            if needs_screenshot and visual_url:
                preview_name = f"{prefix}p{part_index}_{r['name'].replace('/', '_')}"
                if source_type == "youtube_video":
                    # YouTube watch pages frequently render consent, private,
                    # unavailable, or region-specific player states. Build the
                    # card from verified oEmbed metadata and the real thumbnail.
                    shot_path = C.build_resource_preview(
                        r["name"], visual_url, r.get("desc", ""),
                        out=f"{preview_name}_youtube.png", require_image=True)
                    shot_name = os.path.basename(shot_path)
                else:
                    try:
                        shot_path = capture(
                            visual_url, preview_name, source_type=source_type)
                        shot_name = os.path.basename(shot_path)
                    except Exception as e:
                        print("screenshot fallback:", e)
                        shot_path = C.build_resource_preview(
                            r["name"], visual_url, r.get("desc", ""),
                            out=f"{preview_name}_fallback.png")
                        shot_name = os.path.basename(shot_path)
            detail_bg = os.path.basename(bgs[bg_idx][0]) if bgs[bg_idx][0] else None
            bg_idx += 1
            detail_out = (f"{prefix}part{part_index}_{slide_index:02d}.png" if multi
                          else f"{prefix}{slide_index:02d}.png")
            what_text, best_for_text = _slide_copy(r)
            if visual_style == "editorial_reference" and shot_name:
                label_map = {
                    "youtube_video": "youtube", "youtube_channel": "youtube",
                    "substack_article": "substack", "github_repo": "github",
                    "tool_website": "website",
                }
                out = C.build_editorial_source(
                    detail_bg, shot_name, label_map.get(source_type, "website"),
                    out=detail_out, use_photo_background=use_photo_background)
            else:
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
            "credits": sorted(credits), "outline": outline,
            "visual_style": visual_style, "canvas_format": canvas_format}


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
        "description": "- Follow @vonn.gpt\n- Save this for later",
    })
    source_types = {r.get("source_type") for r in resources}
    if source_types & {"youtube_video", "youtube_channel", "video_source"}:
        hashtags = "#videoessay #watchlist #selfeducation"
    elif "substack_article" in source_types:
        hashtags = "#substack #readinglist #selfeducation"
    elif "github_repo" in source_types:
        hashtags = "#github #opensource #buildinpublic"
    else:
        hashtags = "#aitools #productivity #buildinpublic"
    caption = (f"{clean_cover_hook(cover_hook or cover_title)} 🧵\n\n"
               + "\n".join(
                   (f"{clean_editorial_text(r.get('hook') or r['name'])}: {r['url']}"
                    if r.get("url") else clean_editorial_text(r.get("hook") or r["name"]))
                   for r in resources)
               + f"\n\n{hashtags}")
    return {"topic": cover_title, "pages": pages, "caption": caption}


if __name__ == "__main__":
    print(json.dumps(pull_github("claude skills", 5), indent=2))
