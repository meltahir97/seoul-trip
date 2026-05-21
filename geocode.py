#!/usr/bin/env python3
"""
Geocode all spots in spots.json.

Primary geocoder : Kakao Local Search API
  — searches by Korean venue name, giving business-level precision.
  — the same backend used by Kakao Maps / KakaoTalk, best coverage for Korea.

Fallback geocoder: Nominatim (OpenStreetMap)
  — used only when Kakao is unavailable or returns no result.
  — accurate for OSM-mapped street addresses, less so for businesses.

── Setup (takes ~5 minutes, no credit card) ────────────────────────────────
  1. Go to https://developers.kakao.com and sign in with any Kakao account
  2. My Applications → Create Application → fill in any app name
  3. App Settings → App Keys → copy the REST API Key
  4. export KAKAO_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

── Usage ────────────────────────────────────────────────────────────────────
  python geocode.py              # geocode only spots with null coords
  python geocode.py --force      # re-geocode every spot
  python geocode.py --dry-run    # show what would change, don't write

── How to add a new spot ────────────────────────────────────────────────────
  1. Add the entry to spots.json (lat/lng omitted or null)
  2. Run:  python geocode.py
  3. Commit the updated spots.json
"""

import json, time, sys, os, urllib.request, urllib.parse, re

# ── API endpoints ────────────────────────────────────────────────────────────
KAKAO_SEARCH = "https://dapi.kakao.com/v2/local/search/keyword.json"
NOMINATIM    = "https://nominatim.openstreetmap.org/search"
NOM_HEADERS  = {"User-Agent": "seoul-trip-guide/1.0 (personal travel map)"}

# Seoul city centre — Kakao searches within 50 km radius of this point
SEOUL_LNG = 126.9820
SEOUL_LAT = 37.5665

# ── Spots skipped even with Kakao enabled ────────────────────────────────────
KAKAO_SKIP = {
    "Vita",    # unverified, no fixed Seoul address
    "DMZ",     # tour pickup, 60 km from Seoul centre
    "Beaker",  # intentionally multi-location, no single pin
}

# ── Nominatim: address patterns that cannot be geocoded reliably ─────────────
SKIP_ADDR = re.compile(
    r"unverified|verify via|confirm via|multiple locations|tour pickup|"
    r"check @|near \w+ station|instagram|pickup from|seongsu-dong$|"
    r"hannamdong$|itaewon$|cheongdam-dong$|apgujeong$|hongdae flagship$|"
    r"dosan park area$|haus dosan|ikseon-dong$|samcheongdong, jongno|"
    r"sinsa \+ seongsu|hanganjin station|hapjeong main branch|sangsu-dong",
    re.IGNORECASE,
)

def addr_is_geocodeable(addr: str) -> bool:
    if not addr:
        return False
    if SKIP_ADDR.search(addr):
        return False
    if not re.search(r'\d', addr):
        return False
    has_road = bool(re.search(r'-ro\b|-gil\b|-ga\b|-daero\b|Namsangongwon', addr, re.I))
    has_dong = bool(re.search(r'-dong\b', addr, re.I))
    return has_road or has_dong

def clean_addr(addr: str) -> str:
    addr = re.sub(r'\s*\([^)]*\)', '', addr)
    addr = re.sub(r'\bB\d+\b',         '', addr, flags=re.I)
    addr = re.sub(r'\b\d+F\b',         '', addr, flags=re.I)
    addr = re.sub(r'\b\d+th floor\b',  '', addr, flags=re.I)
    addr = re.sub(r'\b[A-Z][a-z]+ (Building|Bldg)\b', '', addr)
    addr = re.sub(r'\s*\+.*$',         '', addr)
    addr = re.sub(r'/\d+[-\d]*',       '', addr)
    addr = re.sub(r'\barea\b',         '', addr, flags=re.I)
    addr = re.sub(r',\s*,',            ',', addr)
    addr = addr.strip().strip(',').strip()
    return f"{addr}, Seoul, South Korea"

