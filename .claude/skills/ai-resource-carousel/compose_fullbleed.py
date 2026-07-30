#!/usr/bin/env python3
"""
Volkan-style slide: a FULL-BLEED photo fills the frame, content composited on top.
  - big outlined title + subtitle
  - real screenshot card
  - optional explanatory note with a colored 'what it does' header

On your machine backgrounds/ holds real Unsplash/Pexels photos.
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import os, random, textwrap

W, H = 1080, 1350
HERE = os.path.dirname(__file__)
# All generators share a writable data root. Locally this remains the project
# folder; Vercel points it at /tmp through webapp.pipeline.
PROJECT_ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
ROOT = os.environ.get("AICAROUSEL_DATA_DIR", PROJECT_ROOT)
BG = os.path.join(ROOT, "backgrounds"); SHOT = os.path.join(ROOT, "screenshots")
OUT = os.path.join(ROOT, "out")
for folder in (BG, SHOT, OUT):
    os.makedirs(folder, exist_ok=True)

_FONT_CANDIDATES = {
    True: (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    False: (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
}
def font(sz, bold=True):
    for path in _FONT_CANDIDATES[bool(bold)]:
        if os.path.exists(path):
            return ImageFont.truetype(path, sz)
    return ImageFont.load_default(size=sz)

def cover_photo(name):
    if not name:
        return Image.new("RGBA", (W, H), (238, 229, 211, 255))
    im = Image.open(os.path.join(BG, name)).convert("RGB")
    r = max(W/im.width, H/im.height)
    im = im.resize((int(im.width*r), int(im.height*r)))
    x=(im.width-W)//2; y=(im.height-H)//2
    im = im.crop((x,y,x+W,y+H))
    # Warm, muted editorial grade: softer highlights, richer shadows and a
    # subtle cream cast that keeps independently sourced photos cohesive.
    im = ImageEnhance.Color(im).enhance(0.82)
    im = ImageEnhance.Contrast(im).enhance(1.10)
    im = ImageEnhance.Brightness(im).enhance(0.94).convert("RGBA")
    grade = Image.new("RGBA", (W, H), (238, 196, 132, 22))
    return Image.alpha_composite(im, grade)

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

def build_resource_preview(name, url, description, out="resource_fallback.png"):
    """Create an honest, polished preview when a site blocks automation.

    This is intentionally not a fake browser screenshot: it is a branded
    resource card containing only metadata we already know.
    """
    im = Image.new("RGBA", (1200, 820), (246, 240, 227, 255))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((54, 48, 1146, 772), radius=34,
                        fill=(255, 252, 244), outline=(43, 39, 34), width=3)
    d.rounded_rectangle((90, 86, 262, 130), radius=12, fill=(220, 92, 50))
    d.text((110, 94), "WEBSITE", font=font(24, True), fill=(255, 255, 255))
    nf = font(88, True)
    name_lines = _wrap(d, name, nf, 980)[:2]
    y = 190
    for line in name_lines:
        d.text((90, y), line, font=nf, fill=(31, 29, 26)); y += 100
    df = font(42, False)
    for line in _wrap(d, description, df, 980)[:3]:
        d.text((92, y+18), line, font=df, fill=(78, 71, 62)); y += 54
    host = url.replace("https://", "").replace("http://", "").rstrip("/")
    d.line((90, 670, 1110, 670), fill=(214, 200, 178), width=2)
    d.text((92, 698), host, font=font(34, True), fill=(220, 92, 50))
    p = os.path.join(SHOT, out)
    im.convert("RGB").save(p, quality=95)
    return p

def build_cover(bg_name, kicker, title, subtitle, swipe="", out="cover.png"):
    """Intro/cover slide: optional full-bleed photo and a viral hook.
    No page counter or swipe button."""
    img = cover_photo(bg_name)
    # Cinematic vertical gradient keeps the person visible while giving the
    # oversized editorial hook enough contrast.
    veil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(veil)
    for y in range(H):
        alpha = int(45 + 115 * (y / H))
        vd.line((0, y, W, y), fill=(18, 15, 12, alpha))
    img = Image.alpha_composite(img, veil)
    d = ImageDraw.Draw(img)
    # top kicker pill
    if kicker:
        kf = font(34, True); kw = d.textlength(kicker, font=kf)
        d.rounded_rectangle([(W-kw)//2-24, 150, (W+kw)//2+24, 212], radius=14, fill=(220,40,40))
        d.text(((W-kw)//2, 162), kicker, font=kf, fill=(255,255,255))
    # Oversized, left-aligned hook inspired by editorial TikTok covers.
    hf = font(112, True)
    lines = _wrap(d, title, hf, int(W*0.82))
    while len(lines) > 5 and hf.size > 72:
        hf = font(hf.size - 6, True)
        lines = _wrap(d, title, hf, int(W*0.82))
    lh = hf.size + 2
    total = lh * len(lines)
    y = max(100, (H - total)//2 - 35)
    for ln in lines:
        d.text((58, y), ln, font=hf, fill=(255, 247, 184)); y += lh
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

def build(bg_name, page, title, subtitle, shot_name, why_text,
          use_photo_background=True, out="slide.png", source_url="",
          include_what_it_does=True, best_for_text="",
          include_why_youll_need_it=True, what_title="WHAT IT DOES",
          why_title="WHY YOU'LL NEED IT"):
    has_shot = bool(shot_name and os.path.exists(os.path.join(SHOT, shot_name)))
    if use_photo_background and bg_name:
        img = cover_photo(bg_name)
        img = Image.alpha_composite(img, Image.new("RGBA", (W, H), (12, 12, 12, 72)))
    else:
        # Blank background prompt is an explicit opt-out of photography.
        img = Image.new("RGBA", (W, H), (238, 229, 211, 255))
        paper = Image.new("RGBA", (W, H), (255, 248, 230, 18))
        img = Image.alpha_composite(img, paper)
    d = ImageDraw.Draw(img)
    # Deliberately no 1/4-style page counter: the carousel platform already
    # communicates sequence and the badge competes with the hook.
    # title — auto-shrink + wrap to at most 2 lines so it never bleeds off frame
    tsize = 88
    while tsize > 44:
        tf = font(tsize, True)
        tlines = _wrap(d, title, tf, int(W*0.88))
        if len(tlines) <= 2 and max(d.textlength(l, font=tf) for l in tlines) <= W*0.9:
            break
        tsize -= 6
    tf = font(tsize, True); tlines = _wrap(d, title, tf, int(W*0.88))[:2]
    tlh = tsize + 12
    sf = font(38, True)
    subtitle_lines = _wrap(d, subtitle, sf, int(W*0.9))[:2] if subtitle else []
    bf = font(39, True)
    why_lines = _wrap(d, why_text, bf, W-176) if include_what_it_does else []
    best_lines = (_wrap(d, best_for_text, bf, W-176)
                  if include_why_youll_need_it and best_for_text else [])
    while len(why_lines) + len(best_lines) > 6 and bf.size > 28:
        bf = font(bf.size - 2, True)
        why_lines = _wrap(d, why_text, bf, W-176) if include_what_it_does else []
        best_lines = (_wrap(d, best_for_text, bf, W-176)
                      if include_why_youll_need_it and best_for_text else [])
    url_lines = _wrap(d, source_url, font(25, False), W-176)[:1] if source_url else []
    line_h = bf.size + 9
    section_gap = 24 if why_lines and best_lines else 0
    what_h = (48 + len(why_lines) * line_h) if why_lines else 0
    need_h = (48 + len(best_lines) * line_h) if best_lines else 0
    takeaway_h = 52 + what_h + section_gap + need_h + (42 if url_lines else 0)
    if not why_lines and not best_lines:
        takeaway_h = 0

    if has_shot:
        ty = 158
    else:
        # Treat title + explanation + takeaway as one composition. Centering
        # the measured stack prevents all content from hugging the top while
        # leaving a large unused lower half.
        title_h = len(tlines) * tlh
        subtitle_h = len(subtitle_lines) * 46
        stack_h = title_h + subtitle_h + 46 + takeaway_h
        ty = max(96, (H-stack_h)//2)
    for ln in tlines:
        center_outlined(d, ty, ln, tf, w=5); ty += tlh
    # subtitle (wrapped, up to 2 lines) directly under the title
    if subtitle_lines:
        for ln in subtitle_lines:
            center_outlined(d, ty, ln, sf, w=3); ty += 46
    # screenshot card — starts below whatever height the title block used
    card_top = max(350, ty + 24)
    if has_shot:
        s=Image.open(os.path.join(SHOT,shot_name)).convert("RGBA")
        tw=int(W*0.84); th=int(s.height*tw/s.width)
        max_h = 555
        if th > max_h:
            th = max_h; tw = int(s.width * th / s.height)
        s=s.resize((tw,th))
        # Rounded screenshot card with a slim cream border.
        mask=Image.new("L",(tw,th),0)
        ImageDraw.Draw(mask).rounded_rectangle((0,0,tw-1,th-1),radius=24,fill=255)
        s.putalpha(mask)
        sh=Image.new("RGBA",(W,H),(0,0,0,0))
        ImageDraw.Draw(sh).rectangle([(W-tw)//2+8,card_top+8,(W-tw)//2+tw+8,card_top+th+8],fill=(0,0,0,150))
        img=Image.alpha_composite(img,sh.filter(ImageFilter.GaussianBlur(18)))
        border=Image.new("RGBA",(tw+8,th+8),(0,0,0,0))
        ImageDraw.Draw(border).rounded_rectangle((0,0,tw+7,th+7),radius=28,fill=(255,244,220,220))
        img.alpha_composite(border,((W-tw)//2-4,card_top-4))
        img.alpha_composite(s,((W-tw)//2,card_top)); d=ImageDraw.Draw(img)
        by=card_top+th+40
    else:
        # Video-derived conceptual slides have no screenshot. Do not reserve a
        # fake screenshot-sized gap; continue naturally after the explanation.
        by=ty+46
    # A single concrete reason, presented as an editorial note rather than a
    # generic red label plus engagement bullets.
    if not why_lines and not best_lines:
        p=os.path.join(OUT,out); img.convert("RGB").save(p,quality=95); return p
    lines = why_lines
    # Size the card to its content instead of stretching it to the bottom of
    # every slide. This keeps short takeaways deliberate and compact.
    card_h = 52 + what_h + section_gap + need_h + (42 if url_lines else 0)
    by = min(by, H - card_h - 72)
    box = (58, by, W-58, by+card_h)
    d.rounded_rectangle(box, radius=28, fill=(28,26,23,245), outline=(84,73,61,120), width=2)
    label_f = font(28, True)
    def draw_section_title(text, y):
        label = (text or "").strip()
        section_f = label_f
        while d.textlength(label, font=section_f) > W-176 and section_f.size > 18:
            section_f = font(section_f.size - 2, True)
        d.text((88, y), label, font=section_f, fill=(232,166,96))

    yy=by+24
    if lines:
        draw_section_title(what_title, yy)
        yy += 48
        for line in lines:
            d.text((88, yy), line, font=bf, fill=(255,250,239)); yy += line_h
    if best_lines:
        yy += section_gap
        draw_section_title(why_title, yy)
        yy += 48
        for line in best_lines:
            d.text((88, yy), line, font=bf, fill=(255,250,239)); yy += line_h
    if url_lines:
        d.text((88, yy+4), url_lines[0], font=font(25, False), fill=(232,166,96))
    p=os.path.join(OUT,out); img.convert("RGB").save(p,quality=95); return p


def build_cta(bg_name, headline="FOLLOW FOR MORE", username="vonn.gpt",
              use_photo_background=True, out="cta.png", comment_keyword="CLAUDE"):
    """Final carousel slide with a native-looking follow/save CTA."""
    if use_photo_background and bg_name:
        img = cover_photo(bg_name)
        img = Image.alpha_composite(img, Image.new("RGBA", (W, H), (16, 14, 12, 92)))
    else:
        img = Image.new("RGBA", (W, H), (238, 229, 211, 255))
        img = Image.alpha_composite(img, Image.new("RGBA", (W, H), (255, 248, 230, 26)))

    d = ImageDraw.Draw(img)
    # Soft paper panel, sized like the note/card system used on detail slides.
    panel = (112, 300, W - 112, 925)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (panel[0] + 10, panel[1] + 12, panel[2] + 10, panel[3] + 12),
        radius=38, fill=(0, 0, 0, 118))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(panel, radius=38, fill=(255, 249, 235, 238),
                        outline=(58, 50, 42, 190), width=3)

    message_f = font(72, True)
    first_plain = "Comment "
    first_accent = (comment_keyword or "CLAUDE").strip()[:30]
    while (d.textlength(first_plain + first_accent, font=message_f)
           > panel[2] - panel[0] - 90 and message_f.size > 54):
        message_f = font(message_f.size - 4, True)
    x = panel[0] + 48
    y = 390
    d.text((x, y), first_plain, font=message_f, fill=(31, 29, 26))
    accent_x = x + d.textlength(first_plain, font=message_f)
    d.text((accent_x, y), first_accent, font=message_f, fill=(220, 92, 50))
    d.text((x, y + 112), "and I will send you", font=message_f, fill=(31, 29, 26))
    d.text((x, y + 224), "the guide", font=message_f, fill=(31, 29, 26))

    bottom_f = font(48, True)
    bottom_lines = [headline.lower()]
    y = 1110
    for line in bottom_lines:
        tw = d.textlength(line, font=bottom_f)
        outlined(d, ((W - tw)//2, y), line, bottom_f,
                 fill=(255, 250, 239), outline=(0, 0, 0), w=3)
        y += 58

    p = os.path.join(OUT, out)
    img.convert("RGB").save(p, quality=95)
    return p

if __name__=="__main__":
    print(build("photo_style_test.jpg","","REST APIs","How apps communicate using HTTP requests",
        "claude-code.png",
        "Build and ship useful work faster, without adding another complicated workflow.",
        out="volkan_style_demo.png"))
