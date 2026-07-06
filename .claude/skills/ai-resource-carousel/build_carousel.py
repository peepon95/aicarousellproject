#!/usr/bin/env python3
"""
Driver: build the 4-slide "design skills to download" carousel.
Runs the full pipeline per slide: Pexels bg -> repo screenshot -> composite.
Reads .env from the project root; writes PNGs to out/.
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"), override=True)

from fetch_pexels import fetch_background
from capture_screenshot import capture
import compose_fullbleed as C

# Each slide: repo url, warm-aesthetic bg search, hook title, one-liner,
# and 3 "why you'll need this" bullets — plain-spoken, no hype.
SLIDES = [
    {
        "url": "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill",
        "shot": "ui_ux_pro_max",
        "bg": "warm minimal workspace desk",
        "title": "ui-ux-pro-max",
        "sub": "design intelligence for real interfaces",
        "bullets": [
            "turns vague prompts into real layouts",
            "works across web and mobile",
            "fewer 'make it look better' rounds",
        ],
    },
    {
        "url": "https://github.com/Leonxlnx/taste-skill",
        "shot": "taste_skill",
        "bg": "cozy studio warm light",
        "title": "taste-skill",
        "sub": "gives your AI actual taste",
        "bullets": [
            "stops generic AI slop",
            "better color and spacing by default",
            "output you don't have to redo",
        ],
    },
    {
        "url": "https://github.com/alchaincyf/huashu-design",
        "shot": "huashu_design",
        "bg": "designer desk plants warm light",
        "title": "huashu-design",
        "sub": "html-native design skill for claude code",
        "bullets": [
            "high-fidelity prototypes fast",
            "slides and animations too",
            "no figma round-trip",
        ],
    },
    {
        "url": "https://github.com/google-labs-code/stitch-skills",
        "shot": "stitch_skills",
        "bg": "moody warm interior window light",
        "title": "stitch-skills",
        "sub": "google's agent skills for stitch",
        "bullets": [
            "follows the open agent-skills spec",
            "design straight from your agent",
            "free and open source",
        ],
    },
]

# Cover / header slide that describes the whole carousel.
COVER = {
    "bg": "warm cozy workspace laptop coffee",
    "kicker": "AI DESIGN SKILLS",
    "title": "4 design skills your AI is missing",
    "sub": "free, open-source, and worth downloading",
}

def main():
    total = len(SLIDES) + 1  # cover + skills
    outs, credits = [], set()

    # --- cover slide (1/N) ---
    print(f"[1/{total}] cover")
    cbg, cattr = fetch_background(COVER["bg"])
    credits.add(cattr)
    print("   bg:", os.path.basename(cbg), "|", cattr)
    cover = C.build_cover(os.path.basename(cbg), COVER["kicker"],
                          COVER["title"], COVER["sub"], out="skill_00_cover.png")
    print("   ->", cover)
    outs.append(cover)

    # --- skill slides (2/N .. N/N) ---
    for i, s in enumerate(SLIDES):
        page = f"{i+2}/{total}"
        print(f"[{page}] {s['title']}")
        bg_path, attr = fetch_background(s["bg"])
        credits.add(attr)
        print("   bg:", os.path.basename(bg_path), "|", attr)
        shot_name = None
        try:
            shot_path = capture(s["url"], s["shot"])
            shot_name = os.path.basename(shot_path)
            print("   shot:", shot_name)
        except Exception as e:
            print("   screenshot skipped:", e)
        out = C.build(
            os.path.basename(bg_path), page,
            s["title"], s["sub"], shot_name, s["bullets"],
            out=f"skill_{i+1:02d}_{s['shot']}.png",
        )
        print("   ->", out)
        outs.append(out)
    print("\nDONE. Slides:")
    for o in outs:
        print("  ", o)
    print("\nPhoto credits (Pexels):")
    for c in sorted(credits):
        print("  ", c)

if __name__ == "__main__":
    main()
