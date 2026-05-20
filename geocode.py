#!/usr/bin/env python3
"""
Geocode all spots in spots.json via Nominatim (OpenStreetMap).

Usage:
    python geocode.py            # geocode spots missing coords or flagged
    python geocode.py --force    # re-geocode every spot with a real address
    python geocode.py --dry-run  # print what would change, don't write

Nominatim rate limit: 1 request/second (enforced automatically).

How to add a new spot:
    1. Add the entry to spots.json with lat/lng omitted (or set to null).
    2. Run:  python geocode.py
    3. Commit the updated spots.json.
"""

import json, time, sys, urllib.request, urllib.parse, re

NOMINATIM = "https://nominatim.openstreetmap.org/search"
HEADERS   = {"User-Agent": "seoul-trip-guide/1.0 (personal travel map)"}

SKIP_PATTERNS = re.compile(
    r"unverified|verify via|confirm via|multiple locations|tour pickup|"
    r"check @|near \w+ station|instagram|pickup from|seongsu-dong$|"
    r"hannamdong$|itaewon$|cheongdam-dong$|apgujeong$|hongdae flagship$|"
    r"dosan park area$|haus dosan|ikseon-dong|samcheongdong, jongno|"
    r"sinsa \+ seongsu|hanganjin station|hapjeong main branch",
    re.IGNORECASE,
)

def is_geocodeable(addr: str) -> bool:
    if not addr:
        return False
    if SKIP_PATTERNS.search(addr):
        return False
    # Must have a number (street/lot number)
    if not re.search(r'\d', addr):
        return False
    # And some Korean address component (road or dong)
    has_road = bool(re.search(r'-ro\b|-gil\b|-ga\b|-daero\b|Namsangongwon', addr, re.I))
    has_dong = bool(re.search(r'-dong\b', addr, re.I))
    return has_road or has_dong

def clean_for_geocoding(addr: str) -> str:
    addr = re.sub(r'\s*\([^)]*\)', '', addr)                      # remove (anything)
    addr = re.sub(r'\bB\d+\b', '', addr, flags=re.I)              # B1, B2 basement
    addr = re.sub(r'\b\d+F\b', '', addr, flags=re.I)              # 1F, 2F, 4F
    addr = re.sub(r'\b\d+th floor\b', '', addr, flags=re.I)       # 4th floor
    addr = re.sub(r'\b[A-Z][a-z]+ (Building|Bldg)\b', '', addr)  # Areumnuri Building
    addr = re.sub(r'\s*\+.*$', '', addr)                           # + Seongsu original
    addr = re.sub(r'/\d+[-\d]*', '', addr)                         # 33/44-8 → 33
    addr = re.sub(r'\barea\b', '', addr, flags=re.I)               # "65-1 Dokseodang-ro area"
    addr = re.sub(r',\s*,', ',', addr)                             # collapse double commas
    addr = addr.strip().strip(',').strip()
    return f"{addr}, Seoul, South Korea"

def nominatim_lookup(query: str) -> tuple[float, float] | None:
    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1})
    url    = f"{NOMINATIM}?{params}"
    req    = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read())
        if results:
            return round(float(results[0]["lat"]), 5), round(float(results[0]["lon"]), 5)
    except Exception as e:
        print(f"    ⚠  request failed: {e}")
    return None

def main():
    force   = "--force"   in sys.argv
    dry_run = "--dry-run" in sys.argv

    with open("spots.json", encoding="utf-8") as f:
        spots = json.load(f)

    changed = 0
    skipped = 0
    failed  = 0

    for spot in spots:
        name = spot["name"]
        addr = spot.get("addr", "")

        if not is_geocodeable(addr):
            skipped += 1
            continue

        has_coords = spot.get("lat") is not None and spot.get("lng") is not None
        if has_coords and not force:
            skipped += 1
            continue

        query      = clean_for_geocoding(addr)
        old_coords = (spot.get("lat"), spot.get("lng"))

        print(f"  Geocoding: {name}")
        print(f"    query: {query}")

        result = nominatim_lookup(query)
        time.sleep(1.1)  # respect Nominatim's 1 req/sec limit

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
