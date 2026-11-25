"""Build the app's extra data layers from the raw downloads.

Run locally after the collectors (igdb_fetch, wiki_hits, famitsu_fetch, steamspy_fetch, steam_details):
    python enrich/build_extended.py

Writes, in data/:
  attributes.json  one row per title in games.json: IGDB cover, ESRB rating, game modes, camera perspective,
                   player rating (matched by igdb_fetch.py: exact title, then platform and year)
  hits.json        officially reported sales of hit games (Wikipedia's best-seller lists), worldwide, digital included
  japan.json       Famitsu lifetime physical sales in Japan, games released 2019 onward
  steam.json       Steam (PC) estimates: SteamSpy owner range and review counts, games released 2018 onward

The four layers measure different things and are never added together (see README, Sources).
"""
import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "enrich"))
from gamelab_common import PLATFORMS, PUB_ORDER, norm, pub_group  # noqa: E402
import igdb_fetch  # noqa: E402

RAW, OUT = HERE / "raw", HERE / "data"
REVIEW_LOW, REVIEW_HIGH = 30, 60       # copies per Steam review (the common "Boxleiter" rule of thumb)

# IGDB genres -> the app's eight genres (first match in this order wins; the rest are Other)
GENRE_RULES = [("Shooter", "Shooter"), ("Sport", "Sports"), ("Racing", "Racing"), ("Role-playing", "Role-Playing"),
               ("Platform", "Platform"), ("Simulator", "Simulation"), ("Adventure", "Action"),
               ("Hack and slash", "Action"), ("Fighting", "Other"), ("Music", "Misc"), ("Quiz", "Misc"),
               ("Card & Board", "Misc")]
MULTI_MODES = ("Multiplayer", "Co-operative", "Split screen", "Massively Multiplayer", "Battle Royale")
FAMILY = {k: v[1] for k, v in PLATFORMS.items()} | {"NS2": "Nintendo", "Multi": "All platforms"}
PLATFORM_NAME = {k: v[0] for k, v in PLATFORMS.items()} | {"NS2": "Switch 2", "Multi": "All platforms"}


def app_genre(igdb_genres):
    g = str(igdb_genres or "")
    return next((ours for key, ours in GENRE_RULES if key.lower() in g.lower()), "Other" if g else None)


def esrb_one(s):
    """IGDB can list several ESRB ratings (re-releases): keep the strictest."""
    order = ["EC", "E", "E10+", "T", "M", "AO", "RP"]
    vals = [x.strip() for x in str(s or "").split(";") if x.strip() in order]
    return max(vals, key=order.index) if vals else None


def perspective(s):
    s = str(s or "")
    for p in ["First person", "Third person", "Side view", "Bird view / Isometric", "Virtual Reality", "Text"]:
        if p in s:
            return p
    return None


def load_igdb():
    with gzip.open(igdb_fetch.FULL, "rt", encoding="utf-8") as f:
        games = json.load(f)
    d = pd.DataFrame([igdb_fetch.flatten(g) for g in games if g.get("name")])
    d["key"] = d["igdb_name"].map(norm)
    return d


class Lookup:
    """Find the IGDB game for a (title, year) pair: same normalized title, closest release year (within 2), the
    main game before ports and remakes. Titles like 'Pokemon Scarlet / Violet' are also tried as their first part."""

    def __init__(self, igdb):
        self.by_key = {k: g for k, g in igdb.groupby("key")}

    def find(self, title, year=None):
        keys = [norm(title)]
        first = re.split(r"\s+(?:/|and|&)\s+", str(title))[0]
        if first != title:
            keys.append(norm(first))
        for k in keys:
            g = self.by_key.get(k)
            if g is None:
                continue
            gap = (g["igdb_year"] - year).abs().fillna(9) if year is not None and not pd.isna(year) else 0 * g["igdb_id"]
            score = gap + g["is_port_or_version"] * 0.5 + g["game_type"].ne("Main Game") * 0.3
            best = g.loc[score.idxmin()]
            if year is not None and not pd.isna(year) and gap[score.idxmin()] > 2:
                continue
            return best
        return None


def igdb_cols(m):
    if m is None:
        return {"igdb_id": None, "cover_id": None, "genre": None, "esrb": None, "multiplayer": None}
    return {"igdb_id": int(m["igdb_id"]), "cover_id": m["cover_id"], "genre": app_genre(m["igdb_genres"]),
            "esrb": esrb_one(m["esrb"]), "multiplayer": int(any(x in str(m["game_modes"]) for x in MULTI_MODES))}


def attributes():
    m = pd.read_csv(RAW / "igdb_matched.csv")
    m = m[m["igdb_id"].notna()].copy()
    out = pd.DataFrame({
        "title": m["title"], "igdb_id": m["igdb_id"].astype(int), "cover_id": m["cover_id"],
        "esrb": m["esrb"].map(esrb_one),
        "multiplayer": m["game_modes"].fillna("").map(lambda s: int(any(x in s for x in MULTI_MODES))),
        "online_mmo": m["game_modes"].fillna("").str.contains("Massively").astype(int),
        "perspective": m["perspectives"].map(perspective),
        "user_rating": m["user_rating"].round(1), "user_rating_count": m["user_rating_count"],
        "igdb_url": m["igdb_url"]})
    out.loc[m["game_modes"].isna().to_numpy(), "multiplayer"] = np.nan   # unknown, not single-player
    return out


