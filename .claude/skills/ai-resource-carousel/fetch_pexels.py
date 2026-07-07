#!/usr/bin/env python3
"""
Fetch a full-bleed background photo from Pexels (free API).
- Caches into backgrounds/ so we never re-fetch (Pexels recommends caching).
- Returns the local path + attribution string for crediting the photographer.

Setup: put PEXELS_API_KEY in a .env file (see .env.example).
Get a free key instantly at https://www.pexels.com/api/
"""
import os, json, random, urllib.request, urllib.parse

HERE = os.path.dirname(__file__)
BG = os.path.join(HERE, "..", "..", "..", "backgrounds")
BG = os.path.normpath(BG)
os.makedirs(BG, exist_ok=True)
CACHE_META = os.path.join(BG, "_attribution.json")

def _key():
    k = os.environ.get("PEXELS_API_KEY")
    if not k:
        raise RuntimeError("Set PEXELS_API_KEY in your .env (get a free key at pexels.com/api)")
    return k

def _search(query, orientation, per_page):
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": orientation, "per_page": per_page})
    req = urllib.request.Request(url, headers={"Authorization": _key(),
                                               "User-Agent": "ai-carousel/1.0"})
    return json.load(urllib.request.urlopen(req)).get("photos", [])

def _download(p):
    """Download one Pexels photo, cached on disk by its stable photo id so
    repeat runs reuse it (Pexels recommends caching)."""
    slug = str(p["id"])
    local = os.path.join(BG, f"{slug}.jpg")
    attribution = f'Photo by {p["photographer"]} on Pexels'
    if not os.path.exists(local):
        img_req = urllib.request.Request(p["src"]["large2x"],
                                         headers={"User-Agent": "ai-carousel/1.0"})
        with urllib.request.urlopen(img_req) as resp, open(local, "wb") as f:
            f.write(resp.read())
    meta = {}
    if os.path.exists(CACHE_META):
        meta = json.load(open(CACHE_META))
    meta[slug] = attribution
    json.dump(meta, open(CACHE_META, "w"), indent=2)
    return local, attribution

def fetch_backgrounds(query, count=1, orientation="portrait"):
    """Return `count` DISTINCT random background photos for one vibe/query, as
    a list of (local_path, attribution). One API call; images cached by id."""
    photos = _search(query, orientation, max(15, count * 2))
    if not photos:
        raise RuntimeError(f"No Pexels photos for '{query}'")
    random.shuffle(photos)
    if len(photos) >= count:
        chosen = photos[:count]
    else:  # not enough unique photos — cycle through what we have
        chosen = [photos[i % len(photos)] for i in range(count)]
    return [_download(p) for p in chosen]

def fetch_background(query, orientation="portrait"):
    """Single random background for the query (back-compat wrapper)."""
    return fetch_backgrounds(query, 1, orientation)[0]

if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "cozy interior warm light"
    path, attr = fetch_background(q)
    print(path); print(attr)
