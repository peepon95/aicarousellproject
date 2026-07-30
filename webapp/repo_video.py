#!/usr/bin/env python3
"""
GitHub repo → animated Remotion explainer video.

analyze_repo(url)  reads the repo via the GitHub API, asks the LLM for a
scene-by-scene video plan (headlines, feature cards, voiceover scripts), and
injects real star/fork numbers so the stats scene never hallucinates.

start_render(plan) runs in a background thread: edge-tts voiceover per scene,
then `npx remotion render RepoExplainer` inside the shared my-video project,
and drops the finished mp4 into the project out/ folder the web app already
serves. Poll job_status(job_id) for progress.
"""
import os, re, json, base64, shutil, subprocess, threading, time, uuid
import urllib.request, urllib.error

import pipeline as P

REMOTION_DIR = os.environ.get("REMOTION_DIR", "/Users/eevontan/my-video")
AUDIO_DIR = os.path.join(REMOTION_DIR, "public", "audio")
VOICE = os.environ.get("REPO_VIDEO_VOICE", "en-US-AndrewNeural")

# Frame layout must match RepoExplainerComposition.tsx (30fps)
SCENES = [
    ("title", 4.0), ("what", 7.0), ("features", 8.0),
    ("how", 7.0), ("stats", 7.0), ("cta", 5.0),
]

JOBS = {}
_LOCK = threading.Lock()


# ── GitHub ────────────────────────────────────────────────────────────────────

