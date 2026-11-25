"""Collect official sales figures for hit games from Wikipedia's "best-selling games" lists.

Run locally:  python enrich/wiki_hits.py      -> raw/wiki_hits.csv

Why Wikipedia: after 2018 there is no free, complete sales source. These lists gather the publisher-reported figures
(annual reports, investor relations pages, press releases) for each platform in one place, each with a citation.
Each row keeps the page and its exact revision (a permanent link), so every number can be traced to its citation.

What the numbers are: lifetime copies sold or shipped worldwide, digital included, "as of" the date given. Mostly
games above about 1 million copies, so this describes hits, not the whole market. Not comparable to the VGChartz
estimates (retail only) in data/games.json; keep the two in separate charts.
"""
import io
import re
import time
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "raw" / "wiki_hits.csv"
API = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "GameSalesLab/1.0 (classroom research dataset; python-requests)"}

# Wikipedia page -> platform code used in this project ("Multi" = all platforms combined)
PAGES = {
    "List of best-selling Nintendo Switch video games": "NS",
    "List of best-selling Nintendo Switch 2 games": "NS2",
    "List of best-selling PlayStation 4 video games": "PS4",
    "List of best-selling PlayStation 5 video games": "PS5",
    "List of best-selling Xbox One video games": "XOne",
    "List of best-selling PC games": "PC",
    "List of best-selling Nintendo 3DS video games": "3DS",
    "List of best-selling Wii U video games": "WiiU",
    "List of best-selling PlayStation 3 video games": "PS3",
    "List of best-selling Xbox 360 video games": "X360",
    "List of best-selling video games": "Multi",
}


def fetch(title):
    for attempt in range(6):
        r = requests.get(API, headers=UA, timeout=60, params={
            "action": "parse", "page": title, "prop": "text|revid", "format": "json", "formatversion": 2})
        if r.ok and r.text.startswith("{"):
            return r.json()["parse"]
        time.sleep(5 * (attempt + 1))      # rate limited: wait and retry
    r.raise_for_status()
    raise RuntimeError(f"Could not fetch {title}")


def clean(s):
    """Drop footnote markers like [a] or [12] and extra spaces."""
    return re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", "", str(s))).strip()


def copies(s):
    """'71.53 million' -> 71.53; '8,000,000' -> 8.0; '1 million+' -> 1.0 (in millions). None if no number."""
    s = clean(s).lower()
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", s)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    if "billion" in s:
        return v * 1000
    if "million" in s or v < 1000:     # bare small numbers in these tables are millions
        return v
    return v / 1e6


def year_of(s):
    m = re.search(r"(19[7-9]\d|20[0-3]\d)", clean(s))
    return int(m.group(1)) if m else None


def pick(cols, *names):
    for c in cols:
        if any(n in str(c).lower() for n in names):
            return c
    return None


def main():
    rows = []
    for title, platform in PAGES.items():
        p = fetch(title)
        tabs = pd.read_html(io.StringIO(p["text"]))
        main = next(t for t in tabs if len(t) >= 10 and pick(t.columns, "copies sold", "sales (millions)"))
        c = main.columns
        name, sold = pick(c, "title", "game"), pick(c, "copies sold", "sales (millions)")
        asof, rel = pick(c, "as of"), pick(c, "release")
        dev, pub, plat = pick(c, "developer"), pick(c, "publisher"), pick(c, "platform")
        link = f"https://en.wikipedia.org/w/index.php?title={title.replace(' ', '_')}&oldid={p['revid']}"
        for _, r in main.iterrows():
            units = copies(r[sold])
            if units is None:
                continue
            rows.append({
                "title": clean(r[name]), "platform": platform, "units_m": units,
                "units_text": clean(r[sold]), "lower_bound": int("+" in str(r[sold]) or "over" in str(r[sold]).lower()),
                "as_of": clean(r[asof]) if asof is not None else None,
                "release_year": year_of(r[rel]) if rel is not None else (year_of(r[pick(c, "release year")])
                                                                          if pick(c, "release year") else None),
                "platforms_listed": clean(r[plat]) if plat is not None else None,
                "developer": clean(r[dev]) if dev is not None else None,
                "publisher": clean(r[pub]) if pub is not None else None,
                "source_page": title, "source_link": link,
            })
        print(f"{platform:6s} {len(main):4d} rows  {title}")
        time.sleep(2)                     # be polite to Wikipedia
    d = pd.DataFrame(rows)
    d.to_csv(OUT, index=False)
    print(f"\n{len(d):,} rows -> {OUT.relative_to(HERE)}; released 2019 or later: "
          f"{(d['release_year'] >= 2019).sum():,}")


if __name__ == "__main__":
    main()
