#!/usr/bin/env python3
"""
Capture a clean screenshot of a resource page (GitHub repo, HF model card, docs).
Runs on your machine via Playwright — not available in the chat sandbox.

One-time setup:
    pip install playwright
    playwright install chromium
"""
import os
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(__file__)
SHOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", "screenshots"))
os.makedirs(SHOT, exist_ok=True)

def capture(url, name, clip_height=820):
    """Screenshot the top of a page. Returns local path."""
    out = os.path.join(SHOT, name if name.endswith(".png") else name + ".png")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 900},
                                device_scale_factor=2)
        # 'networkidle' rarely fires on GitHub (live connections stay open),
        # so wait for the DOM + a short settle instead.
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        # dismiss GitHub cookie banner if present
        try:
            page.click("button:has-text('Accept')", timeout=2000)
        except Exception:
            pass
        page.screenshot(path=out, clip={"x": 0, "y": 0, "width": 1200, "height": clip_height})
        browser.close()
    return out

if __name__ == "__main__":
    import sys
    url = sys.argv[1]; name = sys.argv[2] if len(sys.argv) > 2 else "shot"
    print(capture(url, name))
