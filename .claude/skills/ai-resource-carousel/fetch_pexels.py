#!/usr/bin/env python3
"""
Fetch a full-bleed background photo from Pexels (free API).
- Caches into backgrounds/ so we never re-fetch (Pexels recommends caching).
- Returns the local path + attribution string for crediting the photographer.

Setup: put PEXELS_API_KEY in a .env file (see .env.example).
Get a free key instantly at https://www.pexels.com/api/
"""
import os, json, hashlib, urllib.request, urllib.parse

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

def fetch_background(query, orientation="portrait"):
    """Return (local_path, attribution_str). Cached by query."""
    slug = hashlib.md5(f"{query}-{orientation}".encode()).hexdigest()[:10]
    local = os.path.join(BG, f"{slug}.jpg")
    meta = {}
    if os.path.exists(CACHE_META):
        meta = json.load(open(CACHE_META))
    if os.path.exists(local) and slug in meta:
        return local, meta[slug]  # cache hit

    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": orientation, "per_page": 15})
    req = urllib.request.Request(url, headers={"Authorization": _key(),
                                               "User-Agent": "ai-carousel/1.0"})
    data = json.load(urllib.request.urlopen(req))
    photos = data.get("photos", [])
    if not photos:
        raise RuntimeError(f"No Pexels photos for '{query}'")
    # pick highest-liked-ish first result; you could randomize among top 5 for variety
    p = photos[0]
    img_url = p["src"]["large2x"]
    img_req = urllib.request.Request(img_url, headers={"User-Agent": "ai-carousel/1.0"})
    with urllib.request.urlopen(img_req) as resp, open(local, "wb") as f:
        f.write(resp.read())
    attribution = f'Photo by {p["photographer"]} on Pexels'
    meta[slug] = attribution
    json.dump(meta, open(CACHE_META, "w"), indent=2)
    return local, attribution

if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "cozy interior warm light"
    path, attr = fetch_background(q)
    print(path); print(attr)
