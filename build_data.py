"""Build data/ for the Game Sales Lab from the two VGChartz files in raw/. Run locally: python build_data.py

Sources (both scraped from vgchartz.com, unit sales in millions, mostly physical retail):
  raw/vgchartz-2024.csv  64,016 game-platform rows, release dates, critic scores, developers. Sales are filled for
                         ~19,000 rows. VGChartz stopped publishing Nintendo first-party estimates, so this file is
                         missing Wii Sports, Mario Kart, Pokemon and most other Nintendo titles.
  raw/vgsales-2016.csv   16,598 rows (the well-known Kaggle scrape), release year only, sales through 2016,
                         Nintendo included.
Merge rule: one row per game + platform. Where the 2024 file has sales, its numbers win (later updates). Where only
the 2016 file has sales, they fill in, keeping the 2024 file's date, critic score and developer when it has the game.

Writes data/games.json, data/models.json, data/pitch.json. Needs pandas, numpy, scikit-learn.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold, cross_val_score

HERE = Path(__file__).resolve().parent
RAW, OUT = HERE / "raw", HERE / "data"
OUT.mkdir(exist_ok=True)

from gamelab_common import (HIT_UNITS, MAIN_GENRES, GENRE_MAP, PLATFORMS, PUB_ORDER,  # noqa: F401
                             norm, pub_group, series_of)



# --- Load and merge ----------------------------------------------------------------------------------------------
# The app reads its year labels from the data, so changing these two needs no app edits (keep app.py MODEL_FROM in step)
END_YEAR = 2018     # last release year kept (VGChartz stopped tracking software after 2018)
MODEL_FROM = 2000   # models and pitch grid use releases MODEL_FROM..END_YEAR

new = pd.read_csv(RAW / "vgchartz-2024.csv", dtype={"console": str})
new = new.rename(columns={"console": "platform", "pal_sales": "eu_sales"})
new["release"] = pd.to_datetime(new["release_date"], errors="coerce")
new["year"] = new["release"].dt.year
new["key"] = new["title"].map(norm) + "|" + new["platform"]
# Ties are broken by title and platform (stable sort) so a rebuild gives the same rows in the same order anywhere
new = new.sort_values(["total_sales", "title", "platform"], ascending=[False, True, True], kind="mergesort")
new = new.drop_duplicates("key")

old = pd.read_csv(RAW / "vgsales-2016.csv", dtype={"Platform": str}).rename(columns={
    "Name": "title", "Platform": "platform", "Year": "year", "Genre": "genre", "Publisher": "publisher",
    "NA_Sales": "na_sales", "EU_Sales": "eu_sales", "JP_Sales": "jp_sales", "Other_Sales": "other_sales",
    "Global_Sales": "total_sales"})
old["key"] = old["title"].map(norm) + "|" + old["platform"]
old = old.sort_values(["total_sales", "title", "platform"], ascending=[False, True, True], kind="mergesort")
old = old.drop_duplicates("key")

SALES = ["na_sales", "eu_sales", "jp_sales", "other_sales", "total_sales"]
n_has = new[new["total_sales"].notna()].copy()
n_has["source"] = "VGChartz 2024"
n_no = new[new["total_sales"].isna()].set_index("key")
fill = old[~old["key"].isin(n_has["key"])].copy()
fill["source"] = "VGChartz 2016"
# Keep the 2024 file's date, critic score and developer when it lists the game without sales
for c in ["release", "critic_score", "developer"]:
    fill[c] = fill["key"].map(n_no[c]) if c in n_no else np.nan
fill["year"] = fill["release"].dt.year.fillna(fill["year"])
g = pd.concat([n_has, fill], ignore_index=True)
g = g[g["total_sales"] > 0].copy()
for c in SALES[:-1]:
    g[c] = g[c].fillna(0.0)

g["year"] = pd.to_numeric(g["year"], errors="coerce")
g = g[g["year"].between(1977, END_YEAR)].copy()   # 2019+ has only a few dozen titles: VGChartz stopped tracking
g["year"] = g["year"].astype(int)
g["month"] = g["release"].dt.month
g["platform"] = g["platform"].where(g["platform"].isin(PLATFORMS), "Other")
g["platform_name"] = g["platform"].map(lambda p: PLATFORMS.get(p, ("Other",))[0])
g["family"] = g["platform"].map(lambda p: PLATFORMS.get(p, ("", "Other"))[1])
g["generation"] = g["platform"].map(lambda p: PLATFORMS.get(p, ("", "", 0))[2])
g["handheld"] = g["platform"].map(lambda p: PLATFORMS.get(p, ("", "", 0, 0))[3])
g["genre_raw"] = g["genre"]
g["genre"] = g["genre"].replace(GENRE_MAP)
g["genre"] = g["genre"].where(g["genre"].isin(MAIN_GENRES), "Other")
g["pub"] = g["publisher"].map(pub_group)
g["pub_group"] = g["pub"].where(g["pub"].isin(PUB_ORDER), "Other")
g["critic_score"] = pd.to_numeric(g["critic_score"], errors="coerce")

# --- Franchises: a game is a follow-up if an earlier title in its series came out first ---------------------------
g["series"] = g["title"].map(series_of)
first = g.groupby(["series", "title"])["year"].min().reset_index()
first["entry"] = first.groupby("series")["year"].rank(method="dense").astype(int)
n_titles = first.groupby("series")["title"].nunique()
first["series_titles"] = first["series"].map(n_titles)
g = g.merge(first[["series", "title", "entry", "series_titles"]], on=["series", "title"], how="left")
g["follow_up"] = (g["entry"] > 1).astype(int)
g.loc[g["series_titles"] < 2, "series"] = None   # one-title "series" are just games
g["hit"] = (g["total_sales"] >= HIT_UNITS).astype(int)
g = g.sort_values(["total_sales", "title", "platform"], ascending=[False, True, True], kind="mergesort")
g = g.reset_index(drop=True)
g["id"] = np.arange(len(g))

keep = ["id", "title", "platform", "platform_name", "family", "generation", "handheld", "year", "month", "genre",
        "genre_raw", "publisher", "pub", "pub_group", "developer", "critic_score", "na_sales", "eu_sales",
        "jp_sales", "other_sales", "total_sales", "series", "entry", "follow_up", "hit", "source"]
out = g[keep].copy()
out["release"] = g["release"].dt.strftime("%Y-%m-%d")
(OUT / "games.json").write_text(out.to_json(orient="records"), encoding="utf-8")
print(f"games: {len(out):,} rows, {out['total_sales'].sum():,.0f}M units, "
      f"{(out['source'] == 'VGChartz 2016').sum():,} filled from the 2016 file")

# --- Models: what predicts a game's lifetime units? ---------------------------------------------------------------
# Unit = game on one platform, 2000-2018 releases on the main platforms. Outcome = log units (sales are very skewed),
# reported back in units. Two feature sets: what a publisher knows at greenlight, and the same plus critic score.
m = g[(g["year"].between(MODEL_FROM, END_YEAR)) & (g["platform"] != "Other")].copy()
m["log_units"] = np.log(m["total_sales"])
m["season"] = m["month"].map(lambda x: np.nan if pd.isna(x) else ("Holiday" if x >= 10 else "Other"))
BASE = ["genre", "platform", "pub_group", "follow_up", "year"]


def design(d, feats):
    X = pd.get_dummies(d[feats], columns=[c for c in ["genre", "platform", "pub_group"] if c in feats],
                       dtype=float)
    return X


models = {}
kf = KFold(5, shuffle=True, random_state=0)
for name, feats, d in [("Greenlight", BASE, m), ("Greenlight + critic score", BASE + ["critic_score"],
                                                    m[m["critic_score"].notna()])]:
    X, y = design(d, feats), d["log_units"]
    lin = cross_val_score(LinearRegression(), X, y, cv=kf, scoring="r2")
    rf_model = RandomForestRegressor(300, min_samples_leaf=5, n_jobs=-1, random_state=0)
    rf = cross_val_score(rf_model, X, y, cv=kf, scoring="r2")
    rf_model.fit(X, y)
    pi = permutation_importance(rf_model, X.sample(min(3000, len(X)), random_state=0),
                                y.loc[X.sample(min(3000, len(X)), random_state=0).index], n_repeats=4,
                                random_state=0, n_jobs=-1)
    imp = pd.Series(pi.importances_mean, index=X.columns)
    grouped = {}
    for col, v in imp.items():
        base = next((f for f in feats if col == f or col.startswith(f + "_")), col)
        grouped[base] = grouped.get(base, 0) + float(v)
    models[name] = {"n": int(len(d)), "cv": {"Linear regression": lin.tolist(), "Random forest": rf.tolist()},
                    "importance": grouped}
    print(name, len(d), "lin", lin.mean().round(3), "rf", rf.mean().round(3))
    if name == "Greenlight":
        base_rf, base_X, base_d = rf_model, X, d
    else:
        crit_rf, crit_X, crit_d = rf_model, X, d
(OUT / "models.json").write_text(json.dumps(models), encoding="utf-8")

# --- Pitch grid: every combination a student can pick, predicted once here -----------------------------------------
# Out-of-fold residuals give the likely range and the chance of a million-seller around each prediction.
def oof_resid(d, X):
    r = pd.Series(index=d.index, dtype=float)
    for tr, te in kf.split(X):
        f = RandomForestRegressor(200, min_samples_leaf=5, n_jobs=-1, random_state=0).fit(X.iloc[tr], d["log_units"].iloc[tr])
        r.iloc[te] = d["log_units"].iloc[te] - f.predict(X.iloc[te])
    return r


res_base = oof_resid(base_d, base_X)
res_crit = oof_resid(crit_d, crit_X)
plats = [p for p in ["PS4", "XOne", "NS", "PC", "3DS", "PS3", "X360", "Wii", "WiiU", "PSV", "DS", "PS2"]
         if p in set(m["platform"])]
CRITIC = [None, 6, 7, 8, 9]   # VGChartz critic score, 0-10
rows = []
for gen in MAIN_GENRES:
    for p in plats:
        for pub in PUB_ORDER + ["Other"]:
            for fu in [0, 1]:
                for cs in CRITIC:
                    rows.append({"genre": gen, "platform": p, "pub_group": pub, "follow_up": fu, "year": END_YEAR,
                                 "critic_score": cs})
grid = pd.DataFrame(rows)
pitch = []
for cs_on, rf_model, Xcols, res in [(False, base_rf, base_X.columns, res_base), (True, crit_rf, crit_X.columns, res_crit)]:
    gsub = grid[grid["critic_score"].notna()] if cs_on else grid[grid["critic_score"].isna()]
    feats = BASE + (["critic_score"] if cs_on else [])
    Xg = design(gsub, feats).reindex(columns=Xcols, fill_value=0.0)
    pred = rf_model.predict(Xg)
    q = res.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).values
    for (_, r), p in zip(gsub.iterrows(), pred):
        pitch.append({"genre": r["genre"], "platform": r["platform"], "pub_group": r["pub_group"],
                      "follow_up": int(r["follow_up"]), "critic_score": None if not cs_on else int(r["critic_score"]),
                      "median": float(np.exp(p + q[2])), "p25": float(np.exp(p + q[1])), "p75": float(np.exp(p + q[3])),
                      "p10": float(np.exp(p + q[0])), "p90": float(np.exp(p + q[4])),
                      "p_hit": float((p + res >= np.log(HIT_UNITS)).mean())})
(OUT / "pitch.json").write_text(json.dumps({"platforms": plats, "rows": pitch}), encoding="utf-8")
print("pitch rows", len(pitch))
