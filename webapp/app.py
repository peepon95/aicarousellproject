#!/usr/bin/env python3
"""
Local web UI for the AI resource carousel engine.
Run:  .venv/bin/uvicorn webapp.app:app --reload --port 8000
Open: http://localhost:8000
"""
import os
import io
import zipfile
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import media_storage as M
from . import pipeline as P
from . import repo_video as RV

ROOT = P.DATA_ROOT
HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="AI Carousel Studio")
INDEX = os.path.join(HERE, "templates", "index.html")

# serve generated slides + inbox drafts
app.mount("/out", StaticFiles(directory=P.OUT), name="out")
SCREENSHOTS = os.path.join(ROOT, "screenshots")
os.makedirs(SCREENSHOTS, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=SCREENSHOTS), name="screenshots")
BACKGROUNDS = os.path.join(ROOT, "backgrounds")
os.makedirs(BACKGROUNDS, exist_ok=True)
app.mount("/backgrounds", StaticFiles(directory=BACKGROUNDS), name="backgrounds")
INBOX = os.path.join(ROOT, "inbox")
os.makedirs(INBOX, exist_ok=True)
app.mount("/inbox", StaticFiles(directory=INBOX), name="inbox")


@app.get("/", response_class=HTMLResponse)
def home():
    with open(INDEX, encoding="utf-8") as f:
        html = f.read()
    if not RV.rendering_available():
        html = html.replace(
            'id="repo-video-wrap"',
            'id="repo-video-wrap" hidden',
            1,
        )
    return HTMLResponse(html)


class PullReq(BaseModel):
    mode: str            # "topic" | "links" | "reference"
    query: str = ""      # topic text, or newline-separated URLs


@app.post("/pull")
def pull(req: PullReq):
    if req.mode == "topic":
        try:
            result = P.generate_topic_carousel(req.query, count=8)
        except Exception as e:
            return JSONResponse({"error": f"Topic generation failed: {e}"}, status_code=502)
        return result
    if req.mode in ("youtube", "video"):
        try:
            return P.generate_video_carousel(req.query, count=8)
        except Exception as e:
            return JSONResponse({"error": f"Video breakdown failed: {e}"}, status_code=502)
    return JSONResponse({"error": "unknown mode"}, status_code=400)


class Resource(BaseModel):
    name: str
    url: str
    desc: str = ""
    stars: int = 0
    hook: str = ""
    kind: str = ""
    why: str = ""
    what_title: str = "WHAT IT DOES"
    why_title: str = "WHY YOU'LL NEED IT"
    dedupe_key: str = ""
    part: int = 1
    part_title: str = ""
    needs_screenshot: bool = True
    visual_url: str = ""


class BuildReq(BaseModel):
    resources: list[Resource]
    bg_query: str = "cozy interior warm light"
    cover_title: str = "AI RESOURCES"
    cover_hook: str = ""
    include_what_it_does: bool = True
    include_why_youll_need_it: bool = True
    split_mode: str = "suggested"
    comment_keyword: str = "CLAUDE"


class ReviseReq(BaseModel):
    resources: list[Resource]
    cover_hook: str = ""
    instruction: str


class DownloadReq(BaseModel):
    files: list[str]
    kind: str = "carousel"


class ScreenshotPreviewReq(BaseModel):
    url: str
    name: str = "preview"
    description: str = ""


@app.post("/screenshot-preview")
def screenshot_preview(req: ScreenshotPreviewReq):
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        return JSONResponse({"error": "Enter a full link starting with http:// or https://."}, status_code=400)
    safe_name = "".join(c if c.isalnum() else "_" for c in req.name).strip("_")[:50] or "preview"
    try:
        M.require_blob()
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    try:
        path = P.capture(url, f"preview_{safe_name}")
        fallback = False
    except Exception as e:
        try:
            path = P.C.build_resource_preview(
                req.name or "Website", url, req.description,
                out=f"preview_{safe_name}_fallback.png")
            fallback = True
        except Exception:
            return JSONResponse({"error": f"Screenshot preview failed: {e}"}, status_code=502)
    try:
        image_url = (
            M.publish_file(path)
            if M.IS_VERCEL
            else f"/screenshots/{os.path.basename(path)}"
        )
    except Exception as e:
        return JSONResponse({"error": f"Preview upload failed: {e}"}, status_code=502)
    return {"image": image_url, "fallback": fallback}


@app.post("/download")
def download(req: DownloadReq):
    base = P.OUT if req.kind == "carousel" else os.path.join(ROOT, "backgrounds")
    safe_files = []
    for name in req.files:
        clean = os.path.basename(name)
        path = os.path.join(base, clean)
        if clean == name and os.path.isfile(path):
            safe_files.append((clean, path))
    if not safe_files:
        return JSONResponse({"error": "No downloadable files found."}, status_code=404)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in safe_files:
            archive.write(path, arcname=name)
    data.seek(0)
    filename = "carousel-images.zip" if req.kind == "carousel" else "carousel-photos.zip"
    return StreamingResponse(data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/revise")
def revise(req: ReviseReq):
    if not req.instruction.strip():
        return JSONResponse({"error": "Enter an instruction for the edit."}, status_code=400)
    try:
        return P.revise_carousel(
            [r.model_dump() for r in req.resources], req.cover_hook, req.instruction)
    except Exception as e:
        return JSONResponse({"error": f"Draft edit failed: {e}"}, status_code=502)


class RepoAnalyzeReq(BaseModel):
    url: str


class RepoRenderReq(BaseModel):
    plan: dict


@app.post("/repo/analyze")
def repo_analyze(req: RepoAnalyzeReq):
    try:
        return RV.analyze_repo(req.url)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"Repo analysis failed: {e}"}, status_code=502)


@app.post("/repo/render")
def repo_render(req: RepoRenderReq):
    if not req.plan.get("scenes"):
        return JSONResponse({"error": "Analyze a repo first."}, status_code=400)
    if not RV.rendering_available():
        return JSONResponse({
            "error": (
                "Repo video rendering is unavailable in the Vercel deployment. "
                "Run this feature locally or move it to a dedicated media worker."
            )
        }, status_code=503)
    return {"job": RV.start_render(req.plan)}


@app.get("/repo/status/{job_id}")
def repo_status(job_id: str):
    job = RV.job_status(job_id)
    if not job:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    return job


@app.post("/build")
def build(req: BuildReq):
    resources = [r.model_dump() for r in req.resources]
    if not resources:
        return JSONResponse({"error": "no resources selected"}, status_code=400)
    try:
        M.require_blob()
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    try:
        result = P.build_carousel(
            resources, bg_query=req.bg_query,
            cover_title=req.cover_title, cover_hook=req.cover_hook or None,
            include_what_it_does=req.include_what_it_does,
            include_why_youll_need_it=req.include_why_youll_need_it,
            split_mode=req.split_mode,
            comment_keyword=req.comment_keyword)
        result = M.publish_carousel(
            result,
            P.OUT,
            os.path.join(ROOT, "backgrounds"),
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return result
