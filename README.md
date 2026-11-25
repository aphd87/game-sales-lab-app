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
