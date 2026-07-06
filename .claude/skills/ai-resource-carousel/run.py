#!/usr/bin/env python3
"""
Orchestrator: pull -> shortlist (human) -> screenshot -> photo -> compose.
Run inside Claude Code: the agent calls these steps, shows you the shortlist,
and you approve before slides are built. This file is also runnable directly.
"""
import os, json, urllib.request, urllib.parse
from fetch_pexels import fetch_background
from capture_screenshot import capture
import compose_fullbleed as C

def pull_github(topic, n=10):
    url = ("https://api.github.com/search/repositories?"
           + urllib.parse.urlencode({"q": topic, "sort": "stars", "order": "desc", "per_page": n}))
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    data = json.load(urllib.request.urlopen(req))
    return [{"name": r["full_name"], "url": r["html_url"],
             "desc": (r["description"] or "")[:100], "stars": r["stargazers_count"]}
            for r in data.get("items", [])]

def build_carousel(resources, bg_query="cozy interior warm light", title="AI RESOURCES"):
    """resources: list of dicts with name, url, desc, stars, bullets, hook."""
    slides, credits = [], set()
    for i, r in enumerate(resources):
        bg_path, attr = fetch_background(bg_query)
        credits.add(attr)
        bg_name = os.path.basename(bg_path)
        shot_name = None
        try:
            shot_path = capture(r["url"], r["name"].replace("/", "_"))
            shot_name = os.path.basename(shot_path)
        except Exception as e:
            print("screenshot skipped:", e)
        out = C.build(bg_name, f"{i+1}/{len(resources)}",
                      r.get("hook", r["name"]), r.get("desc", ""),
                      shot_name, r.get("bullets", []),
                      out=f"slide_{i:02d}.png")
        slides.append(out)
    print("credits:", "; ".join(sorted(credits)))
    return slides

if __name__ == "__main__":
    repos = pull_github("claude+skills", 8)
    print("Candidates:")
    for i, r in enumerate(repos):
        print(f"  [{i}] {r['name']} ★{r['stars']} — {r['desc']}")
    print("\nEdit this script or drive it from Claude Code to pick & build.")
