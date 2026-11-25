# Game Sales Lab

Live: https://game-sales-lab.streamlit.app

Classroom dashboard on the video game business, built on VGChartz unit sales. Companion to the Behind the Box Office
Lab (`aphd87/box-office-lab-app`) and built on the same code and design system.

## Files
- `raw/vgchartz-2024.csv`: VGChartz scrape (2024), 64,016 game-platform rows with release dates, critic scores, developers.
- `raw/vgsales-2016.csv`: the 2016 VGChartz scrape (16,598 rows). Fills in Nintendo first-party titles missing from the 2024 file.
- `build_data.py`: merges the two files and writes `data/` (games, model scores, pitch grid). Run locally: `python build_data.py`.
- `data/`: the built data the app reads.
- `app.py`: the Streamlit app. Run locally: `streamlit run app.py`.
- `requirements.txt`: what the deployed app needs (build_data.py also needs scikit-learn; run it locally).

## Deploy
Streamlit Cloud: point a new app at this repo's `app.py`. `data/` ships in the repo, so no data download or token is needed. To make the class log in, set `APP_PASSWORD` under the app's Settings > Secrets
(`APP_PASSWORD = "..."`); without it the app is open. After pushing changes, reboot the app (file watching is off in `.streamlit/config.toml` to save CPU under classroom load).

## Sources

### Data used in the app
| Source | What it provides | Link |
|---|---|---|
| VGChartz | The original publisher of every sales estimate in this app (game-level unit sales by region, release dates, critic scores) | https://www.vgchartz.com |
| Kaggle, "Video Game Sales 2024" (asaniczka) | `raw/vgchartz-2024.csv`: 2024 scrape of VGChartz, 64,016 game-platform rows | https://www.kaggle.com/datasets/asaniczka/video-game-sales-2024 |
| Kaggle, "Video Game Sales" (gregorut, 2016) | `raw/vgsales-2016.csv`: 2016 scrape of VGChartz, 16,598 rows; fills in Nintendo first-party titles | https://www.kaggle.com/datasets/gregorut/videogamesales |

Kaggle only hosts these files; the numbers are VGChartz's estimates (see *Assumptions and limits*). Spot checks
against the original VGChartz pages are the way to verify a figure.

### Code and tools
| Source | Used for | Link |
|---|---|---|
| Behind the Box Office Lab | App structure, design system, shared chart cache | https://github.com/aphd87/box-office-lab-app |
| Streamlit | App framework and hosting (Community Cloud) | https://streamlit.io |
| Vega-Altair | Charts | https://altair-viz.github.io |
| scikit-learn | Prediction models in `build_data.py` | https://scikit-learn.org |

### Candidate sources for 2018–2025 (not yet in the app)
VGChartz stopped publishing most software estimates after 2018. No single free source replaces it; these are the
options reviewed on 2026-11-25, most trustworthy first. They measure different things (shipped vs. sold, physical
vs. digital, worldwide vs. one country), so they should be kept as separate layers, never added together.

| Source | Coverage | Trust | Cost | Link |
|---|---|---|---|---|
| Nintendo IR, Top Selling Title Sales Units | Top 10 Nintendo titles per platform (Switch, Switch 2, Wii U, 3DS), worldwide life-to-date, digital included, quarterly | Official | Free | https://www.nintendo.co.jp/ir/en/finance/software/index.html |
| Capcom IR, Platinum Titles | Every Capcom title over 1M units (~125), digital included, quarterly | Official | Free | https://www.capcom.co.jp/ir/english/finance/million.html |
| Bandai Namco fact books | Franchise-level cumulative units | Official | Free (PDF) | https://www.bandainamco.co.jp/en/ir/library/assets/pdf/2024/factbook2024_en.pdf |
| Other publisher IR (Sega, Square Enix, Sony, Take-Two, Koei Tecmo) | Occasional headline titles only | Official, patchy | Free | Each company's investor relations site |
| Famitsu weekly charts (Japan), republished by Gematsu | Top 30 physical titles per week with lifetime totals | Industry tracking estimate | Free to read | https://www.gematsu.com (weekly "Famitsu Sales" posts, e.g. https://www.gematsu.com/2026/11/famitsu-sales-10-26-26-11-1-26) |
| SteamSpy | Estimated owner ranges for Steam (PC) games | Rough estimate; weak for small games | Free | https://steamspy.com |
| Gamalytic / VG Insights | Steam sales estimates | Estimate (vendor reports ~77% of games within 30%) | Paid | https://gamalytic.com, https://vginsights.com (acquired by Sensor Tower, 2025) |
| Circana (formerly NPD) | US physical + digital sales, the industry standard (some publishers no longer share digital) | Best for the US | Paid license | https://www.circana.com/industries/video-games |
| Kaggle, "Video Game Sales Data from VGChartz.com" (patkle, Feb 2023) | Later VGChartz scrape with a "shipped" column; post-2018 coverage not yet checked | Same as VGChartz | Free | https://www.kaggle.com/datasets/patkle/video-game-sales-data-from-vgchartzcom |

