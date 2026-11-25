"""Steam (PC) estimates for games released 2018 and later, beyond SteamSpy's top list.

Run locally after igdb_fetch.py:  python enrich/steam_details.py      -> raw/steam_details.csv

1. IGDB's links from each game to its Steam store ID (IGDB "external games", source 1 = Steam).
2. Pick games released 2018 or later with some following on IGDB (rated or followed by players), at most
   MAX_GAMES of them, most-rated first.
3. Look each one up with SteamSpy's per-game request (one per second, its stated limit): owner range plus
   positive and negative review counts. Results are appended to raw/steam_details.jsonl as they arrive, so an
   interrupted run resumes where it stopped.

What the numbers are: estimates. SteamSpy's owner range is wide (e.g. 1-2 million). A second, common estimate is
copies = reviews x 30 to 60 (the "Boxleiter" rule of thumb used by PC developers); both are kept.
"""
import gzip
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import igdb_fetch  # noqa: E402  (token() and paths)

HERE = Path(__file__).resolve().parent.parent
LINKS = HERE / "raw" / "igdb_steam_links.csv"
JSONL = HERE / "raw" / "steam_details.jsonl"
OUT = HERE / "raw" / "steam_details.csv"
UA = {"User-Agent": "GameSalesLab/1.0 (classroom research dataset; python-requests)"}
MAX_GAMES = 8000
FROM_YEAR = 2018


def steam_links():
    if LINKS.exists():
        return pd.read_csv(LINKS, dtype={"uid": str})
    cid, tok = igdb_fetch.token()
    h = {"Client-ID": cid, "Authorization": f"Bearer {tok}"}
    rows, last = [], 0
    while True:
        body = f"fields game,uid; where external_game_source = 1 & id > {last}; sort id asc; limit 500;"
        r = requests.post(f"{igdb_fetch.API}/external_games", headers=h, data=body, timeout=60)
        if r.status_code == 429:
            time.sleep(2)
            continue
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        rows.extend(page)
        last = page[-1]["id"]
        time.sleep(0.3)
    d = pd.DataFrame(rows)[["game", "uid"]].dropna()
    d.to_csv(LINKS, index=False)
    print(f"{len(d):,} IGDB-Steam links")
    return d


def pick(links):
    with gzip.open(igdb_fetch.FULL, "rt", encoding="utf-8") as f:
        games = json.load(f)
    rows = []
    for g in games:
        ts = g.get("first_release_date")
        year = (igdb_fetch.EPOCH + timedelta(seconds=ts)).year if ts else None
        if year is None or year < FROM_YEAR:
            continue
        follow = (g.get("total_rating_count") or 0) + (g.get("hypes") or 0)
        if follow <= 0:
            continue
        rows.append({"igdb_id": g["id"], "name": g.get("name"), "year": year, "follow": follow})
    d = pd.DataFrame(rows).merge(links.rename(columns={"game": "igdb_id", "uid": "appid"}), on="igdb_id")
    d = d[d["appid"].str.fullmatch(r"\d+")].drop_duplicates("igdb_id")
    return d.sort_values("follow", ascending=False).head(MAX_GAMES)


def main():
    todo = pick(steam_links())
    done = set()
    if JSONL.exists():
        done = {json.loads(line)["igdb_id"] for line in JSONL.read_text(encoding="utf-8").splitlines() if line}
    todo = todo[~todo["igdb_id"].isin(done)]
    print(f"{len(done):,} done, {len(todo):,} to fetch (~{len(todo) * 1.1 / 3600:.1f} h)", flush=True)
    with JSONL.open("a", encoding="utf-8") as out:
        for i, r in enumerate(todo.itertuples(), 1):
            try:
                s = requests.get("https://steamspy.com/api.php", headers=UA, timeout=60,
                                 params={"request": "appdetails", "appid": r.appid}).json()
            except Exception:
                time.sleep(10)
                continue
            out.write(json.dumps({"igdb_id": r.igdb_id, "appid": r.appid, "igdb_name": r.name, "year": r.year,
                                  "name": s.get("name"), "owners": s.get("owners"), "positive": s.get("positive"),
                                  "negative": s.get("negative"), "price": s.get("price"),
                                  "developer": s.get("developer"), "publisher": s.get("publisher")}) + "\n")
            if i % 200 == 0:
                out.flush()
                print(f"{i:,} / {len(todo):,}", flush=True)
            time.sleep(1.05)               # SteamSpy: one request per second
    d = pd.read_json(JSONL, lines=True)
    lo_hi = d["owners"].fillna("").str.replace(",", "").str.extract(r"(\d+)\s*\.\.\s*(\d+)").astype(float)
    d["owners_low"], d["owners_high"] = lo_hi[0], lo_hi[1]
    d["reviews"] = d["positive"].fillna(0) + d["negative"].fillna(0)
    d.to_csv(OUT, index=False)
    print(f"{len(d):,} games -> {OUT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
