"""Download game attributes from IGDB (igdb.com, owned by Twitch) and match them to the games in data/games.json.

Run locally:  python enrich/igdb_fetch.py
Needs a free Twitch developer app (https://dev.twitch.tv/console/apps) with its Client ID and Client Secret saved in
~/.igdb/credentials.json as {"client_id": "...", "client_secret": "..."}. The file lives outside the repo and is
never printed or committed.

Steps
1. Get an app access token from Twitch (client-credentials flow).
2. Page through every IGDB game (500 per request, under IGDB's 4 requests/second limit) and keep the fields below.
   The full download is cached in raw/igdb_full.json.gz (git-ignored) so reruns skip it; pass --refresh to redo it.
3. Match each title in data/games.json to an IGDB game: same normalized title, then the closest first-release
   year, preferring a game released on the same platform. Unmatched titles stay unmatched (no fuzzy guessing).
4. Write raw/igdb_matched.csv (one row per title in our data) and print the match rate.
"""
import argparse
import gzip
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent.parent
CRED = Path.home() / ".igdb" / "credentials.json"
FULL = HERE / "raw" / "igdb_full.json.gz"
OUT = HERE / "raw" / "igdb_matched.csv"
API = "https://api.igdb.com/v4"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

FIELDS = ",".join([
    "name", "first_release_date", "game_type.type", "parent_game", "version_parent",
    "genres.name", "themes.name", "game_modes.name", "player_perspectives.name", "keywords.name",
    "franchises.name", "collections.name",
    "platforms.abbreviation", "platforms.name",
    "involved_companies.company.name", "involved_companies.developer", "involved_companies.publisher",
    "age_ratings.organization.name", "age_ratings.rating_category.rating",
    "rating", "rating_count", "aggregated_rating", "aggregated_rating_count", "total_rating", "total_rating_count",
    "hypes", "url", "cover.image_id",
])

# Our platform codes (VGChartz) -> IGDB platform abbreviations
PLATFORM_MAP = {"PS": "PS1", "PS2": "PS2", "PS3": "PS3", "PS4": "PS4", "PSP": "PSP", "PSV": "Vita", "XB": "XBOX",
                "X360": "X360", "XOne": "XONE", "Wii": "Wii", "WiiU": "WiiU", "NS": "Switch", "DS": "NDS",
                "3DS": "3DS", "GBA": "GBA", "GB": "Game Boy", "GBC": "GBC", "GC": "NGC", "N64": "N64",
                "SNES": "SNES", "NES": "NES", "PC": "PC", "GEN": "Genesis/MegaDrive", "SAT": "Saturn", "DC": "DC",
                "2600": "Atari2600"}


def norm(title):
    """Lowercase, accents and punctuation removed, '&' -> 'and', single spaces."""
    t = unicodedata.normalize("NFKD", str(title)).encode("ascii", "ignore").decode().lower()
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def token():
    if not CRED.exists():
        sys.exit(f"Missing {CRED}. See the docstring at the top of this file.")
    c = json.loads(CRED.read_text(encoding="utf-8"))
    r = requests.post("https://id.twitch.tv/oauth2/token", timeout=30,
                      params={"client_id": c["client_id"], "client_secret": c["client_secret"],
                              "grant_type": "client_credentials"})
    r.raise_for_status()
    return c["client_id"], r.json()["access_token"]


def download_all():
    cid, tok = token()
    headers = {"Client-ID": cid, "Authorization": f"Bearer {tok}"}
    # Resume from a partial download if one exists (saved every 20 pages)
    part = FULL.with_suffix(".partial.gz")
    rows = []
    if part.exists():
        with gzip.open(part, "rt", encoding="utf-8") as f:
            rows = json.load(f)
    last_id = rows[-1]["id"] if rows else 0
    pages = 0
    while True:
        body = f"fields {FIELDS}; where id > {last_id}; sort id asc; limit 500;"
        for attempt in range(5):
            r = requests.post(f"{API}/games", headers=headers, data=body, timeout=60)
            if r.status_code == 429:          # rate limited: back off
                time.sleep(1 + attempt)
                continue
            r.raise_for_status()
            break
        page = r.json()
        if not page:
            break
        rows.extend(page)
        last_id = page[-1]["id"]
        pages += 1
        if pages % 20 == 0:
            print(f"{len(rows):,} IGDB games", flush=True)
            with gzip.open(part, "wt", encoding="utf-8") as f:
                json.dump(rows, f)
        time.sleep(0.3)                       # stay under 4 requests/second
    with gzip.open(FULL, "wt", encoding="utf-8") as f:
        json.dump(rows, f)
    part.unlink(missing_ok=True)
    return rows


