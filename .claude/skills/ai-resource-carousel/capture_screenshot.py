#!/usr/bin/env python3
"""
Capture a clean screenshot of a resource page (GitHub repo, HF model card, docs).
Runs on your machine via Playwright — not available in the chat sandbox.

One-time setup:
    pip install playwright
    playwright install chromium
"""
import os
import re
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(__file__)
PROJECT_ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
DATA_ROOT = os.environ.get("AICAROUSEL_DATA_DIR", PROJECT_ROOT)
SHOT = os.path.join(DATA_ROOT, "screenshots")
os.makedirs(SHOT, exist_ok=True)

def _dismiss_consent(page):
    """Best-effort cleanup for common cookie/privacy overlays."""
    labels = ("Accept all", "Allow all", "Accept cookies", "Accept all cookies",
              "I agree", "Agree", "Got it", "Continue", "Reject all",
              "Deny", "Only necessary")
    for frame in page.frames:
        for label in labels:
            try:
                button = frame.get_by_role(
                    "button", name=re.compile(rf"^{re.escape(label)}$", re.I)).first
                if button.is_visible(timeout=250):
                    button.click(timeout=1000)
                    page.wait_for_timeout(350)
                    return
            except Exception:
                pass
    page.evaluate("""() => {
      const marker = /cookie|consent|privacy|onetrust|trustarc|usercentrics|cookiefirst|cookiebot/i;
      document.querySelectorAll('body *').forEach(el => {
        const identity = `${el.id || ''} ${el.className || ''} ${el.getAttribute('aria-label') || ''}`;
        const style = getComputedStyle(el);
        if (marker.test(identity) && (style.position === 'fixed' || style.position === 'sticky' || el.tagName === 'DIALOG')) el.remove();
      });
      document.documentElement.style.overflow = 'auto';
      document.body.style.overflow = 'auto';
    }""")

def capture(url, name, clip_height=820):
    """Screenshot the top of a page. Returns local path."""
    if os.environ.get("VERCEL"):
        raise RuntimeError(
            "Browser capture is disabled on Vercel; using the generated preview fallback."
        )
    out = os.path.join(SHOT, name if name.endswith(".png") else name + ".png")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 900},
                                device_scale_factor=2)
        # 'networkidle' rarely fires on GitHub (live connections stay open),
        # so wait for the DOM + a short settle instead.
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        _dismiss_consent(page)
        page.wait_for_timeout(500)
        # Some sites (notably Replit) return a visually rendered Cloudflare
        # block page with HTTP 200. Never pass that off as a product preview.
        body = page.locator("body").inner_text(timeout=5000).lower()
        blocked_markers = (
            "sorry, you have been blocked",
            "you are unable to access",
            "attention required! | cloudflare",
            "verify you are human",
        )
        if (response and response.status >= 400) or any(m in body for m in blocked_markers):
            status = response.status if response else "unknown"
            raise RuntimeError(f"site blocked automated capture (HTTP {status})")
        page.screenshot(path=out, clip={"x": 0, "y": 0, "width": 1200, "height": clip_height})
        browser.close()
    return out

if __name__ == "__main__":
    import sys
    url = sys.argv[1]; name = sys.argv[2] if len(sys.argv) > 2 else "shot"
    print(capture(url, name))
