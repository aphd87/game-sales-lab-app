"""Download SteamSpy's estimates for every Steam game (the PC layer for 2018 onward).

Run locally:  python enrich/steamspy_fetch.py      -> raw/steamspy_all.csv

SteamSpy (https://steamspy.com/api.php) publishes, for each Steam app: an owner range ("1,000,000 .. 2,000,000"),
positive and negative review counts, price, developer and publisher. Its "all" request returns 1,000 apps per page
and allows one request per minute, so a full run takes over an hour; finished pages are cached in raw/steamspy_pages/
(git-ignored) and a rerun skips them.

What the numbers are: estimates, not sales. SteamSpy itself warns that free weekends and giveaways inflate owners,
and estimates for small games (under ~20,000 owners) are unreliable. Use ranges or the midpoint with that caveat.
"""
import json
import time
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent.parent
PAGES = HERE / "raw" / "steamspy_pages"
OUT = HERE / "raw" / "steamspy_all.csv"
UA = {"User-Agent": "GameSalesLab/1.0 (classroom research dataset; python-requests)"}


def main():
    PAGES.mkdir(parents=True, exist_ok=True)
    page = 0
    while True:
        f = PAGES / f"page_{page:03d}.json"
        if not f.exists():
            for attempt in range(5):
                r = requests.get("https://steamspy.com/api.php", params={"request": "all", "page": page},
                                 headers=UA, timeout=120)
                if r.ok and r.text.strip().startswith("{"):
                    break
                time.sleep(70)
            data = r.json()
            f.write_text(json.dumps(data), encoding="utf-8")
            print(f"page {page}: {len(data)} apps", flush=True)
            if not data:
                break
            time.sleep(61)                 # SteamSpy allows one "all" request per minute
        else:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not data:
                break
        page += 1
    rows = []
    for f in sorted(PAGES.glob("page_*.json")):
        rows.extend(json.loads(f.read_text(encoding="utf-8")).values())
    d = pd.DataFrame(rows)
    lo_hi = d["owners"].str.replace(",", "").str.extract(r"(\d+)\s*\.\.\s*(\d+)").astype(float)
    d["owners_low"], d["owners_high"] = lo_hi[0], lo_hi[1]
    d = d.drop_duplicates("appid")
    d.to_csv(OUT, index=False)
    print(f"{len(d):,} apps -> {OUT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
