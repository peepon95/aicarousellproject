#!/usr/bin/env python3
"""
Local web UI for the AI resource carousel engine.
Run:  .venv/bin/uvicorn webapp.app:app --reload --port 8000
Open: http://localhost:8000
"""
import os
import io
import hmac
import uuid
import zipfile
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import media_storage as M
from . import pipeline as P
from . import repo_video as RV
from . import telegram_agent as TA

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
UPLOADS = os.path.join(ROOT, "uploads")
os.makedirs(UPLOADS, exist_ok=True)


def _blob_oidc_token(request: Request) -> str:
    return (
        request.headers.get("x-vercel-oidc-token", "").strip()
        or os.environ.get("VERCEL_OIDC_TOKEN", "").strip()
    )


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


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    supplied = request.headers.get("x-telegram-bot-api-secret-token", "").strip()
    if not expected or not hmac.compare_digest(expected, supplied):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        update = await request.json()
        return {"ok": True, **TA.handle_update(update)}
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Telegram agent failed: {exc}"}, status_code=502)


@app.get("/telegram/daily")
def telegram_daily(request: Request):
    expected = os.environ.get("CRON_SECRET", "").strip()
    supplied = request.headers.get("authorization", "").strip()
    if not expected or not hmac.compare_digest(f"Bearer {expected}", supplied):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        return {"ok": True, **TA.send_daily_suggestion()}
    except Exception as exc:
        return JSONResponse({"error": f"Daily suggestion failed: {exc}"}, status_code=502)


@app.get("/telegram/health")
def telegram_health():
    return {
        "bot_configured": TA.telegram_configured(),
        "chat_configured": bool(os.environ.get("TELEGRAM_CHAT_ID", "").strip()),
        "worker_configured": bool(os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip()),
    }


class PullReq(BaseModel):
    mode: str            # "topic" | "links" | "reference"
    query: str = ""      # topic text, or newline-separated URLs
    source_type: str = "auto"


@app.post("/pull")
def pull(req: PullReq):
    if req.mode == "topic":
        try:
            result = P.generate_topic_carousel(
                req.query, count=8, source_type=req.source_type)
        except Exception as e:
            return JSONResponse({"error": f"Topic generation failed: {e}"}, status_code=502)
        return result
    if req.mode in ("youtube", "video"):
        try:
            return P.generate_video_carousel(req.query, count=8)
        except Exception as e:
            return JSONResponse({"error": f"Video breakdown failed: {e}"}, status_code=502)
    return JSONResponse({"error": "unknown mode"}, status_code=400)


@app.post("/upload-video")
async def upload_video(request: Request):
    """Analyze a local video or screen recording without keeping the upload."""
    if P.IS_VERCEL:
        return JSONResponse({
            "error": "Video upload analysis is local-only because it needs ffmpeg."
        }, status_code=503)
    filename = request.headers.get("x-filename", "recording.mp4")
    extension = os.path.splitext(filename)[1].lower()
    if extension not in (".mp4", ".mov", ".m4v", ".webm", ".mkv"):
        return JSONResponse({
            "error": "Upload an MP4, MOV, M4V, WebM, or MKV recording."
        }, status_code=400)
    safe_stem = "".join(c if c.isalnum() else "_" for c in os.path.splitext(filename)[0])[:60]
    path = os.path.join(
        UPLOADS, f"{safe_stem or 'recording'}_{uuid.uuid4().hex[:10]}{extension}")
    size = 0
    try:
        with open(path, "wb") as destination:
            async for chunk in request.stream():
                size += len(chunk)
                if size > 300 * 1024 * 1024:
                    raise ValueError("Upload must be 300 MB or smaller")
                destination.write(chunk)
        if size == 0:
            raise ValueError("The uploaded file is empty")
        return P.generate_uploaded_video_carousel(path, count=8)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Video analysis failed: {exc}"}, status_code=502)
    finally:
        if os.path.exists(path):
            os.remove(path)


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
    source_type: str = "auto"
    author: str = ""
    published_at: str = ""
    evidence: str = ""


class BuildReq(BaseModel):
    resources: list[Resource]
    bg_query: str = "cozy interior warm light"
    cover_title: str = "AI RESOURCES"
    cover_hook: str = ""
    include_what_it_does: bool = True
    include_why_youll_need_it: bool = True
    split_mode: str = "single"
    comment_keyword: str = "CLAUDE"
    visual_style: str = "editorial_reference"
    canvas_format: str = "editorial_3_4"


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
    source_type: str = "auto"


@app.post("/screenshot-preview")
def screenshot_preview(req: ScreenshotPreviewReq, request: Request):
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        return JSONResponse({"error": "Enter a full link starting with http:// or https://."}, status_code=400)
    safe_name = "".join(c if c.isalnum() else "_" for c in req.name).strip("_")[:50] or "preview"
    oidc_token = _blob_oidc_token(request)
    try:
        M.require_blob(oidc_token)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    try:
        source_type = (
            P.source_type_for_url(url)
            if req.source_type in ("", "auto", "unknown", "video_source")
            else req.source_type
        )
        if source_type == "youtube_video":
            path = P.C.build_resource_preview(
                req.name or "YouTube video", url, req.description,
                out=f"preview_{safe_name}_youtube.png", require_image=True)
            fallback = False
        else:
            path = P.capture(url, f"preview_{safe_name}", source_type=source_type)
            fallback = False
    except Exception as e:
        try:
            if P.source_type_for_url(url) == "youtube_video":
                raise RuntimeError(
                    "This YouTube URL has no usable public thumbnail. "
                    "Choose a public, available video."
                )
            path = P.C.build_resource_preview(
                req.name or "Website", url, req.description,
                out=f"preview_{safe_name}_fallback.png")
            fallback = True
        except Exception:
            return JSONResponse({"error": f"Screenshot preview failed: {e}"}, status_code=502)
    try:
        image_url = (
            M.publish_file(path, oidc_token=oidc_token)
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
def build(req: BuildReq, request: Request):
    resources = [r.model_dump() for r in req.resources]
    if not resources:
        return JSONResponse({"error": "no resources selected"}, status_code=400)
    oidc_token = _blob_oidc_token(request)
    try:
        M.require_blob(oidc_token)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    try:
        result = P.build_carousel(
            resources, bg_query=req.bg_query,
            cover_title=req.cover_title, cover_hook=req.cover_hook or None,
            include_what_it_does=req.include_what_it_does,
            include_why_youll_need_it=req.include_why_youll_need_it,
            split_mode=req.split_mode,
            comment_keyword=req.comment_keyword,
            visual_style=req.visual_style,
            canvas_format=req.canvas_format)
        result = M.publish_carousel(
            result,
            P.OUT,
            os.path.join(ROOT, "backgrounds"),
            oidc_token,
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return result
