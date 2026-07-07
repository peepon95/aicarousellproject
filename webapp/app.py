#!/usr/bin/env python3
"""
Local web UI for the AI resource carousel engine.
Run:  .venv/bin/uvicorn webapp.app:app --reload --port 8000
Open: http://localhost:8000
"""
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import pipeline as P

ROOT = P.ROOT
HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="AI Carousel Studio")
INDEX = os.path.join(HERE, "templates", "index.html")

# serve generated slides + inbox drafts
app.mount("/out", StaticFiles(directory=P.OUT), name="out")
INBOX = os.path.join(ROOT, "inbox")
os.makedirs(INBOX, exist_ok=True)
app.mount("/inbox", StaticFiles(directory=INBOX), name="inbox")


@app.get("/", response_class=HTMLResponse)
def home():
    with open(INDEX, encoding="utf-8") as f:
        return HTMLResponse(f.read())


class PullReq(BaseModel):
    mode: str            # "topic" | "links" | "reference"
    query: str = ""      # topic text, or newline-separated URLs


@app.post("/pull")
def pull(req: PullReq):
    if req.mode == "topic":
        try:
            cands = P.pull_github(req.query, n=12)
        except Exception as e:
            return JSONResponse({"error": f"GitHub pull failed: {e}"}, status_code=502)
        return {"candidates": cands}
    if req.mode == "links":
        urls = [u for u in req.query.replace(",", "\n").splitlines() if u.strip()]
        return {"candidates": [P.resource_from_url(u) for u in urls]}
    if req.mode == "reference":
        return JSONResponse(
            {"error": "Reference mimic is Phase 2 — not wired up yet."},
            status_code=501)
    return JSONResponse({"error": "unknown mode"}, status_code=400)


class Resource(BaseModel):
    name: str
    url: str
    desc: str = ""
    stars: int = 0
    hook: str = ""
    kind: str = ""


class BuildReq(BaseModel):
    resources: list[Resource]
    bg_query: str = "cozy interior warm light"
    cover_title: str = "AI RESOURCES"
    cover_hook: str = ""


@app.post("/build")
def build(req: BuildReq):
    resources = [r.model_dump() for r in req.resources]
    if not resources:
        return JSONResponse({"error": "no resources selected"}, status_code=400)
    try:
        result = P.build_carousel(
            resources, bg_query=req.bg_query,
            cover_title=req.cover_title, cover_hook=req.cover_hook or None)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return result
