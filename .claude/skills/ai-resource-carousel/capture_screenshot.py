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
import urllib.parse
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

def _source_type(url, requested="auto"):
    if requested and requested != "auto":
        return requested
    parsed = urllib.parse.urlparse(url)
    host, path = parsed.netloc.lower().removeprefix("www."), parsed.path
    if host == "github.com":
        return "github_repo"
    if host in ("youtube.com", "m.youtube.com", "youtu.be"):
        return "youtube_channel" if path.startswith(("/@", "/channel/", "/c/", "/user/")) else "youtube_video"
    if host == "substack.com" or host.endswith(".substack.com"):
        return "substack_article"
    return "tool_website"


def _content_selectors(source_type):
    return {
        "github_repo": ("main", "#repo-content-pjax-container"),
        "youtube_video": ("#primary", "ytd-watch-flexy", "main"),
        "youtube_channel": ("#page-header", "ytd-browse", "main"),
        "substack_article": ("article", "main article", "main"),
        "tool_website": ("main", "[role=main]"),
    }.get(source_type, ("main", "[role=main]"))


def _capture_content(page, out, source_type, clip_height):
    """Crop around recognizable page content instead of browser chrome."""
    for selector in _content_selectors(source_type):
        try:
            locator = page.locator(selector).first
            if not locator.is_visible(timeout=700):
                continue
            box = locator.bounding_box()
            if not box or box["width"] < 420 or box["height"] < 180:
                continue
            x = max(0, min(box["x"], 1279))
            y = max(0, box["y"])
            width = min(box["width"], 1280 - x)
            height = min(max(420, clip_height), box["height"])
            page.screenshot(path=out, clip={"x": x, "y": y, "width": width, "height": height})
            return
        except Exception:
            continue
    page.screenshot(path=out, clip={"x": 0, "y": 0, "width": 1280, "height": clip_height})


def capture(url, name, clip_height=820, source_type="auto"):
    """Capture a source-aware, editorial crop of a public page."""
    if os.environ.get("VERCEL"):
        raise RuntimeError(
            "Browser capture is disabled on Vercel; using the generated preview fallback."
        )
    out = os.path.join(SHOT, name if name.endswith(".png") else name + ".png")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 960},
                                device_scale_factor=2)
        # 'networkidle' rarely fires on GitHub (live connections stay open),
        # so wait for the DOM + a short settle instead.
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        _dismiss_consent(page)
        page.wait_for_timeout(500)
        page.add_style_tag(content="""
          [role='dialog'], [aria-modal='true'], .modal-backdrop,
          [class*='cookie'][style*='fixed'], [class*='consent'][style*='fixed'] {
            display: none !important;
          }
        """)
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
        _capture_content(page, out, _source_type(url, source_type), clip_height)
        if not os.path.exists(out) or os.path.getsize(out) < 12_000:
            raise RuntimeError("page capture did not contain enough visible content")
        browser.close()
    return out

if __name__ == "__main__":
    import sys
    url = sys.argv[1]; name = sys.argv[2] if len(sys.argv) > 2 else "shot"
    print(capture(url, name))
