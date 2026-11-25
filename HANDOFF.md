# Handoff: where the Game Sales Lab stands (2026-11-25, evening)

## Redesign and data beyond 2018 (2026-11-25)
- Consulting-style design: navy/blue/gray palette (CVD-checked), serif headings, numbered exhibits with takeaway
  titles, a Source/Note line under every exhibit, KPI cards with a plain-language line under each number, every data
  point labeled, an insight under every table, company logos as row labels and in keys, IGDB cover art.
- 13 sections. New: 7 Critics & Players (adds player ratings, ESRB, multiplayer), 8 Blockbusters Since 2019
  (publisher-reported hits, incl. a 2001–2026 by-year exhibit), 9 Japan Since 2019 (Famitsu), 10 PC & Steam.
- Steam layer: steam_details.py looks up 8,000 more games at SteamSpy's 1/second limit; rerun build_extended.py
  when it finishes, then push.


## Done and pushed
- `raw/`, `build_data.py`, `data/`: merged VGChartz data (19,113 game-platform rows), model scores, pitch grid.
- `app.py`: all 10 sections (Market Size, Who's Winning, Franchise Fatigue | Publisher Playbooks, Platforms & Calendar,
  Regional Taste, Critics & Sales | Pitch a Game, Predict the Sales, Game Database), header, pinned section bar with
  "In class" / "Go deeper" / "Build your pitch" groups, sidebar menu and glossary, password gate.
- Per-chart notes: every chart is followed by the README assumptions listed for its section (`NOTE` in app.py).
- Color check: the first Microsoft green (#1b7a4b) was nearly identical to Nintendo's magenta under deuteranopia
  (CIEDE2000 3.3). Replaced with #0f6e5e, which lowers no pair's separation under protan, deutan or tritan simulation.
- Franchise Fatigue ratios skip series whose first title sold under 100K in the data (75 of 840, usually a PC
  original VGChartz barely counted, e.g. Call of Duty 2003 at 10K), which would otherwise make every ratio explode.
- Tested: headless run of every section, widget changes, Vega-Lite schema validation on every chart, password gate,
  `streamlit run` health check.
- `wip/` removed; `requirements.txt` added; README has deploy notes.

## Deployed
- Live at https://game-sales-lab.streamlit.app (Streamlit Community Cloud, branch `main`, `app.py`), 2026-11-25.
  The deploy form defaults to branch `master` and `streamlit_app.py`; both must be changed for this repo.

## Data access
- No downloads in the app (2026-11-25): the CSV button is removed and the tables' "Download as CSV" toolbar
  button is hidden with CSS. The data itself is still public in this GitHub repo.

## Year labels follow the data
- `app.py` sets `YEAR_MIN`/`YEAR_MAX` from `data/games.json` after loading, so every year in titles, captions, metrics
  and sliders updates when the data grows. `MODEL_FROM` (2000) must match `build_data.py`, which now has `END_YEAR` and
  `MODEL_FROM` constants at the top.
- Final pass once new data is in (2019+ or IGDB variables): re-read every insight and caption. Keep VGChartz-based
  shares (top-5 share, regional and family shares) ending at the last VGChartz year; official publisher numbers for
  2019+ are hits only and include digital, so they can't extend those charts without changing what they measure.

## Still to do
- Next: 2018–2025 extension. Candidate sources are listed in the README (*Sources*). Nintendo IR shows only the top
  10 per platform; Capcom's site blocks automated downloads (save the page by hand); Kaggle needs an API token.
- Optional: set `APP_PASSWORD` in the app's Settings > Secrets if the class should log in (currently open).
- Not load-tested with a full class yet (the Box Office Lab's caching patterns are all in place).
