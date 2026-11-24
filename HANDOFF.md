# Handoff: where the Game Sales Lab stands (2026-11-24)

## Done and pushed
- `raw/`: both VGChartz files (2024 scrape and the clean 2016 scrape).
- `build_data.py` and its output in `data/`: 19,113 game-platform rows, 9.6B units, 1980 to 2018.
  Model scores (cross validated R², log units, 2000 to 2018): greenlight features 0.30 linear / 0.35 random forest;
  plus critic score 0.41 / 0.47 (4,253 games). Pitch grid: 8,640 precomputed combinations.
- `README.md`: files, data notes, full assumptions and limits.
- `.streamlit/config.toml`: same theme as the Box Office Lab.

## Not done: app.py
`wip/` holds the pieces, in order. Build `app.py` by concatenating them, then appending the sections below:
1. `01_docstring.py`
2. `02_imports_from_box_office_lab.py` (imports, HERE/DATA, Altair validation skip)
3. `03_design_system_nav_definitions.py` (page config, colors, publisher/family/region palettes, NAV, DEFINE_RULES)
4. `04_define_metric_css_from_box_office_lab.py` (define(), hover help on metrics, CSS). Change "the middle film" to
   "the middle game" in define().
5. `05_table_chart_cache_section_helpers_from_box_office_lab.py` (show_table, shared chart cache, house style,
   section(), exhibit(), takeaway())

Still to write (same patterns as `aphd87/box-office-lab-app/app.py`):
- Password gate (APP_PASSWORD), data load from `data/games.json`, `models.json`, `pitch.json` (cache_resource).
- Header: kicker, title, lede, 4 metrics (units tracked, million seller rate, top 5 publisher share, units explained by
  the data), an info box with the key qualifiers from the README (estimates, boxed retail only, ends 2018, units not
  revenue, descriptive not causal), Problem / Solution columns, pinned section bar.
- Sections, each chart followed by a caption with its qualifiers:
  1. Market Size: units by year by region; platform family share by year.
  2. Who's Winning: publisher share of units by year (pick publishers); top 5 share over time; publisher table.
  3. Franchise Fatigue: units by entry number vs. the first entry (series with 3+ titles); follow up vs. original
     medians and hit rates; pick a series to see its entries.
  4. Publisher Playbooks: publisher x genre share heatmap; platform family mix; head to head table.
  5. Platforms & Calendar: software units by years since platform launch; units by release month, holiday share.
  6. Regional Taste: genre share by region heatmap; top games in a picked region.
  7. Critics & Sales: median units and hit rate by critic score band (note the 4,600 game subset).
  8. Pitch a Game: genre, platform, publisher, follow up, critic score -> predicted units, likely range, chance of a
     million seller (from `pitch.json`), plus comparable games.
  9. Predict the Sales: R² by model and feature set; feature importance.
  10. Game Database: search and filters, table, CSV download.
- Sidebar menu and glossary; "Go deeper" and "Build your pitch" dividers.
- Then run `streamlit run app.py` headless, check every section, and add `requirements.txt`
  (streamlit, pandas, numpy, altair).