## Data notes
Units are lifetime sales in millions, as estimated by VGChartz: mostly boxed retail, so digital sales are largely
missing and years after about 2015 are undercounted. Coverage stops in 2018.

## Assumptions and limits
Read these before drawing conclusions from the dashboard. Every number describes what has gone together with
bigger sales in the past; none of it proves that a choice causes higher sales.

**Source**
1. **Estimates, not reported sales.** VGChartz builds its figures from retail sampling and modeling, not from
   publisher reports. Treat every number as an estimate; individual games can be off by a wide margin.
2. **Boxed retail, mostly.** Digital sales (PlayStation Store, Xbox Store, eShop, Steam) are largely missing. Recent
   years, PC games and digital heavy publishers are undercounted, and part of the decline in units after about 2010
   reflects the shift to digital, not a shrinking market.
3. **Coverage ends in 2018.** VGChartz stopped publishing most software estimates after 2018; the few dozen 2019+
   titles are dropped.

**How the two files are combined**
4. **Merge rule.** One row per game per platform, matched on title (lowercased, punctuation removed) and platform.
   Where the 2024 file has sales, its numbers are used. The 2016 file fills in 1,719 games the 2024 file lacks,
   mostly Nintendo's own titles; their sales stop at 2016 levels. Spelling differences between the files can leave a
   small number of duplicates or missed matches.
5. **Unit of analysis.** A game on one platform. A game released on three consoles counts as three games, each with
   its own sales.
6. **Units, not revenue.** There are no prices, so a budget game and a full price game count the same per unit.

**Definitions**
7. **Hit (million seller).** A game version that sold at least 1 million units over its life.
8. **Release date.** From the 2024 file. About 3% of games have a year only and are left out of the month and season
   views.
9. **Publisher groups.** Labels rolled up to their parent as owned during the data's years: EA Sports to Electronic
   Arts, Rockstar and 2K to Take-Two, Blizzard and Vivendi to Activision, Eidos to Square Enix. Acquisitions after
   2018 (for example Microsoft buying Bethesda and Activision) are not applied. The mapping matches name patterns, so a
   few small labels may be grouped imperfectly. Groups outside the main eight are shown as Other.
10. **Genres.** VGChartz's genre labels. Action Adventure counts as Action, Party and Music as Misc, Visual Novel as
    Adventure, MMO as Role Playing. Genres outside the main eight (Adventure, Fighting, Strategy, Puzzle and others)
    are grouped as Other.
11. **Franchises and follow ups.** Detected from titles: the series is the title before a colon, dash or trailing
    number ("Call of Duty: Black Ops" and "FIFA 18" become "call of duty" and "fifa"). A follow up is any title whose
    series had an earlier release. This misses franchises whose entries have different names and can lump unrelated
    games that share a name. Treat franchise results as approximate.
12. **Critic scores.** On a 0 to 10 scale, available for only about 4,600 games, mostly larger releases. Results that
    use critic scores describe that subset, not all games.

**Models (Predict the Sales, Pitch a Game)**
13. Random forest and linear regression on the log of lifetime units, games released 2000 to 2018 on named platforms.
    Scores are cross validated (5 folds): each model is graded on games it did not learn from.
14. Pitch predictions assume a 2018 release and use the spread of the model's past misses for the likely range and the
    chance of a million seller. They describe comparable past games, not a forecast for a new market.