# ── Kakao Local Search ───────────────────────────────────────────────────────
def kakao_lookup(name: str, kr: str, area: str, api_key: str) -> tuple[float, float] | None:
    """
    Try three queries in order of specificity:
      1. Korean name alone           (e.g. "치킨락")          — most precise
      2. English name + area         (e.g. "Chicken Rock Yeonnam")
      3. Korean name + area          (e.g. "치킨락 연남")     — disambiguates chains
    """
    queries = []
    if kr and kr.strip():
        queries.append(kr.strip())
    queries.append(f"{name} {area}".strip())
    if kr and kr.strip() and area:
        queries.append(f"{kr.strip()} {area}")

    headers = {"Authorization": f"KakaoAK {api_key}"}
    for q in queries:
        params = urllib.parse.urlencode({
            "query": q,
            "x": SEOUL_LNG, "y": SEOUL_LAT,
            "radius": 50000,
            "size": 1,
        })
        req = urllib.request.Request(f"{KAKAO_SEARCH}?{params}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                docs = json.loads(resp.read()).get("documents", [])
            if docs:
                lat = round(float(docs[0]["y"]), 5)
                lng = round(float(docs[0]["x"]), 5)
                print(f"    kakao ({repr(q)}): {lat}, {lng}")
                return lat, lng
        except Exception as e:
            print(f"    ⚠  Kakao error: {e}")
            return None
        time.sleep(0.05)
    return None

# ── Nominatim ────────────────────────────────────────────────────────────────
def nominatim_lookup(query: str) -> tuple[float, float] | None:
    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1})
    req    = urllib.request.Request(f"{NOMINATIM}?{params}", headers=NOM_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read())
        if results:
            return round(float(results[0]["lat"]), 5), round(float(results[0]["lon"]), 5)
    except Exception as e:
        print(f"    ⚠  Nominatim error: {e}")
    return None

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    force   = "--force"   in sys.argv
    dry_run = "--dry-run" in sys.argv
    api_key = os.environ.get("KAKAO_API_KEY", "").strip()

    if api_key:
        print("✓  Kakao Local Search API active\n")
    else:
        print("ℹ  KAKAO_API_KEY not set — falling back to Nominatim address geocoding.")
        print("   For business-level accuracy: export KAKAO_API_KEY=<your_rest_key>")
        print("   Free key (5 min): https://developers.kakao.com\n")

    with open("spots.json", encoding="utf-8") as f:
        spots = json.load(f)

    changed = skipped = failed = 0

    for spot in spots:
        name = spot["name"]
        kr   = spot.get("kr", "")
        area = spot.get("area", "")
        addr = spot.get("addr", "")

        has_coords = spot.get("lat") is not None and spot.get("lng") is not None
        if has_coords and not force:
            skipped += 1
            continue

        old_coords = (spot.get("lat"), spot.get("lng"))
        result = None

        print(f"  {name}")

        # ── Try Kakao first ──────────────────────────────────────────────────
        if api_key and name not in KAKAO_SKIP:
            result = kakao_lookup(name, kr, area, api_key)

        # ── Fall back to Nominatim ───────────────────────────────────────────
        if result is None:
            if not addr_is_geocodeable(addr):
                print(f"    → skipped (no geocodeable address)")
                skipped += 1
                continue
            query = clean_addr(addr)
            print(f"    nominatim ({repr(query)})")
            result = nominatim_lookup(query)
            time.sleep(1.1)   # Nominatim rate limit: 1 req/sec

        # ── Record result ────────────────────────────────────────────────────
        if result:
            new_lat, new_lng = result
            if old_coords != (new_lat, new_lng):
                print(f"    {old_coords[0]}, {old_coords[1]}  →  {new_lat}, {new_lng}")
                if not dry_run:
                    spot["lat"] = new_lat
                    spot["lng"] = new_lng
                changed += 1
            else:
                print(f"    unchanged ({new_lat}, {new_lng})")
        else:
            print(f"    ✗ not found")
            failed += 1

    print(f"\nDone — {changed} updated, {skipped} skipped, {failed} not found")

    if not dry_run and changed > 0:
        with open("spots.json", "w", encoding="utf-8") as f:
            json.dump(spots, f, ensure_ascii=False, indent=2)
        print("spots.json written.")

if __name__ == "__main__":
    main()
