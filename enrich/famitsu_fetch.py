"""Collect Famitsu's weekly Japan sales charts, as republished by Gematsu, into lifetime totals per game.

Run locally:  python enrich/famitsu_fetch.py      -> raw/famitsu_weekly.csv, raw/famitsu_lifetime.csv

Famitsu (Kadokawa) estimates physical (boxed) game sales in Japan each week. Gematsu (gematsu.com) posts each week's
chart as "Famitsu Sales: <dates>", listing for each title: platform, publisher, release date, that week's units and
the lifetime total so far. The posts are read through Gematsu's public WordPress API, 100 posts per request, with
the 10-second delay its robots.txt asks for. Raw posts are cached in raw/famitsu_posts.json (git-ignored).

What the numbers are: Japan only, physical copies only (no downloads), estimates by Famitsu. A game's lifetime total
is the largest one seen in any week's chart; games that drop off the chart early stop updating there.
"""
import difflib
import html
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent.parent
CACHE = HERE / "raw" / "famitsu_posts.json"
API = "https://www.gematsu.com/wp-json/wp/v2/posts"
UA = {"User-Agent": "GameSalesLab/1.0 (classroom research dataset; python-requests)"}


def download():
    posts, page = [], 1
    while True:
        r = requests.get(API, headers=UA, timeout=120, params={
            "search": "Famitsu Sales", "per_page": 100, "page": page, "_fields": "id,date,title,link,content"})
        if r.status_code == 400:           # past the last page
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        posts.extend(batch)
        print(f"page {page}: {len(posts)} posts", flush=True)
        if page >= int(r.headers.get("X-WP-TotalPages", page)):
            break
        page += 1
        time.sleep(10)                     # robots.txt crawl-delay
    CACHE.write_text(json.dumps(posts), encoding="utf-8")
    return posts


# One chart entry looks like:
#  [NSW] Mario Kart World (Nintendo, 06/05/25) – 12,345 (2,345,678)
LINE = re.compile(r"\[(?P<plat>[A-Za-z0-9]+)\]\s*(?P<title>[^\[\]]+?)\s*\((?P<pub>[^()]*?),\s*(?P<rel>\d{2}/\d{2}/\d{2,4})\)"
                  r"\s*[–—-]\s*(?P<week>[\d,]+)(?:\s*\((?P<life>[\d,]+)\))?")


def parse(posts):
    rows = []
    for p in posts:
        title = html.unescape(p["title"]["rendered"])
        if not title.lower().startswith("famitsu sales"):
            continue
        # Each entry is split across HTML tags, so match on the whole post as one line of text
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", p["content"]["rendered"])).split())
        for m in LINE.finditer(text):
            life = m.group("life") or m.group("week")      # a debut week's lifetime = its weekly units
            rows.append({"post_date": p["date"][:10], "chart": title, "platform": m.group("plat"),
                         "title": m.group("title").strip(), "publisher": m.group("pub").strip(),
                         "release": m.group("rel"), "week_units": int(m.group("week").replace(",", "")),
                         "lifetime_units": int(life.replace(",", "")), "source_link": p["link"]})
    return pd.DataFrame(rows)


PLATFORM = {"NSW": "NS", "SW2": "NS2", "NS2": "NS2", "PS4": "PS4", "PS5": "PS5", "XSX": "XS", "XBS": "XS",
            "PSV": "PSV", "3DS": "3DS", "NDS": "DS", "PSVR2": "PS5"}


def norm(t):
    t = t.lower().replace("pokémon", "pokemon").replace("pokeon", "pokemon")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def merge_spellings(w):
    """Same platform + same release date + similar title (difflib ratio >= 0.6, or one title inside the other) =
    the same game written differently in different weeks. Each game gets its most common spelling."""
    w["game_id"] = -1
    gid = 0
    for _, g in w.groupby(["platform", "release"]):
        reps = []                                   # (normalized title, id) of games seen in this group
        for i, t in zip(g.index, g["title"].map(norm)):
            hit = next((k for r, k in reps if r == t or r in t or t in r
                        or difflib.SequenceMatcher(None, r, t).ratio() >= 0.6), None)
            if hit is None:
                hit = gid
                reps.append((t, gid))
                gid += 1
            w.at[i, "game_id"] = hit
    w["title"] = w.groupby("game_id")["title"].transform(lambda s: s.mode().iat[0])
    return w


def clean_lifetime(g):
    """Drop lifetime totals that are typos (a missing or extra digit, e.g. '5,6815,162'). A lifetime total changes
    slowly, so each one is compared with the median of the charted weeks around it (up to 3 before and 3 after):
    more than 1.5x or less than 2/3 of that median is a typo. Early launch weeks can also fail this test; that is
    harmless because only the latest good total is kept."""
    g = g.sort_values("post_date")
    life = g["lifetime_units"].to_numpy(dtype=float)
    ok = []
    for i in range(len(life)):
        around = [life[j] for j in range(max(0, i - 3), min(len(life), i + 4)) if j != i]
        if not around:
            ok.append(True)
            continue
        mid = sorted(around)[len(around) // 2]
        ok.append(mid * 2 / 3 <= life[i] <= mid * 1.5)
    return g[ok]


def main():
    posts = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else download()
    w = parse(posts)
    w["platform"] = w["platform"].map(lambda p: PLATFORM.get(p, p))
    # '11/18/22' and '11/18/2022' are the same date
    rel = pd.to_datetime(w["release"], format="%m/%d/%y", errors="coerce").fillna(
        pd.to_datetime(w["release"], format="%m/%d/%Y", errors="coerce"))
    w["release"] = rel.dt.strftime("%Y-%m-%d").fillna(w["release"])
    w = merge_spellings(w)
    n_raw = len(w)
    w = pd.concat([clean_lifetime(g) for _, g in w.groupby("game_id")])
    print(f"Dropped {n_raw - len(w):,} weekly totals that look like typos")
    w.to_csv(HERE / "raw" / "famitsu_weekly.csv", index=False)
    w["release_dt"] = pd.to_datetime(w["release"], format="%Y-%m-%d", errors="coerce")
    last = w.sort_values(["lifetime_units", "post_date"]).groupby("game_id").tail(1)
    life = last.assign(release_year=last["release_dt"].dt.year,
                       weeks_charted=last["game_id"].map(w.groupby("game_id").size()))
    life = life[["title", "platform", "publisher", "release", "release_year", "lifetime_units", "post_date",
                 "weeks_charted", "source_link"]].rename(columns={"post_date": "as_of"})
    # A stray week with a different release date splits a game in two: keep the entry charted most often
    life = (life.assign(key=life["title"].map(norm)).sort_values("weeks_charted")
            .groupby(["platform", "key"]).tail(1).drop(columns="key"))
    life.sort_values("lifetime_units", ascending=False).to_csv(HERE / "raw" / "famitsu_lifetime.csv", index=False)
    print(f"{len(posts)} posts, {len(w):,} chart lines, {len(life):,} games "
          f"({w['post_date'].min()} to {w['post_date'].max()})")


if __name__ == "__main__":
    main()
