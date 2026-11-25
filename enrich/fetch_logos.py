"""Download console-maker and publisher logos from Wikimedia Commons into data/logos.json.

Run locally:  python enrich/fetch_logos.py

Only files Commons marks "Public domain" are used (simple text logos, below the threshold of originality). They are
still trademarks of their owners and appear only to identify the companies. Each logo is stored as a small PNG
data URI, so the app needs no outside requests to show it.
"""
import base64
import json
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "data" / "logos.json"
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "GameSalesLab/1.0 (classroom research dataset; python-requests)"}

# name in the app -> Commons file (license checked on download)
FILES = {
    # Platform families
    "PlayStation": "PlayStation logo and wordmark.svg",
    "Nintendo": "Nintendo red logo.svg",
    "Xbox": "Xbox logo (2019).svg",
    "PC": "Windows logo and wordmark - 2021.svg",
    "Sega": "SEGA logo.svg",
    "Steam": "Steam logo.svg",
    # Publisher groups (Nintendo and Sega reuse the logos above)
    "Electronic Arts": "Electronic Arts 2020.svg",
    "Activision": "Activision.svg",
    "Sony": "Sony logo.svg",
    "Ubisoft": "Ubisoft logo.svg",
    "Take-Two": "Take-Two Interactive Logo.svg",
    "Microsoft": "Microsoft logo (2012).svg",
}


def main():
    out = {}
    for name, file in FILES.items():
        for attempt in range(6):          # Commons rate-limits bursts: wait and retry
            resp = requests.get(API, headers=UA, timeout=60, params={
                "action": "query", "titles": f"File:{file}", "prop": "imageinfo", "format": "json",
                "iiprop": "url|extmetadata", "iiurlheight": 80, "iiextmetadatafilter": "LicenseShortName"})
            if resp.ok and resp.text.startswith("{"):
                break
            time.sleep(10 * (attempt + 1))
        r = resp.json()
        page = next(iter(r["query"]["pages"].values()))
        info = page["imageinfo"][0]
        lic = info["extmetadata"]["LicenseShortName"]["value"]
        if "public domain" not in lic.lower():
            print(f"skip {name}: {lic}")
            continue
        png = requests.get(info["thumburl"], headers=UA, timeout=60).content
        out[name] = {"src": "data:image/png;base64," + base64.b64encode(png).decode(), "file": file,
                     "page": info["descriptionurl"], "license": lic}
        print(f"{name:16s} {len(png):6,} bytes  {file}")
        time.sleep(4)
    OUT.write_text(json.dumps(out), encoding="utf-8")
    print(f"{len(out)} logos -> {OUT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
