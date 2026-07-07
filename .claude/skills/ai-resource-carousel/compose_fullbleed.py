#!/usr/bin/env python3
"""
Volkan-style slide: a FULL-BLEED photo fills the frame, content composited on top.
  - page badge (e.g. 1/5)
  - big outlined title + subtitle
  - real screenshot card
  - optional bullet list with a colored 'why you'll need this' header

On your machine backgrounds/ holds real Unsplash/Pexels photos.
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os, random, textwrap

W, H = 1080, 1350
HERE = os.path.dirname(__file__)
# backgrounds/, screenshots/, out/ live at the PROJECT ROOT (three levels up
# from this skill dir) so fetch_pexels.py, capture_screenshot.py and this
# compositor all read/write the same folders.
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
BG = os.path.join(ROOT, "backgrounds"); SHOT = os.path.join(ROOT, "screenshots")
OUT = os.path.join(ROOT, "out"); os.makedirs(OUT, exist_ok=True)

# macOS system fonts (the original DejaVu paths are Linux-only).
_FONTS = {
    True:  "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    False: "/System/Library/Fonts/Supplemental/Arial.ttf",
}
def font(sz, bold=True):
    return ImageFont.truetype(_FONTS[bool(bold)], sz)

def cover_photo(name):
    im = Image.open(os.path.join(BG, name)).convert("RGB")
    r = max(W/im.width, H/im.height)
    im = im.resize((int(im.width*r), int(im.height*r)))
    x=(im.width-W)//2; y=(im.height-H)//2
    return im.crop((x,y,x+W,y+H)).convert("RGBA")

def outlined(d, xy, text, fnt, fill=(255,255,255), outline=(0,0,0), w=4):
    x,y=xy
    for dx in range(-w,w+1):
        for dy in range(-w,w+1):
            if dx*dx+dy*dy <= w*w:
                d.text((x+dx,y+dy), text, font=fnt, fill=outline)
    d.text((x,y), text, font=fnt, fill=fill)

def center_outlined(d, y, text, fnt, **kw):
    tw=d.textlength(text,font=fnt); outlined(d,((W-tw)//2,y),text,fnt,**kw); return tw

def _wrap(d, text, fnt, max_w):
    """Greedy word-wrap so a headline fits inside max_w pixels."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

def build_cover(bg_name, kicker, title, subtitle, swipe="swipe →", out="cover.png"):
    """Intro/cover slide: full-bleed photo, big wrapped headline, subtitle,
    a small top kicker and a swipe cue. No screenshot card, no bullets."""
    img = cover_photo(bg_name)
    # darken slightly so big text always reads over a busy photo
    veil = Image.new("RGBA", (W, H), (0, 0, 0, 90))
    img = Image.alpha_composite(img, veil)
    d = ImageDraw.Draw(img)
    # top kicker pill
    if kicker:
        kf = font(34, True); kw = d.textlength(kicker, font=kf)
        d.rounded_rectangle([(W-kw)//2-24, 150, (W+kw)//2+24, 212], radius=14, fill=(220,40,40))
        d.text(((W-kw)//2, 162), kicker, font=kf, fill=(255,255,255))
    # big wrapped headline, vertically centred-ish
    hf = font(104, True)
    lines = _wrap(d, title, hf, int(W*0.86))
    lh = 118
    total = lh * len(lines)
    y = (H - total)//2 - 40
    for ln in lines:
        center_outlined(d, y, ln, hf, w=6); y += lh
    # subtitle
    if subtitle:
        y += 24
        center_outlined(d, y, subtitle, font(44, True), w=3)
    # swipe cue near bottom
    if swipe:
        sf = font(40, True); sw = d.textlength(swipe, font=sf)
        d.rounded_rectangle([(W-sw)//2-26, H-190, (W+sw)//2+26, H-124], radius=16, fill=(255,255,255))
        d.text(((W-sw)//2, H-182), swipe, font=sf, fill=(20,20,20))
    p = os.path.join(OUT, out); img.convert("RGB").save(p, quality=95); return p

def build(bg_name, page, title, subtitle, shot_name, bullets, why="Why you'll need this:", out="slide.png"):
    img = cover_photo(bg_name)
    d = ImageDraw.Draw(img)
    # page badge
    pf=font(30,True); bw=d.textlength(page,font=pf)
    d.rounded_rectangle([(W-bw)//2-24, 70, (W+bw)//2+24, 128], radius=14, fill=(220,40,40))
    d.text(((W-bw)//2, 82), page, font=pf, fill=(255,255,255))
    # title — auto-shrink + wrap to at most 2 lines so it never bleeds off frame
    tsize = 88
    while tsize > 44:
        tf = font(tsize, True)
        tlines = _wrap(d, title, tf, int(W*0.88))
        if len(tlines) <= 2 and max(d.textlength(l, font=tf) for l in tlines) <= W*0.9:
            break
        tsize -= 6
    tf = font(tsize, True); tlines = _wrap(d, title, tf, int(W*0.88))[:2]
    ty = 158; tlh = tsize + 12
    for ln in tlines:
        center_outlined(d, ty, ln, tf, w=5); ty += tlh
    # subtitle (wrapped, up to 2 lines) directly under the title
    if subtitle:
        sf = font(38, True)
        for ln in _wrap(d, subtitle, sf, int(W*0.9))[:2]:
            center_outlined(d, ty, ln, sf, w=3); ty += 46
    # screenshot card — starts below whatever height the title block used
    card_top = max(350, ty + 24)
    if shot_name and os.path.exists(os.path.join(SHOT,shot_name)):
        s=Image.open(os.path.join(SHOT,shot_name)).convert("RGBA")
        tw=int(W*0.82); th=int(s.height*tw/s.width); s=s.resize((tw,th))
        sh=Image.new("RGBA",(W,H),(0,0,0,0))
        ImageDraw.Draw(sh).rectangle([(W-tw)//2+8,card_top+8,(W-tw)//2+tw+8,card_top+th+8],fill=(0,0,0,150))
        img=Image.alpha_composite(img,sh.filter(ImageFilter.GaussianBlur(18)))
        img.alpha_composite(s,((W-tw)//2,card_top)); d=ImageDraw.Draw(img)
        by=card_top+th+40
    else:
        by=max(780, card_top)
    # why header
    hf=font(46,True); hw=d.textlength(why,font=hf)
    d.rounded_rectangle([(W-hw)//2-20,by,(W+hw)//2+20,by+66],radius=10,fill=(220,40,40))
    d.text(((W-hw)//2,by+8),why,font=hf,fill=(255,255,255)); by+=90
    # bullets
    bf=font(40,True)
    for b in bullets:
        center_outlined(d, by, "• "+b, bf, w=3); by+=58
    p=os.path.join(OUT,out); img.convert("RGB").save(p,quality=95); return p

if __name__=="__main__":
    print(build("photo_style_test.jpg","1/5","REST APIs","How apps communicate using HTTP requests",
        "claude-code.png",
        ["used in almost every app","handles frontend -> backend","shows up in most job descriptions"],
        out="volkan_style_demo.png"))
