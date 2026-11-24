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

## Also needed (added after review)
- **Per chart notes.** Which README assumptions to repeat under each chart:
  Market Size: 1, 2, 3, 6 (estimates, boxed retail only, ends 2018, units not revenue).
  Who's Winning and Publisher Playbooks: 2, 9 (digital heavy publishers undercounted; publisher grouping).
  Franchise Fatigue: 11 (title based franchise detection is approximate); follow ups start from proven demand.
  Platforms & Calendar: 5, 8 (per platform counting; dated games only for months).
  Regional Taste: 2, 10 (retail only; genre grouping).
  Critics & Sales: 12 (critic subset is mostly larger releases).
  Pitch a Game and Predict the Sales: 13, 14, and descriptive, not causal.
  Game Database: 4 (merged from two scrapes; the 2016 rows stop at 2016 sales).
- **Color check.** The Microsoft green (#1b7a4b) is new and wasn't in the Box Office Lab's validated set. Check it
  against the other publisher colors for color vision deficiency.
- **Deploy.** Streamlit Cloud: point it at `app.py`; set `APP_PASSWORD` in Secrets if the class should log in.
  `data/` ships in the repo, so the Hugging Face download in the Box Office Lab isn't needed (02 has no HF code).
- **Clean up.** Delete `wip/` once `app.py` is assembled and runs; update the README's file list if anything changes.