def _gh(path):
    headers = {"User-Agent": "carousel-studio", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def parse_repo_url(url):
    m = re.search(r"github\.com/([\w.-]+)/([\w.-]+)", url.strip())
    if not m:
        raise ValueError("Paste a GitHub repo link like https://github.com/owner/repo")
    return m.group(1), m.group(2).removesuffix(".git")


def fetch_repo(owner, name):
    repo = _gh(f"/repos/{owner}/{name}")
    readme = ""
    try:
        blob = _gh(f"/repos/{owner}/{name}/readme")
        readme = base64.b64decode(blob.get("content", "")).decode("utf-8", "ignore")
    except Exception:
        pass
    langs = {}
    try:
        langs = _gh(f"/repos/{owner}/{name}/languages")
    except Exception:
        pass
    return {
        "owner": owner, "name": name,
        "full_name": repo.get("full_name", f"{owner}/{name}"),
        "description": repo.get("description") or "",
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "open_issues": repo.get("open_issues_count", 0),
        "language": repo.get("language") or (next(iter(langs), "") if langs else ""),
        "languages": list(langs)[:5],
        "license": (repo.get("license") or {}).get("spdx_id") or "",
        "created": (repo.get("created_at") or "")[:4],
        "homepage": repo.get("homepage") or "",
        "topics": repo.get("topics", [])[:8],
        "readme": readme[:7000],
    }


# ── LLM plan ──────────────────────────────────────────────────────────────────

def _fmt_count(n):
    if n >= 1000:
        v = n / 1000
        return (f"{v:.1f}".rstrip("0").rstrip(".")) + "k"
    return str(n)


PLAN_PROMPT = """You are writing the script for a 38-second animated vertical explainer video about a GitHub repository. The audience is developers and AI-curious builders scrolling short-form video.

REPO FACTS (verified via GitHub API — do not contradict them):
{facts}

README EXCERPT:
{readme}

Return JSON with exactly this shape:
{{
  "display_name": "short display name for huge title text, UPPERCASE, max 12 chars (abbreviate if needed)",
  "tagline": "punchy 4-8 word tagline",
  "accent": "#hex primary accent color that suits the project (vivid, reads on black)",
  "accent2": "#hex secondary accent (complementary, for gradients)",
  "scenes": {{
    "title":    {{ "vo": "hook voiceover, 10-13 words" }},
    "what":     {{ "headline": "question or statement, 3-6 words ending with the key word",
                  "highlight": "the last 1-2 words of headline to underline",
                  "summary": "one plain-English line, max 12 words, shown under the mockup",
                  "vo": "what the repo does, 19-22 words" }},
    "features": {{ "headline": "3-4 word heading", "highlight": "last word of headline",
                  "cards": [ {{ "name": "feature name, max 14 chars", "tag": "1-word badge", "desc": "max 9 words" }} ] (exactly 4),
                  "vo": "walk through the standout capabilities, 22-25 words" }},
    "how":      {{ "headline": "3-4 word heading about getting started", "highlight": "last word",
                  "steps": [ {{ "cmd": "real shell command or usage line from the README, max 38 chars", "note": "2-4 word label" }} ] (exactly 3, real commands only — if unclear, use plausible install/run/use steps),
                  "vo": "how you actually use it, 19-22 words" }},
    "stats":    {{ "headline": "2-4 word heading",
                  "pills": [ "6-8 short feature/topic pills, 1-3 words each, may start with an emoji" ],
                  "vo": "credibility: community size, maturity, license, 19-22 words" }},
    "cta":      {{ "line1": "first word of 2-word closing line", "line2": "second word (this one gets the gradient)",
                  "sub": "one-line invitation, max 8 words",
                  "vo": "call to action mentioning the repo name, 11-14 words" }}
  }}
}}

Voiceover rules: natural spoken English, no URLs, no markdown, no special characters; say names phonetically; confident tech-narrator tone. Word counts are hard limits — the audio must fit fixed scene lengths."""


def analyze_repo(url):
    owner, name = parse_repo_url(url)
    info = fetch_repo(owner, name)
    facts = {k: v for k, v in info.items() if k != "readme"}
    plan = P._openai_json(
        PLAN_PROMPT.format(facts=json.dumps(facts, ensure_ascii=False),
                           readme=info["readme"] or "(no README)"),
        use_web_search=False)
    plan["owner"] = owner
    plan["name"] = name
    plan["repo"] = info["full_name"]
    plan["url"] = f"https://github.com/{info['full_name']}"
    plan["language"] = info["language"]
    dn = (plan.get("display_name") or name).upper()
    plan["display_name"] = dn[:14]
    # Real numbers for the stats scene — never trust the model with these.
    stats = [
        {"value": _fmt_count(info["stars"]), "label": "GitHub stars", "sub": "and counting"},
        {"value": _fmt_count(info["forks"]), "label": "Forks", "sub": "community builds"},
    ]
    if info["language"]:
        stats.append({"value": info["language"], "label": "Built with",
                      "sub": " · ".join(info["languages"][1:3]) or "primary language"})
    if info["created"]:
        stats.append({"value": f"since {info['created']}", "label": "Actively developed",
                      "sub": info["license"] or "open source"})
    while len(stats) < 4:
        stats.append({"value": _fmt_count(info["open_issues"]), "label": "Open issues", "sub": "living project"})
    plan.setdefault("scenes", {}).setdefault("stats", {})["stats"] = stats[:4]
    plan["scenes"]["what"].setdefault("browser_url", f"github.com/{info['full_name']}")
    plan["scenes"]["what"]["repo_desc"] = info["description"][:90]
    plan["scenes"]["what"]["repo_stars"] = _fmt_count(info["stars"])
    plan["scenes"]["what"]["repo_forks"] = _fmt_count(info["forks"])
    return plan


# ── Voiceover ─────────────────────────────────────────────────────────────────

def _audio_seconds(path):
    out = subprocess.run(["afinfo", path], capture_output=True, text=True).stdout
    m = re.search(r"estimated duration:\s*([\d.]+)", out)
    return float(m.group(1)) if m else 0.0


def _tts(text, path, rate="+15%"):
    subprocess.run(
        ["edge-tts", "--voice", VOICE, "--rate", rate, "--text", text, "--write-media", path],
        check=True, capture_output=True, timeout=120)


def make_voiceover(plan, job=None):
    os.makedirs(AUDIO_DIR, exist_ok=True)
    for i, (scene_id, seconds) in enumerate(SCENES, start=1):
        vo = (plan["scenes"].get(scene_id) or {}).get("vo", "").strip()
        path = os.path.join(AUDIO_DIR, f"repo_vo_s{i}.mp3")
        if job is not None:
            job["detail"] = f"voiceover {i}/{len(SCENES)}"
        if not vo:
            # keep the slot silent but present so the composition stays simple
            subprocess.run(["edge-tts", "--voice", VOICE, "--text", " . ", "--write-media", path],
                           check=True, capture_output=True, timeout=60)
            continue
        _tts(vo, path)
        if _audio_seconds(path) > seconds - 0.3:
            _tts(vo, path, rate="+28%")


# ── Render job ────────────────────────────────────────────────────────────────

def start_render(plan):
    job_id = uuid.uuid4().hex[:12]
    job = {"status": "queued", "detail": "", "video": None, "error": None,
           "progress": 0.0, "started": time.time(), "repo": plan.get("repo", "")}
    with _LOCK:
        JOBS[job_id] = job
    threading.Thread(target=_run_job, args=(job_id, plan), daemon=True).start()
    return job_id


def job_status(job_id):
    with _LOCK:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def _run_job(job_id, plan):
    job = JOBS[job_id]
    try:
        job["status"] = "voiceover"
        make_voiceover(plan, job)

        job["status"] = "rendering"
        job["detail"] = "starting Remotion render"
        props_path = os.path.join(REMOTION_DIR, "repo-plan.json")
        with open(props_path, "w", encoding="utf-8") as f:
            json.dump({**plan, "withAudio": True}, f, ensure_ascii=False)

        slug = re.sub(r"[^a-z0-9]+", "_", plan.get("repo", "repo").lower()).strip("_")
        out_name = f"repo_video_{slug}.mp4"
        render_out = os.path.join(REMOTION_DIR, "out", out_name)
        proc = subprocess.Popen(
            ["npx", "remotion", "render", "RepoExplainer", render_out,
             f"--props={props_path}", "--concurrency=4"],
            cwd=REMOTION_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            m = re.search(r"Rendered (\d+)/(\d+)", line)
            if m:
                job["progress"] = int(m.group(1)) / max(1, int(m.group(2)))
                job["detail"] = f"rendering frames {m.group(1)}/{m.group(2)}"
        proc.wait()
        if proc.returncode != 0 or not os.path.isfile(render_out):
            raise RuntimeError("Remotion render failed — check the my-video project logs")

        final = os.path.join(P.OUT, out_name)
        shutil.copyfile(render_out, final)
        job["video"] = out_name
        job["progress"] = 1.0
        job["status"] = "done"
        job["detail"] = "video ready"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


if __name__ == "__main__":
    plan = analyze_repo("https://github.com/anthropics/claude-code")
    print(json.dumps(plan, indent=2)[:2000])