def hits(look):
    w = pd.read_csv(RAW / "wiki_hits.csv")
    rows = []
    for r in w.itertuples():
        ig = igdb_cols(look.find(r.title, r.release_year))
        first_pub = re.split(r";|/|,", str(r.publisher))[0].strip()
        pg = pub_group(first_pub)
        rows.append({"title": r.title, "platform": r.platform, "platform_name": PLATFORM_NAME.get(r.platform),
                     "family": FAMILY.get(r.platform, "Other"), "units_m": r.units_m, "as_of": r.as_of,
                     "release_year": r.release_year, "publisher": r.publisher,
                     "pub_group": pg if pg in PUB_ORDER else "Other", "pub": pg, "developer": r.developer,
                     "source_link": r.source_link, **ig})
    return pd.DataFrame(rows)


def japan(look):
    j = pd.read_csv(RAW / "famitsu_lifetime.csv")
    j = j[j["release_year"] >= 2019]
    rows = []
    for r in j.itertuples():
        ig = igdb_cols(look.find(r.title, r.release_year))
        pg = pub_group(r.publisher)
        rows.append({"title": r.title, "platform": r.platform, "platform_name": PLATFORM_NAME.get(r.platform, r.platform),
                     "family": FAMILY.get(r.platform, "Other"), "units_m": r.lifetime_units / 1e6,
                     "release_year": int(r.release_year), "publisher": r.publisher,
                     "pub_group": pg if pg in PUB_ORDER else "Other", "pub": pg, "weeks_charted": r.weeks_charted,
                     "as_of": r.as_of, **ig})
    return pd.DataFrame(rows)


def steam(look, igdb):
    top = pd.read_csv(RAW / "steamspy_all.csv")
    det = pd.read_csv(RAW / "steam_details.csv") if (RAW / "steam_details.csv").exists() else pd.DataFrame()
    rows = {}
    for r in det.itertuples() if len(det) else []:
        rows[int(r.appid)] = {"appid": int(r.appid), "title": r.name or r.igdb_name, "release_year": r.year,
                              "igdb_id": int(r.igdb_id), "owners_low": r.owners_low, "owners_high": r.owners_high,
                              "reviews": r.reviews, "positive": r.positive, "price": r.price,
                              "developer": r.developer, "publisher": r.publisher}
    for r in top.itertuples():
        if int(r.appid) in rows:
            continue
        m = look.find(r.name)
        rows[int(r.appid)] = {"appid": int(r.appid), "title": r.name,
                              "release_year": m["igdb_year"] if m is not None else None,
                              "igdb_id": int(m["igdb_id"]) if m is not None else None,
                              "owners_low": r.owners_low, "owners_high": r.owners_high,
                              "reviews": (r.positive or 0) + (r.negative or 0), "positive": r.positive,
                              "price": r.price, "developer": r.developer, "publisher": r.publisher}
    s = pd.DataFrame(rows.values())
    s = s[s["release_year"].fillna(0) >= 2018].copy()
    by_id = igdb.drop_duplicates("igdb_id").set_index("igdb_id", drop=False)
    ig = [igdb_cols(by_id.loc[i] if pd.notna(i) and i in by_id.index else None) for i in s["igdb_id"]]
    s = pd.concat([s.reset_index(drop=True), pd.DataFrame(ig).drop(columns="igdb_id")], axis=1)
    s["est_low_m"] = s["reviews"] * REVIEW_LOW / 1e6
    s["est_high_m"] = s["reviews"] * REVIEW_HIGH / 1e6
    s["owners_mid_m"] = (s["owners_low"] + s["owners_high"]) / 2 / 1e6
    s["positive_share"] = s["positive"] / s["reviews"].replace(0, np.nan)
    s["price_usd"] = pd.to_numeric(s["price"], errors="coerce") / 100
    pg = s["publisher"].fillna("").map(lambda p: pub_group(re.split(r",", p)[0].strip()) if p else "")
    s["pub_group"] = pg.where(pg.isin(PUB_ORDER), "Other")
    s["release_year"] = s["release_year"].astype(int)
    return s.drop(columns=["price", "positive"])


def write(name, d):
    d = d.replace({np.nan: None})
    (OUT / name).write_text(json.dumps(d.to_dict("records")), encoding="utf-8")
    print(f"{name:16s} {len(d):6,} rows")


def main():
    igdb = load_igdb()
    look = Lookup(igdb)
    write("attributes.json", attributes())
    h = hits(look)
    write("hits.json", h)
    jp = japan(look)
    write("japan.json", jp)
    st_ = steam(look, igdb)
    write("steam.json", st_)
    for n, d in [("hits", h), ("japan", jp), ("steam", st_)]:
        print(f"  {n}: IGDB match {d['igdb_id'].notna().mean():.0%}, cover {d['cover_id'].notna().mean():.0%}")


if __name__ == "__main__":
    main()