def names(lst, key="name"):
    return "; ".join(sorted({x.get(key) for x in (lst or []) if isinstance(x, dict) and x.get(key)}))


def flatten(g):
    comps = g.get("involved_companies") or []
    esrb = [a.get("rating_category", {}).get("rating") for a in g.get("age_ratings") or []
            if isinstance(a, dict) and (a.get("organization") or {}).get("name") == "ESRB"]
    ts = g.get("first_release_date")
    return {
        "igdb_id": g["id"], "igdb_name": g.get("name"), "igdb_url": g.get("url"),
        "igdb_year": (EPOCH + timedelta(seconds=ts)).year if ts else None,   # works before 1970 too (Windows)
        "game_type": (g.get("game_type") or {}).get("type"),
        "is_port_or_version": int(bool(g.get("parent_game") or g.get("version_parent"))),
        "igdb_genres": names(g.get("genres")), "themes": names(g.get("themes")),
        "game_modes": names(g.get("game_modes")), "perspectives": names(g.get("player_perspectives")),
        "keywords": names(g.get("keywords")),
        "franchises": names(g.get("franchises")), "collection": names(g.get("collections")),
        "igdb_platforms": names(g.get("platforms"), "abbreviation"),
        "developers": "; ".join(sorted({(c.get("company") or {}).get("name") for c in comps
                                        if c.get("developer") and (c.get("company") or {}).get("name")})),
        "publishers": "; ".join(sorted({(c.get("company") or {}).get("name") for c in comps
                                        if c.get("publisher") and (c.get("company") or {}).get("name")})),
        "esrb": "; ".join(sorted({e for e in esrb if e})),
        "user_rating": g.get("rating"), "user_rating_count": g.get("rating_count"),
        "critic_rating": g.get("aggregated_rating"), "critic_rating_count": g.get("aggregated_rating_count"),
        "hypes": g.get("hypes"),
        "cover_id": (g.get("cover") or {}).get("image_id"),
    }


def match(igdb):
    games = pd.DataFrame(json.loads((HERE / "data" / "games.json").read_text(encoding="utf-8")))
    titles = games.groupby("title").agg(year=("year", "min"), platforms=("platform", lambda x: set(x))).reset_index()
    titles["key"] = titles["title"].map(norm)
    cand = pd.DataFrame([flatten(g) for g in igdb if g.get("name")])
    cand["key"] = cand["igdb_name"].map(norm)
    by_key = {k: d for k, d in cand.groupby("key")}
    out = []
    for t in titles.itertuples():
        d = by_key.get(t.key)
        if d is None:
            out.append({"title": t.title})
            continue
        want = {PLATFORM_MAP.get(p) for p in t.platforms} - {None}
        on_platform = d["igdb_platforms"].map(lambda s: bool(want & set(s.split("; "))))
        gap = (d["igdb_year"] - t.year).abs().fillna(99)
        # Same platform first, then closest year, then the main game over ports and bundles
        score = (~on_platform) * 10 + gap + d["is_port_or_version"] * 0.5
        best = d.loc[score.idxmin()]
        if gap[score.idxmin()] > 3:        # same name but a different game (e.g. a remake decades later)
            out.append({"title": t.title})
            continue
        out.append({"title": t.title, **best.drop("key").to_dict(), "same_platform": bool(on_platform[score.idxmin()])})
    res = pd.DataFrame(out)
    res.to_csv(OUT, index=False)
    hit = res["igdb_id"].notna()
    units = games.groupby("title")["total_sales"].sum()
    print(f"Matched {hit.sum():,} of {len(res):,} titles ({hit.mean():.0%}); "
          f"{units[res.loc[hit, 'title']].sum() / units.sum():.0%} of units. Wrote {OUT.relative_to(HERE)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download IGDB instead of using the cache")
    a = ap.parse_args()
    if FULL.exists() and not a.refresh:
        with gzip.open(FULL, "rt", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = download_all()
    match(data)
