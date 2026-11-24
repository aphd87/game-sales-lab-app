# Game Sales Lab

Classroom dashboard on the video game business, built on VGChartz unit sales. Companion to the Behind the Box Office
Lab (`aphd87/box-office-lab-app`) and built on the same code and design system.

## Files
- `raw/vgchartz-2024.csv`: VGChartz scrape (2024), 64,016 game-platform rows with release dates, critic scores, developers.
- `raw/vgsales-2016.csv`: the 2016 VGChartz scrape (16,598 rows). Fills in Nintendo first-party titles missing from the 2024 file.
- `build_data.py`: merges the two files and writes `data/` (games, model scores, pitch grid). Run locally: `python build_data.py`.
- `data/`: the built data the app reads.
- `app.py`: the Streamlit app. Run locally: `streamlit run app.py`.

## Data notes
Units are lifetime sales in millions, as estimated by VGChartz: mostly boxed retail, so digital sales are largely
missing and years after about 2015 are undercounted. Coverage stops in 2018.
