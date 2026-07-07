#!/usr/bin/env python3
"""
Thin wrapper around the ai-resource-carousel skill scripts so the web app and
the daily agent share one engine. Everything reads/writes the project-root
folders (backgrounds/, screenshots/, out/) exactly like the CLI skill does.
"""
import os, re, json, sys, urllib.request, urllib.parse
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, ".claude", "skills", "ai-resource-carousel")
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, SKILL)

from fetch_pexels import fetch_background, fetch_backgrounds  # noqa: E402
from capture_screenshot import capture             # noqa: E402
import compose_fullbleed as C                      # noqa: E402

OUT = os.path.join(ROOT, "out")


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
def _auto_bullets(r):
    """Fill the 'why you'll need this' section when the caller gave no bullets.
    Keep them short so they fit on one line each."""
    b = []
    if r.get("stars"):
        b.append(f"{r['stars']:,}+ stars — battle-tested")
    if r.get("kind") == "github":
        b.append("free & open source")
    b.append("save it before you forget")
    return b[:3]


def build_carousel(resources, bg_query="cozy interior warm light",
                   cover_title="AI RESOURCES", cover_hook=None, run_id="web"):
    """resources: list of dicts (name, url, desc, stars, optional hook/bullets).
    Returns list of output PNG paths (relative to OUT)."""
    slides, credits = [], set()
    prefix = f"{run_id}_"

    # one distinct random background per slide (cover + each resource), same vibe
    bgs = fetch_backgrounds(bg_query, len(resources) + 1)
    for _, attr in bgs:
        credits.add(attr)

    # cover
    cover = C.build_cover(os.path.basename(bgs[0][0]), "AI RESOURCE DROP",
                          cover_title, cover_hook or "save these before they blow up",
                          out=f"{prefix}00_cover.png")
    slides.append(os.path.basename(cover))

    for i, r in enumerate(resources, start=1):
        shot_name = None
        try:
            shot_path = capture(r["url"], f"{prefix}{r['name'].replace('/', '_')}")
            shot_name = os.path.basename(shot_path)
        except Exception as e:
            print("screenshot skipped:", e)
        out = C.build(os.path.basename(bgs[i][0]), f"{i}/{len(resources)}",
                      r.get("hook") or r["name"], r.get("desc", ""),
                      shot_name, r.get("bullets") or _auto_bullets(r),
                      out=f"{prefix}{i:02d}.png")
        slides.append(os.path.basename(out))

    outline = make_canva_outline(resources, cover_title, cover_hook)
    with open(os.path.join(OUT, f"{prefix}outline.json"), "w") as f:
        json.dump(outline, f, indent=2)

    return {"slides": slides, "credits": sorted(credits), "outline": outline}


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
    caption = (f"{cover_hook or cover_title} 🧵\n\n"
               + "\n".join(f"• {r.get('hook') or r['name']} — {r['url']}" for r in resources)
               + "\n\n#ai #aitools #buildinpublic #claude #opensource")
    return {"topic": cover_title, "pages": pages, "caption": caption}


if __name__ == "__main__":
    print(json.dumps(pull_github("claude skills", 5), indent=2))
