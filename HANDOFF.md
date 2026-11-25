# Handoff: where the Game Sales Lab stands (2026-11-25)

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

## Still to do
- Optional: set `APP_PASSWORD` in the app's Settings > Secrets if the class should log in (currently open).
- Not load-tested with a full class yet (the Box Office Lab's caching patterns are all in place).
