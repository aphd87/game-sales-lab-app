"""Find cover art for games the exact-title match missed, using IGDB's search (which also checks each game's
alternative and Japanese titles).

Run locally after build_extended.py:  python enrich/cover_search.py   then rerun build_extended.py

Searches every game shown in the app without a cover: all of data/hits.json and data/japan.json, and the
MAX_GAMES best-selling VGChartz titles. A search result is accepted only if its first release year is within 1 year
of ours (2 if the names are also similar), so a cover is never taken from a different game with a similar name.
Results are cached in raw/cover_search.json, so reruns only search new titles.
"""
import difflib
import json
import re
import sys
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "enrich"))
from gamelab_common import norm  # noqa: E402
import igdb_fetch  # noqa: E402

CACHE = HERE / "raw" / "cover_search.json"
MAX_GAMES = 3000


def candidates():
    d = HERE / "data"
    rows = []
    for name in ["hits", "japan"]:
        t = pd.DataFrame(json.loads((d / f"{name}.json").read_text(encoding="utf-8")))
        t = t[t["cover_id"].isna()]
        rows += [(r.title, r.release_year) for r in t.itertuples()]
    g = pd.DataFrame(json.loads((d / "games.json").read_text(encoding="utf-8")))
    a = pd.DataFrame(json.loads((d / "attributes.json").read_text(encoding="utf-8")))
    have = set(a.loc[a["cover_id"].notna(), "title"])
    top = (g.groupby("title").agg(units=("total_sales", "sum"), year=("year", "min")).reset_index()
           .sort_values("units", ascending=False).head(MAX_GAMES))
    rows += [(r.title, r.year) for r in top.itertuples() if r.title not in have]
    return list(dict.fromkeys((str(t), None if pd.isna(y) else int(y)) for t, y in rows))


def accept(title, year, results):
    for r in results:
        if not (r.get("cover") or {}).get("image_id"):
            continue
        ts = r.get("first_release_date")
        ry = (igdb_fetch.EPOCH + timedelta(seconds=ts)).year if ts else None
        sim = difflib.SequenceMatcher(None, norm(title), norm(r.get("name", ""))).ratio()
        if year is None:
            ok = sim >= 0.9
        elif ry is None:
            ok = sim >= 0.9
        else:
            ok = abs(ry - year) <= 1 or (abs(ry - year) <= 2 and sim >= 0.7)
        if ok:
            return {"igdb_id": r["id"], "igdb_name": r.get("name"), "igdb_year": ry, "cover_id": r["cover"]["image_id"],
                    "similarity": round(sim, 2)}
    return None


def main():
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = [(t, y) for t, y in candidates() if f"{t}|{y}" not in cache]
    print(f"{len(todo):,} titles to search", flush=True)
    cid, tok = igdb_fetch.token()
    h = {"Client-ID": cid, "Authorization": f"Bearer {tok}"}
    for i, (title, year) in enumerate(todo, 1):
        q = re.sub(r'["\\]', " ", title)
        body = f'search "{q}"; fields name,first_release_date,cover.image_id; limit 8;'
        for _ in range(5):
            r = requests.post(f"{igdb_fetch.API}/games", headers=h, data=body.encode("utf-8"), timeout=60)
            if r.status_code != 429:
                break
            time.sleep(2)
        cache[f"{title}|{year}"] = accept(title, year, r.json() if r.ok else [])
        if i % 200 == 0:
            CACHE.write_text(json.dumps(cache), encoding="utf-8")
            print(f"{i:,} / {len(todo):,}", flush=True)
        time.sleep(0.28)                     # IGDB: 4 requests per second
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    found = sum(v is not None for v in cache.values())
    print(f"covers found for {found:,} of {len(cache):,} searched titles")


if __name__ == "__main__":
    main()
