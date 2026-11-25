"""Game Sales Lab: classroom dashboard on the video game business. Companion to the Behind the Box Office Lab and
built on the same code: one long page, a shared chart cache (every chart is built once per distinct set of inputs and
shared by all sessions, see show_chart) and plain-language definitions on every number.

Data (all precomputed into data/, so a click only filters small tables; nothing is fitted while students use the app):
  games.json       VGChartz unit-sales estimates, 1977-2018 (build_data.py)
  models.json, pitch.json   prediction-model scores and the pitch grid (build_data.py)
  attributes.json  IGDB cover art, age rating, game modes and player ratings for those games (enrich/)
  hits.json        officially reported sales of hit games, all years, mostly 2013 onward (enrich/, Wikipedia lists)
  japan.json       Famitsu lifetime physical sales in Japan, games released 2019 onward (enrich/)
  steam.json       Steam (PC) estimates, games released 2018 onward (enrich/, SteamSpy + IGDB)
  logos.json       public-domain console-maker and publisher logos (enrich/fetch_logos.py)
APP_PASSWORD, if set as a secret or environment variable, gates the app; locally there is no password.
"""
import base64
import hashlib
import hmac
import html
import inspect
import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"


# --- Classroom load: skip Altair's schema check ----------------------------------------------------------------
# Altair re-validates every chart against the full Vega-Lite JSON schema each time it is drawn, for every student,
# which was the biggest single CPU cost in a 65-student load test. These charts are fixed code, already validated
# while building the app, so draw them without the check. Guarded so reruns don't stack wrappers.
def _skip_altair_validation():
    for cls in (alt.Chart, alt.TopLevelMixin):
        if "to_dict" in cls.__dict__ and not getattr(cls.to_dict, "_no_validate", False):
            orig = cls.to_dict

            def to_dict(self, validate=False, *args, _orig=orig, **kw):
                return _orig(self, validate, *args, **kw)
            to_dict._no_validate = True
            cls.to_dict = to_dict


_skip_altair_validation()

st.set_page_config(page_title="Game Sales Lab", page_icon="🎮", layout="wide", initial_sidebar_state="collapsed")

# --- Design system ---------------------------------------------------------------------------------------------
# One controlled palette, used the same way everywhere: navy carries the story, one bright blue highlights, grays
# hold everything else. Eight category colors, checked for color-vision deficiency (protan, deutan and tritan
# simulation, Machado 2009: every pair stays at CIEDE2000 >= 10, 2026-11-25). A company keeps its color in every
# chart: Nintendo is berry as a console maker and as a publisher, Sony/PlayStation navy, Microsoft/Xbox blue.
NAVY, BLUE, TEAL, SKY, AMBER, BERRY, SLATE, SILVER = ("#0B1F33", "#2251FF", "#14B8A6", "#93C5FD", "#F2A900",
                                                      "#C2185B", "#64748B", "#CBD5E1")
INK, MUTED, LINE, FAINT, OTHER = NAVY, "#5B6573", "#E5E7EB", "#F5F7FA", "#E2E6EC"
FOCUS, COMPARE = BLUE, SILVER          # neutral two-group splits: the group in question vs. the comparison
GOOD, BAD = BLUE, NAVY
RULE = "#9AA3B2"
KEYLINE = "#475569"                    # outline for the lightest marks (Sega silver) so they read on white
SEQ = ["#EEF3FF", BLUE, NAVY]          # magnitude: light blue -> blue -> navy
CAT = [NAVY, BLUE, TEAL, SKY, AMBER, BERRY, SLATE, SILVER]
FONT = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"
SERIF = "'Source Serif 4', Georgia, 'Times New Roman', serif"
GENRE_ORDER = ["Action", "Sports", "Shooter", "Role-Playing", "Platform", "Racing", "Misc", "Simulation"]
GENRE_COLOR = dict(zip(GENRE_ORDER, CAT)) | {"Other": OTHER}
FAMILY_ORDER = ["PlayStation", "Nintendo", "Xbox", "PC", "Sega", "Other"]
FAMILY_COLOR = {"PlayStation": NAVY, "Nintendo": BERRY, "Xbox": BLUE, "PC": AMBER, "Sega": SILVER, "Other": OTHER}
REGIONS = {"na_sales": "North America", "eu_sales": "Europe", "jp_sales": "Japan", "other_sales": "Rest of world"}
REGION_ORDER = list(REGIONS.values())
REGION_COLOR = dict(zip(REGION_ORDER, [NAVY, BLUE, SKY, SILVER]))
PUB_ORDER = ["Nintendo", "Electronic Arts", "Activision", "Sony", "Ubisoft", "Take-Two", "Microsoft", "Sega"]
PUB_COLOR = {"Nintendo": BERRY, "Electronic Arts": AMBER, "Activision": SLATE, "Sony": NAVY, "Ubisoft": TEAL,
             "Take-Two": SKY, "Microsoft": BLUE, "Sega": SILVER}
# Current consoles, when a chart is split by machine rather than by maker
PLATFORM_COLOR = {"NS": BERRY, "NS2": AMBER, "PS4": NAVY, "PS5": BLUE, "XOne": TEAL, "XS": TEAL, "PC": SLATE}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HIT_UNITS = 1.0           # million units = a hit
YEAR_MIN, YEAR_MAX = 1977, 2018   # placeholders; reset from the data right after it loads
MODEL_FROM = 2000                 # build_data.py fits models and the pitch grid on releases MODEL_FROM..YEAR_MAX
COVER = "https://images.igdb.com/igdb/image/upload/t_cover_big/{}.jpg"    # loaded by the viewer's browser


def pub_text(p):
    return KEYLINE if p == "Sega" else PUB_COLOR.get(p, INK)


def pub_expr(field):
    expr = f"'{KEYLINE}'"
    for p in reversed(PUB_ORDER):
        expr = f"datum['{field}'] == '{p}' ? '{pub_text(p)}' : {expr}"
    return alt.ExprRef(expr=expr)


NAV = {"Market Size": "market", "Who's Winning": "winning", "Franchise Fatigue": "fatigue",
       "Publisher Playbooks": "publishers", "Platforms & Calendar": "platforms", "Regional Taste": "regions",
       "Critics & Players": "critics", "Blockbusters Since 2019": "hits", "Japan Since 2019": "japan",
       "PC & Steam": "steam", "Pitch a Game": "pitch", "Predict the Sales": "predict", "Game Database": "database",
       "Econometrics": "econometrics"}
NAV_NUM = {t: str(i) for i, t in enumerate(NAV, start=1)}
NAV_GROUPS = [("In class", 0, 3), ("Go deeper", 3, 7), ("The digital era", 7, 10), ("Build your pitch", 10, 13),
              ("Methods", 13, 14)]

# --- Plain-language definitions (table headers and glossary; first match wins, so specific phrases come first) ----
DEFINE_RULES = [
    ("million-seller", "A game that sold at least 1 million copies on one console over its life."),
    ("hit rate", "Out of every 100 games, how many sold at least 1 million copies."),
    ("chance of a million", "How often games like this one sold at least 1 million copies."),
    ("10th–90th", "From a bad case (only 1 game in 10 did worse) to a great case (only 1 in 10 did better)."),
    ("likely range", "Half of similar past games landed inside this range."),
    ("predicted", "What the model expects a typical game with these choices to sell."),
    ("top-5 share", "Of all copies sold that year, the share sold by the five biggest publishers."),
    ("share of units", "This group's copies as a share of all copies in the comparison."),
    ("units", "Copies sold over the game's life, in millions."),
    ("north america", "Copies sold in the US and Canada (millions)."),
    ("europe", "Copies sold in Europe (millions)."),
    ("japan", "Copies sold in Japan (millions)."),
    ("rest of world", "Copies sold everywhere else (millions)."),
    ("player rating", "Average rating from players on IGDB, 0–100."),
    ("critic", "Average score from professional reviewers, 0–10."),
    ("esrb", "US age rating: E = everyone, E10+ = 10 and up, T = teen (13+), M = mature (17+)."),
    ("follow-up", "A later game in a series that already had an earlier game (a sequel, for example)."),
    ("original", "The first game in its series, or a game that isn't part of a series."),
    ("explained", "How much of the difference in sales between games the model can predict on games it never saw."),
    ("importance", "How much the model's accuracy drops when it can't use this factor. Bigger = relied on more."),
    ("holiday", "Games released October to December."),
    ("owners", "SteamSpy's estimated number of people who own the game on Steam (a wide range)."),
    ("reviews", "Number of player reviews on Steam. A common rule: each review stands for about 30–60 copies."),
    ("games", "Number of game releases (a game on three consoles counts three times)."),
    ("publisher", "The company that funds and sells the game, grouped by parent company at the time "
                  "(e.g. Rockstar and 2K count as Take-Two)."),
    ("platform", "The console or PC the game was released on."),
    ("genre", "Type of game. Genres outside the main eight are grouped as Other."),
    ("year", "Year the game came out."),
]


def define(label):
    low = str(label).lower()
    for key, text in DEFINE_RULES:
        if key in low:
            if low.startswith("median") or low.startswith("typical"):
                text = "The typical game: half sold more, half sold less. " + text
            return text
    return None


st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600;8..60,700&display=swap');
html, body, [class*="st-"], .stMarkdown, .stCaption, button, input, textarea {{ font-family: {FONT}; color: {INK}; }}
h1 {{ font-family: {SERIF} !important; font-weight: 700 !important; letter-spacing: -0.01em; color: {INK};
      line-height: 1.12 !important; }}
h2, h3 {{ font-family: {SERIF} !important; font-weight: 600 !important; color: {INK}; letter-spacing: -0.005em; }}
.kicker {{ text-transform: uppercase; letter-spacing: .12em; font-size: .72rem; font-weight: 700; color: {BLUE};
           margin-bottom: -.3rem; }}
.lede {{ font-size: 1.06rem; color: #334155; max-width: 64rem; }}
.chapter {{ border-top: 3px solid {NAVY}; margin: 3.4rem 0 1.0rem; }}
.exh {{ margin: 2.1rem 0 .5rem; padding-top: .9rem; border-top: 1px solid {LINE}; }}
.exh-no {{ font-size: .7rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: {MUTED}; }}
.exh-title {{ font-family: {SERIF}; font-size: 1.28rem; font-weight: 600; color: {INK}; line-height: 1.3;
              margin: .15rem 0 .15rem; max-width: 60rem; }}
.exh-sub {{ font-size: .86rem; color: {MUTED}; }}
.src {{ font-size: .76rem; color: {MUTED}; margin: .2rem 0 .6rem; line-height: 1.45; max-width: 70rem; }}
.src b {{ color: #334155; font-weight: 600; }}
.kpi {{ background: #fff; border: 1px solid {LINE}; border-top: 3px solid {NAVY}; border-radius: 2px;
        padding: .75rem .9rem .8rem; height: 100%; }}
.kpi-l {{ font-size: .68rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: {MUTED}; }}
.kpi-v {{ font-family: {SERIF}; font-size: 1.65rem; font-weight: 600; color: {INK}; line-height: 1.2;
          margin: .15rem 0 .2rem; }}
.kpi-long {{ font-size: 1.12rem; line-height: 1.3; }}
.kpi-e {{ font-size: .8rem; color: #475569; line-height: 1.4; }}
.kpis {{ display: grid; gap: .7rem; margin: .5rem 0 1rem; }}
.takeaway {{ border-left: 4px solid {NAVY}; background: {FAINT}; padding: .8rem 1.05rem; margin: .5rem 0 1rem;
             color: {INK}; font-size: .95rem; }}
.takeaway b {{ color: {NAVY}; }}
.navbar {{ display: flex; flex-wrap: wrap; gap: .4rem; margin: .6rem 0 1.4rem; padding: .5rem 0;
           background: #fff; border-bottom: 1px solid {LINE}; }}
div[data-testid="stElementContainer"]:has(.navbar), div.element-container:has(.navbar) {{
    position: sticky; top: 3.75rem; z-index: 990; }}
.jump {{ position: relative; }} .jump span {{ position: absolute; top: -11rem; }}
.navbar a {{ text-decoration: none; font-size: .8rem; font-weight: 600; color: {INK}; border: 1px solid {LINE};
             border-radius: 2px; padding: .26rem .7rem; background: #fff; }}
.navbar a:hover {{ border-color: {BLUE}; color: {BLUE}; }}
.navbar a b {{ color: {BLUE}; margin-right: .3rem; }}
.navbar .navsep {{ font-size: .68rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
                   color: {MUTED}; align-self: center; margin: 0 .2rem 0 .7rem; }}
.deeper {{ margin: 3.6rem 0 0; padding: 1rem 1.2rem; background: {NAVY}; color: #fff; }}
.deeper b {{ color: #fff; font-family: {SERIF}; font-size: 1.05rem; }}
.skey {{ display: flex; flex-wrap: wrap; gap: .5rem; margin: .3rem 0 .4rem; }}
.skey-card {{ flex: 1 1 92px; max-width: 140px; text-align: center; padding: .45rem .4rem .4rem;
              border: 1px solid {LINE}; background: #fff; }}
.skey-logo {{ height: 34px; display: flex; align-items: center; justify-content: center; }}
.skey-logo img {{ max-height: 34px; max-width: 100%; object-fit: contain; }}
.skey-swatch {{ height: 4px; margin: .4rem .3rem .3rem; }}
.skey-name {{ font-size: .76rem; font-weight: 650; }}
.covers {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); max-width: 100%; gap: .8rem;
           margin: .4rem 0 .8rem; }}
.cover {{ font-size: .74rem; line-height: 1.3; color: {INK}; }}
.cover img {{ width: 100%; aspect-ratio: 3 / 4; object-fit: cover; border: 1px solid {LINE}; background: {FAINT}; }}
.cover .ph {{ width: 100%; aspect-ratio: 3 / 4; border: 1px solid {LINE}; background: {FAINT}; display: flex;
              align-items: center; justify-content: center; color: {MUTED}; font-size: .7rem; text-align: center;
              padding: .3rem; }}
.cover b {{ display: block; margin-top: .3rem; font-weight: 600; }}
.cover span {{ color: {MUTED}; }}
section[data-testid="stSidebar"] a {{ text-decoration: none; color: {INK}; }}
[data-testid="stIconMaterial"], .material-symbols-rounded, [class*="material-symbols"] {{
    font-family: 'Material Symbols Rounded' !important; }}
[data-testid="stCaptionContainer"] p, .stCaption p {{ color: {MUTED}; }}
/* Info boxes in the palette: light gray with a navy rule, like the takeaways */
[data-testid="stAlert"] > div, [data-testid="stAlertContainer"] {{ background: {FAINT} !important;
    border-left: 4px solid {NAVY} !important; border-radius: 0 !important; color: {INK} !important; }}
[data-testid="stAlert"] p, [data-testid="stAlertContainer"] p {{ color: {INK} !important; }}
[data-testid="stAlertDynamicIcon"], [data-testid="stAlert"] svg {{ display: none !important; }}
/* No data downloads: hide the "Download as CSV" button in every table's hover toolbar */
button[aria-label="Download as CSV"], [data-testid="stElementToolbarButton"]:has(button[aria-label="Download as CSV"]) {{
    display: none !important; }}
</style>""", unsafe_allow_html=True)
# st.dataframe takes width="stretch" from Streamlit 1.46; older versions (e.g. a local 1.45) need use_container_width
_NEW_WIDTH = tuple(int(x) for x in st.__version__.split(".")[:2]) >= (1, 46)


def _stretch(fn):
    return {"width": "stretch"} if _NEW_WIDTH and "width" in inspect.signature(fn).parameters \
        else {"use_container_width": True}


def show_table(df, column_config=None, **kw):
    """st.dataframe with each column header's hover help filled in from define()."""
    cfg = dict(column_config or {})
    cols = df.data.columns if hasattr(df, "data") else df.columns
    for c in cols:
        v = cfg.get(c)
        label = v if isinstance(v, str) else (v or {}).get("label") or str(c)
        text = define(label)
        if not text:
            continue
        if v is None or isinstance(v, str):
            cfg[c] = st.column_config.Column(label, help=text)
        elif not v.get("help"):
            cfg[c] = {**v, "help": text}
    st.dataframe(df, hide_index=True, column_config=cfg or None, **_stretch(st.dataframe), **kw)


def cover_col(label="Cover"):
    return st.column_config.ImageColumn(label, width="small")


def title_tile(title):
    """A navy tile with the game's title, used in tables when no cover art exists (never an empty cell)."""
    words, lines, cur = str(title).split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > 11 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines = (lines + [cur])[:4]
    tspans = "".join(f"<tspan x='45' dy='{0 if i == 0 else 13}'>{html.escape(t[:13])}</tspan>"
                     for i, t in enumerate(lines))
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='90' height='120'><rect width='90' height='120' "
           f"fill='{NAVY}'/><rect x='6' y='6' width='78' height='3' fill='{BLUE}'/><text x='45' "
           f"y='{60 - 6 * (len(lines) - 1)}' fill='white' font-family='Georgia,serif' font-size='11' "
           f"text-anchor='middle'>{tspans}</text></svg>")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()


def with_cover_url(d, col="cover_id"):
    return d.assign(cover=[COVER.format(c).replace("t_cover_big", "t_cover_small") if isinstance(c, str) and c
                           else title_tile(t) for c, t in zip(d[col], d["title"])])


# --- Shared chart cache -------------------------------------------------------------------------------------------
# Building an Altair chart and converting it to Vega-Lite costs ~20-80 ms of server CPU, and a full page draws ~40 of
# them. With 65 students on one shared CPU that queued page loads for over a minute (load test, 2026-11-11). So each
# chart is passed in as a small build() function, and its finished spec is cached server-wide, keyed on everything
# build() can see: the call site plus the values it closes over (DataFrames by content hash). Two students with the
# same selections get the same key and the second one skips the work. Different selections mean a different key, so
# a student can never be shown someone else's chart.
try:  # Streamlit's own Altair -> Vega-Lite step, so cached charts are byte-identical to st.altair_chart
    from streamlit.elements.vega_charts import _convert_altair_to_vega_lite_spec as _altair_to_spec
except Exception:  # renamed in some future Streamlit: fall back to plain st.altair_chart, uncached
    _altair_to_spec = None
CHART_CACHE_MAX = 1500      # specs are small (a few KB to ~100 KB); this caps memory at well under 200 MB


@st.cache_resource(show_spinner=False)
def _chart_store():
    return OrderedDict(), threading.Lock()


def _fingerprint(v):
    """A hashable stand-in for v that changes whenever v's content does."""
    if isinstance(v, (pd.DataFrame, pd.Series)):
        try:
            raw = pd.util.hash_pandas_object(v, index=True).values.tobytes()
        except TypeError:   # unhashable cells (e.g. lists)
            raw = v.to_json(default_handler=str).encode()
        meta = (tuple(map(str, v.columns)), tuple(map(str, v.dtypes))) if isinstance(v, pd.DataFrame) \
            else (str(v.name), str(v.dtype))
        return (type(v).__name__, meta, hashlib.md5(raw).hexdigest())
    if isinstance(v, pd.Index):
        return ("Index", _fingerprint(list(v)))
    if isinstance(v, np.ndarray):
        return ("ndarray", v.dtype.str, v.shape, hashlib.md5(np.ascontiguousarray(v).tobytes()).hexdigest())
    if isinstance(v, (list, tuple, set, frozenset)):
        items = sorted(map(repr, v)) if isinstance(v, (set, frozenset)) else v
        return (type(v).__name__, tuple(_fingerprint(x) for x in items))
    if isinstance(v, dict):
        return ("dict", tuple((repr(k), _fingerprint(x)) for k, x in v.items()))
    if inspect.isfunction(v):
        return _builder_key(v)
    return (type(v).__name__, repr(v))


def _builder_key(fn):
    code = fn.__code__
    return (code.co_filename, code.co_firstlineno, getattr(code, "co_qualname", code.co_name),
            tuple(_fingerprint(c.cell_contents) for c in (fn.__closure__ or ())), _fingerprint(fn.__defaults__))


_EXH = {"sec": "0", "n": 0}     # exhibit numbering: section() resets it, each chart takes the next number


def exhibit_head(title, subtitle=None):
    """Consulting-style exhibit header: number, the takeaway as the title, and what is measured."""
    _EXH["n"] += 1
    sub = f"<div class='exh-sub'>{subtitle}</div>" if subtitle else ""
    st.markdown(f"<div class='exh'><span class='exh-no'>Exhibit {_EXH['sec']}.{_EXH['n']}</span>"
                f"<div class='exh-title'>{title}</div>{sub}</div>", unsafe_allow_html=True)


def show_chart(build, title=None, subtitle=None, panel=True):
    """Every chart: exhibit header above (takeaway title + measure), chart in house style, then the caller adds a
    source line. build is a no-argument function returning the Altair chart (cached across sessions, see above); a
    chart object also works but is drawn uncached. build() must only use values it closes over plus this module's
    constants. panel is kept for call compatibility (all charts now sit on white)."""
    if title or subtitle:
        exhibit_head(title or subtitle, subtitle if title else None)
    is_fn = inspect.isfunction(build)
    key = None
    if is_fn and _altair_to_spec is not None:
        try:
            key = (_builder_key(build), "v2")
        except Exception:
            key = None
    store, lock = _chart_store()
    hit = None
    if key is not None:
        with lock:
            hit = store.get(key)
            if hit is not None:
                store.move_to_end(key)
    if hit is None:
        chart = _house_style(build() if is_fn else build)
        if key is None:
            st.altair_chart(chart, theme=None, **_stretch(st.altair_chart))
        else:
            spec = _altair_to_spec(chart)
            datasets = spec.pop("datasets", None) or {}
            hit = (json.dumps(spec), datasets)
            with lock:
                store[key] = hit
                while len(store) > CHART_CACHE_MAX:
                    store.popitem(last=False)
    if hit is not None:
        spec = json.loads(hit[0])          # a fresh dict each time: Streamlit edits the spec it is given
        spec["datasets"] = dict(hit[1])    # Arrow bytes, passed through as is
        st.vega_lite_chart(spec, theme=None, **_stretch(st.vega_lite_chart))


def _house_style(chart):
    """White background, light horizontal gridlines, a baseline under the bars, no tick marks, muted labels."""
    grid = dict(grid=True, gridColor=LINE, gridWidth=1, domain=False, ticks=False)
    return (chart.configure(font=FONT, background="white", padding={"left": 4, "right": 22, "top": 8, "bottom": 4})
            .configure_view(stroke=None)
            .configure_axis(labelColor=MUTED, titleColor=MUTED, labelFontSize=11, titleFontSize=11,
                            titleFontWeight="normal", labelPadding=6, domain=False, ticks=False)
            .configure_axisQuantitative(**grid)
            .configure_axisTemporal(**grid)
            .configure_axisDiscrete(grid=False, domain=True, domainColor=RULE)
            .configure_legend(labelFontSize=11, labelColor="#334155", symbolType="square", symbolSize=90,
                              titleFontSize=11, titleColor=MUTED, columnPadding=16, orient="top")
            .configure_text(color=INK))


def section(kicker, title, how):
    """Chapter opener on the one-page scroll. The anchor comes from NAV, so the menu links land here."""
    _EXH["sec"], _EXH["n"] = NAV_NUM[title], 0
    st.markdown(f"<div class='chapter'></div><div class='jump'><span id='{NAV[title]}'></span></div>"
                f"<div class='kicker'>{NAV_NUM[title]} · {kicker}</div>", unsafe_allow_html=True)
    st.subheader(title, anchor=False)
    st.markdown(how)


def exhibit(title, subtitle=None):
    """Exhibit header for a table or a set of controls (charts get theirs from show_chart)."""
    exhibit_head(title, subtitle)


def takeaway(text):
    st.markdown(f"<div class='takeaway'>{text}</div>", unsafe_allow_html=True)


def kpis(items):
    """A row of number cards. Each item: (label, value, one plain-language sentence saying what it means)."""
    cards = "".join(f"<div class='kpi'><div class='kpi-l'>{html.escape(str(lbl))}</div>"
                    f"<div class='kpi-v{' kpi-long' if len(str(val)) > 16 else ''}'>{html.escape(str(val))}</div>"
                    f"<div class='kpi-e'>{exp}</div></div>"
                    for lbl, val, exp in items)
    st.markdown(f"<div class='kpis' style='grid-template-columns: repeat({len(items)}, minmax(0, 1fr))'>{cards}</div>",
                unsafe_allow_html=True)


def source(src, note_text=None):
    """The source line under an exhibit."""
    extra = f" <b>Note:</b> {note_text}" if note_text else ""
    st.markdown(f"<div class='src'><b>Source:</b> {src}.{extra}</div>", unsafe_allow_html=True)


def covers(d, title="title", value=None, n=12):
    """A row of cover-art cards: cover, title and one value line. Missing covers get a plain placeholder."""
    cards = []
    d = d[d["cover_id"].map(lambda c: isinstance(c, str) and bool(c))] if "cover_id" in d else d.iloc[0:0]
    for r in d.head(n).itertuples():
        cid = getattr(r, "cover_id", None)
        name = html.escape(str(getattr(r, title)))
        img = (f"<img src='{COVER.format(cid)}' alt='Cover of {name}' loading='lazy'>"
               if isinstance(cid, str) and cid else f"<div class='ph'>{name}</div>")
        sub = f"<span>{html.escape(value(r))}</span>" if value else ""
        cards.append(f"<div class='cover'>{img}<b>{name}</b>{sub}</div>")
    st.markdown(f"<div class='covers'>{''.join(cards)}</div>", unsafe_allow_html=True)


# --- Class password (only when APP_PASSWORD is set, i.e. on Streamlit Cloud) --------------------------------------
def _secret(name):
    try:
        return st.secrets.get(name, "") or os.environ.get(name, "")
    except Exception:   # no secrets.toml locally
        return os.environ.get(name, "")


def password_gate():
    expected = _secret("APP_PASSWORD")
    if not expected or st.session_state.get("authed"):
        return
    st.markdown("<p class='kicker'>Media &amp; Entertainment Businesses · Games data lab</p>", unsafe_allow_html=True)
    st.title("Game Sales Lab")
    with st.form("login"):
        pw = st.text_input("Class password", type="password")
        if st.form_submit_button("Enter"):
            if hmac.compare_digest(pw.encode(), str(expected).encode()):
                st.session_state["authed"] = True
                st.rerun()
            st.error("That password isn't right. Check the Canvas announcement.")
    st.stop()


password_gate()


# --- Data (loaded once per server, shared read-only by every session) -----------------------------------------
def _read(name):
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


@st.cache_resource(show_spinner="Loading the game data…")
def load():
    games = pd.DataFrame(_read("games.json"))
    games["units"] = games["total_sales"]
    games["kind"] = np.where(games["follow_up"] == 1, "Follow-up", "Original")
    games["label"] = games["title"] + " (" + games["platform"] + ", " + games["year"].astype(str) + ")"
    attrs = pd.DataFrame(_read("attributes.json") or [])
    if len(attrs):
        games = games.merge(attrs.drop_duplicates("title"), on="title", how="left")
    for c in ["cover_id", "esrb", "multiplayer", "perspective", "user_rating", "user_rating_count"]:
        if c not in games:
            games[c] = np.nan
    frames = {n: pd.DataFrame(_read(f"{n}.json") or []) for n in ["hits", "japan", "steam", "japan_curves"]}
    pitch = _read("pitch.json")
    return (games, _read("models.json"), pd.DataFrame(pitch["rows"]), pitch["platforms"], frames,
            _read("logos.json") or {})


GAMES, MODELS, PITCH, PITCH_PLATFORMS, LAYERS, LOGOS = load()
HITS, JAPAN, STEAM, CURVES = LAYERS["hits"], LAYERS["japan"], LAYERS["steam"], LAYERS["japan_curves"]
# Every year label on the page follows the data, so extending the data needs no text edits
YEAR_MIN, YEAR_MAX = int(GAMES["year"].min()), int(GAMES["year"].max())
YY = f"{YEAR_MAX % 100:02d}"
PLATFORM_NAME = dict(zip(GAMES["platform"], GAMES["platform_name"])) | {"NS2": "Switch 2", "PS5": "PlayStation 5",
                                                                        "XS": "Xbox Series"}
GENRES = GENRE_ORDER + ["Other"]
PUBS = PUB_ORDER + ["Other"]
REG_COLS = list(REGIONS)
# North American launch year of each platform, for "years since launch"
LAUNCH = {"NES": 1985, "GB": 1989, "GEN": 1989, "SNES": 1991, "PS": 1995, "SAT": 1995, "N64": 1996, "DC": 1999,
          "PS2": 2000, "XB": 2001, "GC": 2001, "GBA": 2001, "DS": 2004, "PSP": 2005, "X360": 2005, "PS3": 2006,
          "Wii": 2006, "3DS": 2011, "PSV": 2012, "WiiU": 2012, "PS4": 2013, "XOne": 2013, "NS": 2017}

# Sources, cited under every exhibit
SRC_VGC = f"VGChartz unit-sales estimates, games released {YEAR_MIN}–{YEAR_MAX}"
SRC_HITS = ("Publisher-reported sales compiled on Wikipedia's best-selling games lists (each figure links to its "
            "citation); cover art and genres from IGDB")
SRC_JP = "Famitsu weekly Japan sales charts, as published by Gematsu; cover art and genres from IGDB"
SRC_STEAM = "SteamSpy (owner ranges and review counts); release years, genres and cover art from IGDB"
SRC_IGDB = "IGDB (player ratings, age ratings and game modes), matched to VGChartz games by title"


# --- Small helpers ---------------------------------------------------------------------------------------------
def units_fmt(v):
    """Millions of units -> '82.7M', '9.6B', '350K'."""
    if v is None or pd.isna(v):
        return "—"
    if v >= 1000:
        return f"{v / 1000:,.1f}B"
    if v >= 1:
        return f"{v:,.1f}M"
    return f"{v * 1000:,.0f}K"


def median(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return float(s.median()) if len(s) else np.nan


def pct(v, digits=0):
    return "—" if v is None or pd.isna(v) else f"{v * 100:.{digits}f}%"


def line_points(size=55):
    return alt.OverlayMarkDef(size=size, filled=True, stroke="white", strokeWidth=1.5)


def year_axis(title=None):
    return alt.X("Year:Q", title=title, axis=alt.Axis(format="d", tickMinStep=1), scale=alt.Scale(nice=False))


NOTE = {   # the README's assumptions, in plain words, repeated under the charts they apply to
    1: "VGChartz figures are estimates, not company-reported sales.",
    2: "They count mostly boxed copies sold in stores; downloads are largely missing, so recent years, PC games and "
       "download-heavy publishers look smaller than they were.",
    3: f"The VGChartz data ends in {YEAR_MAX}.",
    4: "About 1,700 games (mostly Nintendo's own) come from an older 2016 copy of the data, so their sales stop "
       "at 2016.",
    5: "A game released on three consoles counts as three games.",
    6: "Copies, not dollars: a $20 game and a $60 game count the same.",
    8: "Month views use the 97% of games with a full release date.",
    9: "Publishers are grouped by parent company at the time (Rockstar and 2K in Take-Two, Blizzard in Activision); "
       "later deals such as Microsoft buying Activision are not applied.",
    10: "Genres outside the main eight are grouped as Other.",
    11: "Series are spotted from game titles, so they are approximate: series whose games have different names are "
        "missed, and unrelated games with a shared name can be lumped together.",
    12: "Only about 4,600 games have a critic score, mostly bigger releases.",
    13: f"The models learned from games released {MODEL_FROM}–{YEAR_MAX} and were graded on games they never saw.",
    14: f"Predictions assume a {YEAR_MAX} release and describe similar past games, not a forecast for today's market.",
    "assoc": "These patterns show what went together, not what causes what: publishers give sequels, big platforms "
             "and holiday dates to the games they already believe in.",
    "release_year": "Each year counts the lifetime sales of the games released that year, not sales made during "
                    "that year.",
}


def note(*keys, src=None):
    source(src or SRC_VGC, " ".join(NOTE[k] for k in keys))


def dodge(values, gap):
    """Label positions at least `gap` apart, each as close to its value as possible (so end labels don't collide)."""
    v = pd.Series(values, dtype=float)
    order = v.sort_values().index
    pos = v[order].to_numpy().copy()
    for _ in range(50):
        moved = False
        for i in range(1, len(pos)):
            if pos[i] - pos[i - 1] < gap:
                mid, half = (pos[i] + pos[i - 1]) / 2, gap / 2
                pos[i - 1], pos[i] = mid - half, mid + half
                moved = True
        if not moved:
            break
    return pd.Series(pos, index=order).reindex(v.index)


def end_labels(d, xcol, ycol, key, frac=0.045):
    """The last point of each line, with a dodged label position LabelY."""
    last = d.sort_values(xcol).groupby(key).tail(1).copy()
    span = float(d[ycol].max() - min(0, d[ycol].min())) or 1
    last["LabelY"] = dodge(last[ycol], span * frac)
    return last


def pub_lines(d, x, y, pick, tooltip, point_size=45):
    """One line per publisher group in its own color, labeled at its last point. Sega's light line sits on a
    keyline."""
    color = alt.Color("Publisher:N", scale=alt.Scale(domain=pick, range=[PUB_COLOR[p] for p in pick]), legend=None)
    halo = alt.Chart(d).transform_filter("datum.Publisher == 'Sega'").encode(x=x, y=y)
    main = alt.Chart(d).mark_line(point=line_points(point_size), strokeWidth=2.2).encode(
        x=x, y=y, color=color, tooltip=tooltip)
    yfield = y.shorthand.split(":")[0]
    last = end_labels(d, x.shorthand.split(":")[0], yfield, "Publisher")
    # Each line ends in its company's logo plus its last value (the name stands in where there is no logo)
    last["url"] = last["Publisher"].map(lambda n: LOGOS.get(n, {}).get("src"))
    last["Label"] = last[yfield].map(lambda v: f"{v * 100:.0f}%")
    last.loc[last["url"].isna(), "Label"] = last["Publisher"] + "  " + last["Label"]
    logos = alt.Chart(last[last["url"].notna()]).mark_image(width=58, height=18, xOffset=38).encode(
        x=x, y=alt.Y("LabelY:Q"), url="url:N")
    with_logo = alt.Chart(last[last["url"].notna()]).mark_text(align="left", dx=72, fontSize=11, fontWeight=600,
                                                              color=pub_expr("Publisher")).encode(
        x=x, y=alt.Y("LabelY:Q"), text="Label:N")
    no_logo = alt.Chart(last[last["url"].isna()]).mark_text(align="left", dx=8, fontSize=11, fontWeight=600,
                                                            color=pub_expr("Publisher")).encode(
        x=x, y=alt.Y("LabelY:Q"), text="Label:N")
    labels = logos + with_logo + no_logo
    return alt.layer(halo.mark_line(color=KEYLINE, strokeWidth=4.2),
                     halo.mark_circle(color=KEYLINE, size=point_size + 40, opacity=1), main, labels)


def logo_rows(field, order, width=74, height=22, offset=-48):
    """Company logos drawn as the row labels of a chart with `field` on the y axis (pair with an axis whose labels
    are hidden). Rows without a logo get their name as text. Logos are public-domain Wikimedia Commons files."""
    d = pd.DataFrame({field: order})
    d["url"] = d[field].map(lambda n: LOGOS.get(n, {}).get("src"))
    y = alt.Y(f"{field}:N", sort=order, title=None)
    imgs = alt.Chart(d[d["url"].notna()]).mark_image(width=width, height=height).encode(
        y=y, x=alt.value(offset), url="url:N")
    names = alt.Chart(d[d["url"].isna()]).mark_text(fontSize=11, fontWeight=600, color=INK, align="right").encode(
        y=y, x=alt.value(-8), text=f"{field}:N")
    return imgs + names


DARK = {NAVY, BLUE, BERRY, SLATE, TEAL}


def stack_labels(d, group, cat, share, cat_order, colors, axis, min_share=0.06, fmt="{:.0%}"):
    """Value labels centered inside the segments of a 100% stacked bar. Segment midpoints are computed here (stacking
    in cat_order, the same order the bars use); segments under min_share stay unlabeled. White text on dark colors.
    axis is the group encoding (alt.X for columns, alt.Y for horizontal bars)."""
    d = d.copy()
    d["_o"] = d[cat].map({k: i for i, k in enumerate(cat_order)})
    d = d.sort_values([group, "_o"])
    tot = d.groupby(group)[share].transform("sum")
    d["_f"] = d[share] / tot
    d["_mid"] = d.groupby(group)["_f"].cumsum() - d["_f"] / 2
    d = d[d["_f"] >= min_share]
    d["_t"] = d["_f"].map(fmt.format)
    d["_c"] = d[cat].map(lambda k: "white" if colors.get(k) in DARK else INK)
    pos = alt.X("_mid:Q") if isinstance(axis, alt.Y) else alt.Y("_mid:Q")
    return alt.Chart(d).mark_text(fontSize=10, fontWeight=600).encode(
        axis, pos, text="_t:N", color=alt.Color("_c:N", scale=None))


def heatmap(d, x, y, x_order, y_order, legend_title, fmt_str, y_color=None, count_title="Games", logos=False):
    """Light-blue -> navy heatmap with the value printed in each cell. y_color is an Altair color expression for the
    row labels (publisher colors), or None for ink. logos=True draws company logos as the row labels."""
    yaxis = alt.Axis(labelFontWeight=600, labelColor=y_color) if y_color is not None else \
        alt.Axis(labelFontWeight=600, labelColor=INK)
    if logos:
        yaxis = alt.Axis(labels=False, title=None, domain=False, ticks=False)
    base = alt.Chart(d).encode(x=alt.X(f"{x}:N", sort=x_order, title=None,
                                       axis=alt.Axis(labelAngle=0, orient="top", labelColor=INK, domain=False)),
                               y=alt.Y(f"{y}:N", sort=y_order, title=None, axis=yaxis))
    rect = base.mark_rect(stroke="white", strokeWidth=2).encode(
        color=alt.Color("Value:Q", title=legend_title, scale=alt.Scale(range=SEQ),
                        legend=alt.Legend(orient="right", gradientLength=160, format=fmt_str)),
        tooltip=[alt.Tooltip(f"{y}:N"), alt.Tooltip(f"{x}:N"), alt.Tooltip("Value:Q", format=fmt_str, title=legend_title),
                 alt.Tooltip("n:Q", title=count_title, format=",")])
    cut = d["Value"].max() * 0.45 if len(d) else 0   # white text on the blue and navy end of the scale
    text = base.mark_text(fontSize=11).encode(
        text=alt.Text("Value:Q", format=fmt_str),
        color=alt.condition(f"datum.Value > {cut}", alt.value("white"), alt.value(INK)))
    layers = rect + text + logo_rows(y, y_order) if logos else rect + text
    return layers.properties(height=(38 if logos else 34) * len(y_order) + 24)


def hbar(d, cat, val, fmt, title, color=NAVY, highlight=None, tooltip=None, sort=None, height_per=26, logos=False):
    """Horizontal bars with the value printed at the end; `highlight` names categories drawn in blue. logos=True
    shows company logos as the row labels where a logo exists (names otherwise)."""
    order = sort or list(d.sort_values(val, ascending=False)[cat])
    ax = alt.Axis(labels=False, domain=False) if logos else alt.Axis(labelColor=INK, labelLimit=220)
    base = alt.Chart(d).encode(y=alt.Y(f"{cat}:N", sort=order, title=None, axis=ax))
    col = (alt.condition(alt.FieldOneOfPredicate(field=cat, oneOf=list(highlight)), alt.value(BLUE), alt.value(color))
           if highlight else alt.value(color))
    bars = base.mark_bar(height={"band": 0.72}).encode(
        x=alt.X(f"{val}:Q", title=title, axis=alt.Axis(format=fmt)), color=col,
        tooltip=tooltip or [alt.Tooltip(f"{cat}:N"), alt.Tooltip(f"{val}:Q", format=fmt)])
    lab = base.mark_text(align="left", dx=4, fontSize=11, color=INK).encode(x=f"{val}:Q",
                                                                            text=alt.Text(f"{val}:Q", format=fmt))
    layers = bars + lab + logo_rows(cat, order) if logos else bars + lab
    return layers.properties(height=max(140, (34 if logos else height_per) * len(order)))


def logo_key(names, colors, text_color=None):
    """One row of logos, each over its chart color, so viewers can match marks to companies. Logos are public-domain
    files from Wikimedia Commons (still trademarks of their owners), shown only to identify the companies."""
    cards = []
    for n in names:
        lg = LOGOS.get(n)
        img = f"<img src='{lg['src']}' alt='{html.escape(n)} logo'>" if lg else ""
        sw = f"background:{colors[n]};" + (f"box-shadow: inset 0 0 0 1px {KEYLINE};" if colors[n] == SILVER else "")
        tc = (text_color or (lambda x: INK))(n)
        cards.append(f"<div class='skey-card'><div class='skey-logo'>{img}</div><div class='skey-swatch' "
                     f"style='{sw}'></div><div class='skey-name' style='color:{tc}'>{html.escape(n)}</div></div>")
    st.markdown(f"<div class='skey'>{''.join(cards)}</div>", unsafe_allow_html=True)


def pub_key():
    logo_key(PUB_ORDER, PUB_COLOR, pub_text)


def family_key():
    logo_key([f for f in FAMILY_ORDER if f != "Other"], FAMILY_COLOR)


# --- Header -------------------------------------------------------------------------------------------------------
st.markdown("<div class='kicker'>Media &amp; Entertainment Businesses · Games data lab</div>", unsafe_allow_html=True)
st.title("Game Sales Lab: What Sells in the Video Game Business?")
st.markdown(f"<p class='lede'>Four decades of video game sales in one place: {len(GAMES):,} game releases from "
            f"{YEAR_MIN} to {YEAR_MAX}, plus officially reported hits, Japan's charts and PC sales on Steam through "
            f"2026. Who sells, what sells, where and when. Companion to the Behind the Box Office Lab.</p>",
            unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def headline_numbers():
    g = GAMES
    recent = g[g["year"] >= MODEL_FROM]
    by = recent.groupby(["year", "pub"])["units"].sum().reset_index()
    top5 = by.groupby("year").apply(lambda d: d.nlargest(5, "units")["units"].sum() / d["units"].sum(),
                                    include_groups=False)
    rf = lambda fs: float(np.mean(MODELS.get(fs, {}).get("cv", {}).get("Random forest", [np.nan])))
    return {"units": g["units"].sum(), "n": len(g), "hit": g["hit"].mean(), "top5": float(top5.mean()),
            "r2": rf("Greenlight"), "r2_critic": rf("Greenlight + critic score")}


H = headline_numbers()
kpis([
    ("Copies tracked", units_fmt(H["units"]),
     f"Games sold across {H['n']:,} releases, {YEAR_MIN}–{YEAR_MAX} (VGChartz estimates)."),
    ("Million-seller rate", pct(H["hit"]),
     f"Out of every 100 games, about {H['hit'] * 100:.0f} sold a million copies or more."),
    (f"Top-5 publisher share, {MODEL_FROM}–{YY}", pct(H["top5"]),
     "In a typical year, the five biggest publishers sold this share of all copies."),
    ("Sales the data can predict", pct(H["r2"]),
     f"A model using only pre-launch choices predicts about {H['r2'] * 100:.0f}% of the differences in sales "
     f"between games. Adding review scores: {H['r2_critic'] * 100:.0f}%."),
])
def about_the_data():
    """Up-front limitations: what each source counts, what it misses, and a worked example of the gap."""
    vg = GAMES[GAMES["title"].str.lower() == "call of duty: black ops iii"]["units"].sum()
    rep = HITS[(HITS["platform"] == "Multi") & (HITS["title"].str.lower() == "call of duty: black ops iii")]
    rep_v = float(rep["units_m"].iloc[0]) if len(rep) else np.nan
    st.markdown("<div class='kicker' style='margin-top:1.2rem'>Read this first</div>", unsafe_allow_html=True)
    st.subheader("About the data", anchor=False)
    st.markdown(
        "No public source counts every copy of every game. This lab combines four sources, each with real gaps. "
        "**Use the numbers to compare games, publishers and years within one source, not as exact sales.**")
    if vg and pd.notna(rep_v):
        takeaway(f"<b>How big the gaps can be:</b> VGChartz estimates <i>Call of Duty: Black Ops III</i> (2015) at "
                 f"<b>{units_fmt(vg)}</b> copies across all platforms. Activision told a court in December 2024 that "
                 f"it sold <b>{units_fmt(rep_v)}</b>. Most of the difference is downloads, which VGChartz barely "
                 f"sees. The newer the game and the bigger its download share, the larger the gap.")
    src = pd.DataFrame([
        {"Source": "VGChartz estimates (sections 1–7, 11–14)", "Years": f"{YEAR_MIN}–{YEAR_MAX}",
         "What it counts": "Estimated copies sold, by game, console and region",
         "Main gaps": "Third-party estimates, not company figures. Mostly boxed copies in stores: downloads are "
                      "largely missing, so games after about 2010, PC games and download-heavy publishers are "
                      "understated, sometimes by half. Ends in 2018."},
        {"Source": "Publisher-reported hits (section 8)", "Years": "2001–2026",
         "What it counts": "Lifetime copies the publisher announced, downloads included",
         "Main gaps": "Only games a publisher chose to announce, mostly hits above 1 million. Nintendo reports "
                      "almost everything; Sony, Microsoft and many others report little. Figures are 'as of' "
                      "different dates and mix copies sold with copies shipped to stores."},
        {"Source": "Famitsu, Japan (section 9)", "Years": "2019–2026",
         "What it counts": "Boxed copies sold in Japanese stores, weekly top 30",
         "Main gaps": "Japan only, boxed copies only (no downloads). Games that never reached the top 30 are "
                      "missing. A few weekly figures had typos, which were removed."},
        {"Source": "SteamSpy, PC (section 10)", "Years": "2018–2026",
         "What it counts": "Estimated owners on Steam (a range) and player review counts",
         "Main gaps": "Rough estimates: owner ranges are wide and inflated by free weekends and giveaways. Steam only "
                      "(not Epic, Xbox PC or others). Covers games with a following, not every release."},
        {"Source": "IGDB (covers, ratings, game modes)", "Years": "All",
         "What it counts": "Cover art, age ratings, multiplayer modes, player ratings",
         "Main gaps": "Matched to the sales data by title: 77% of VGChartz titles (89% of copies) matched. Player "
                      "ratings come from IGDB users, often years after release."},
    ])
    show_table(src, column_config={
        "Source": st.column_config.TextColumn("Source", width="medium"),
        "Years": st.column_config.TextColumn("Years", width="small"),
        "What it counts": st.column_config.TextColumn("What it counts", width="medium"),
        "Main gaps": st.column_config.TextColumn("Main gaps", width="large")}, row_height=90)
    st.markdown(
        "**What none of these sources count:** money. Copies are not revenue: a $20 game and a $70 game count the "
        "same, and none of the sources include **subscriptions** (Game Pass, PlayStation Plus), **in-game "
        "spending** (skins, battle passes, loot boxes) or **free-to-play** revenue, which today make up much of the "
        "industry's income. A game on three consoles counts as three games in the VGChartz data.\n\n"
        "**Why the sources stay apart:** they measure different things, so no chart adds one source to another. "
        "Each exhibit names its source underneath.\n\n"
        "**What the patterns mean:** every chart shows what **went together** with bigger sales. None of them "
        "proves that a choice *causes* higher sales: publishers give sequels, big budgets and holiday dates to the "
        "games they already expect to sell.")
    st.caption("Full details, every source link and the step-by-step build are in the project README on GitHub.")


about_the_data()

c1, c2 = st.columns(2)
c1.markdown("**The problem**  \n"
            "A big game takes years and tens of millions of dollars to make, and most games never sell a million "
            "copies. Publishers and console makers must decide which games to fund, for which consoles, for which "
            "countries and when to launch, while players move to downloads and subscriptions and the biggest "
            "series take a growing share of attention.")
c2.markdown("**How this lab helps**  \n"
            "It brings the evidence together: how big the **market** is and where, which **publishers** win and how, "
            "whether **sequels** hold up, the role of the **console and the calendar**, what **critics and players** "
            "reward, and what has sold **since 2019**. Then pitch your own game and see what similar games sold.")
_pills = [f"<a href='#{a}'><b>{NAV_NUM[t]}</b>{t}</a>" for t, a in NAV.items()]
st.markdown("<div class='navbar'>" + "".join(
    f"<span class='navsep'{' style=\"margin-left:0\"' if i == 0 else ''}>{name}</span>" + "".join(_pills[a:b])
    for i, (name, a, b) in enumerate(NAV_GROUPS)) + "</div>", unsafe_allow_html=True)
st.caption("Hover a column header or chart for details. Section menu and glossary: the › arrow at the top left.")


# --- 1. Market Size ------------------------------------------------------------------------------------------------
def market_section():
    section("Market", "Market Size",
            "How many games does the industry sell, where, and on whose consoles? Each year counts the lifetime "
            "sales of the games released that year.")
    y = GAMES.groupby("year")[REG_COLS].sum().rename(columns=REGIONS)
    y["Total"] = y.sum(axis=1)
    peak = int(y["Total"].idxmax())
    reg_share = GAMES[REG_COLS].sum() / GAMES["units"].sum()
    kpis([("Biggest release year", str(peak), f"Games released in {peak} sold {units_fmt(y.loc[peak, 'Total'])} "
                                              f"copies, the most of any year."),
          ("North America's share", pct(reg_share["na_sales"]), "Share of all copies bought in the US and Canada."),
          ("Europe's share", pct(reg_share["eu_sales"]), "Share of all copies bought in Europe."),
          ("Japan's share", pct(reg_share["jp_sales"]), "Share of all copies bought in Japan.")])
    long = y.drop(columns="Total").reset_index().melt("year", var_name="Region", value_name="Units")
    long = long.rename(columns={"year": "Year"})
    title = (f"Store sales peaked with the games of {peak}; North America bought "
             f"{pct(reg_share['na_sales'])} of all copies")
    marks = y.reset_index()[["year", "Total"]].rename(columns={"year": "Year"})
    marks = marks[(marks["Year"] % 5 == 0) & (marks["Year"] >= 1985) | (marks["Year"].isin([peak, YEAR_MAX]))]
    marks = marks.drop_duplicates("Year")
    marks["Label"] = marks["Total"].map(units_fmt)

    def build():
        area = alt.Chart(long).mark_area(stroke="white", strokeWidth=0.6).encode(
            x=year_axis(), y=alt.Y("Units:Q", stack=True, title="Copies sold (millions)"),
            color=alt.Color("Region:N", sort=REGION_ORDER, title=None,
                            scale=alt.Scale(domain=REGION_ORDER, range=[REGION_COLOR[r] for r in REGION_ORDER])),
            order=alt.Order("order:Q"),
            tooltip=[alt.Tooltip("Year:Q", format="d"), "Region:N", alt.Tooltip("Units:Q", format=",.1f",
                                                                                 title="Copies (M)")]
        ).transform_calculate(order=f"indexof({json.dumps(REGION_ORDER)}, datum.Region)")
        dots = alt.Chart(marks).mark_circle(color=NAVY, size=28).encode(x="Year:Q", y="Total:Q")
        lab = alt.Chart(marks).mark_text(dy=-10, fontSize=10, fontWeight=600, color=INK).encode(
            x="Year:Q", y="Total:Q", text="Label:N")
        return (area + dots + lab).properties(height=330)
    show_chart(build, title, "Copies sold of the games released each year, by region (millions)")
    note(1, 2, 3, 6, "release_year")
    takeaway("<b>Read with care:</b> much of the drop after 2010 is downloads that VGChartz can't see, not players "
             "leaving. Sections 8–10 show what sold in the download era.")

    f = GAMES.groupby(["year", "family"])["units"].sum().reset_index().rename(columns={"year": "Year",
                                                                                       "family": "Family"})
    f["Units"] = f["units"]
    f["Share"] = f["units"] / f.groupby("Year")["units"].transform("sum")
    f = f[f["Year"] >= 1985]
    late = GAMES[GAMES["year"].between(YEAR_MAX - 4, YEAR_MAX)].groupby("family")["units"].sum()
    late = late / late.sum()
    lead = late.idxmax()
    title = (f"{lead} consoles carried {pct(late[lead])} of game sales for {YEAR_MAX - 4}–{YY} releases; "
             f"{late.drop(lead).idxmax()} {pct(late.drop(lead).max())}")
    exhibit_head(title, "Share of each release year's copies sold, by console maker (handhelds included)")
    family_key()
    # Share of each maker in the last year, labeled at the right edge at the middle of its band
    end = f[f["Year"] == f["Year"].max()].copy()
    end["_o"] = end["Family"].map({k: i for i, k in enumerate(FAMILY_ORDER)})
    end = end.sort_values("_o")
    end["Mid"] = end["Share"].cumsum() - end["Share"] / 2
    end = end[end["Share"] >= 0.03]
    end["Label"] = end["Family"] + " " + end["Share"].map(lambda v: f"{v:.0%}")
    end["LabelY"] = dodge(end["Mid"], 0.06)

    end["tc"] = end["Family"].map(lambda k: FAMILY_COLOR[k] if k not in ("Sega", "Other") else MUTED)
    xax = alt.X("Year:Q", title=None, axis=alt.Axis(format="d", tickMinStep=1, values=list(range(1985, YEAR_MAX + 1, 5))),
                scale=alt.Scale(domain=[1985, YEAR_MAX + 7], nice=False))   # room on the right for the labels

    def build():
        lab = alt.Chart(end).mark_text(align="left", dx=6, fontSize=11, fontWeight=600).encode(
            x=xax, y=alt.Y("LabelY:Q"), text="Label:N", color=alt.Color("tc:N", scale=None))
        return lab + alt.Chart(f).mark_area(stroke="white", strokeWidth=0.6).encode(
            x=xax, y=alt.Y("Share:Q", stack="normalize", title="Share of copies sold",
                                   axis=alt.Axis(format="%")),
            color=alt.Color("Family:N", sort=FAMILY_ORDER, legend=None,
                            scale=alt.Scale(domain=FAMILY_ORDER, range=[FAMILY_COLOR[k] for k in FAMILY_ORDER])),
            order=alt.Order("order:Q"),
            tooltip=[alt.Tooltip("Year:Q", format="d"), "Family:N", alt.Tooltip("Share:Q", format=".0%"),
                     alt.Tooltip("Units:Q", format=",.1f", title="Copies (M)")]
        ).transform_calculate(order=f"indexof({json.dumps(FAMILY_ORDER)}, datum.Family)").properties(height=300)
    show_chart(build)
    note(1, 2, 3, 6)


# --- 2. Who's Winning ----------------------------------------------------------------------------------------------
@st.fragment
def winning_section():
    section("Competition", "Who's Winning",
            "Which publishers sell the most games, and is the business getting more concentrated? Shares are of all "
            "copies of games released that year.")
    pick = st.multiselect("Publishers", PUB_ORDER, default=["Nintendo", "Electronic Arts", "Activision", "Sony",
                                                              "Ubisoft", "Take-Two", "Microsoft"],
                          key="win_pubs", help=define("publisher"))
    years = st.slider("Release years", 1990, YEAR_MAX, (1995, YEAR_MAX), key="win_years")
    g = GAMES[GAMES["year"].between(*years)]
    by = g.groupby(["year", "pub"])["units"].sum().reset_index()
    rows = []
    for yr, d in by.groupby("year"):
        t5 = d.nlargest(5, "units")
        rows.append({"Year": yr, "Top-5 share": t5["units"].sum() / d["units"].sum(), "Top five": ", ".join(t5["pub"])})
    c = pd.DataFrame(rows)
    tot = g.groupby("pub_group")["units"].sum() / g["units"].sum()
    top = tot.drop("Other", errors="ignore").idxmax()
    kpis([("Biggest publisher", top, f"Sold {pct(tot[top])} of all copies of games released {years[0]}–{years[1]}."),
          ("Top-5 share, first year", pct(c.iloc[0]["Top-5 share"]) if len(c) else "—",
           f"Share of {years[0]}'s copies sold by that year's five biggest publishers."),
          ("Top-5 share, last year", pct(c.iloc[-1]["Top-5 share"]) if len(c) else "—",
           f"The same for {years[1]}. Higher = a more concentrated business."),
          ("Publishers in the data", f"{g['pub'].nunique():,}", "Distinct publishing companies, grouped by parent.")])
    s = g.groupby(["year", "pub_group"])["units"].sum().reset_index()
    s["Share"] = s["units"] / s.groupby("year")["units"].transform("sum")
    s = s.rename(columns={"year": "Year", "pub_group": "Publisher", "units": "Units"})
    if pick:
        d = s[s["Publisher"].isin(pick)]
        sel = tot.reindex(pick).dropna()
        best = sel.idxmax()
        title = f"{best} sold the most of these publishers: {pct(sel[best])} of {years[0]}–{years[1]} copies"
        order = [p for p in PUB_ORDER if p in pick]
        exhibit_head(title, "Share of each release year's copies sold, by publisher")
        pub_key()

        def build():
            x = alt.X("Year:Q", title=None, axis=alt.Axis(format="d", values=list(range(years[0], years[1] + 1, 2))),
                      scale=alt.Scale(domain=[years[0], years[1] + 6], nice=False))   # room for the end labels
            y = alt.Y("Share:Q", title="Share of copies sold", axis=alt.Axis(format="%"))
            tip = [alt.Tooltip("Year:Q", format="d"), "Publisher:N", alt.Tooltip("Share:Q", format=".1%"),
                   alt.Tooltip("Units:Q", format=",.1f", title="Copies (M)")]
            return pub_lines(d, x, y, order, tip).properties(height=350)
        show_chart(build)
    else:
        st.info("Pick at least one publisher.")
    note(2, 9)

    if len(c) >= 2:
        first, last = c.iloc[0], c.iloc[-1]
        title = (f"The five biggest publishers sold {pct(last['Top-5 share'])} of {int(last['Year'])}'s copies, "
                 f"vs. {pct(first['Top-5 share'])} in {int(first['Year'])}")

        def build():
            base = alt.Chart(c).encode(x=year_axis(), y=alt.Y("Top-5 share:Q", title="Top-5 share of copies sold",
                                                              axis=alt.Axis(format="%"), scale=alt.Scale(zero=False)))
            line = base.mark_line(color=NAVY, strokeWidth=2.4, point=line_points()).encode(
                tooltip=[alt.Tooltip("Year:Q", format="d"), alt.Tooltip("Top-5 share:Q", format=".0%"),
                         "Top five:N"])
            lab = base.mark_text(dy=-11, fontSize=10, color=INK).encode(text=alt.Text("Top-5 share:Q", format=".0%"))
            return (line + lab).properties(height=270)
        show_chart(build, title, "Share of each year's copies sold by that year's five biggest publishers")
        source(SRC_VGC, "All publishers count here, not only the eight above. Hover a point to see which five led. "
               + NOTE[2] + " " + NOTE[9])

    exhibit("Publisher scorecard", f"The 25 biggest publishers, games released {years[0]}–{years[1]}. "
                                   f"Click a column header to sort.")
    t = g.groupby("pub").agg(Games=("units", "size"), Units=("units", "sum"), Hit=("hit", "mean"),
                             Median=("units", "median")).reset_index()
    best = g.loc[g.groupby("pub")["units"].idxmax(), ["pub", "label"]].set_index("pub")["label"]
    t["Biggest game"] = t["pub"].map(best)
    t["Share"] = t["Units"] / g["units"].sum()
    t = t.sort_values("Units", ascending=False).head(25)
    show_table(t[["pub", "Games", "Units", "Share", "Hit", "Median", "Biggest game"]], column_config={
        "pub": "Publisher", "Games": st.column_config.NumberColumn("Games", format="%d"),
        "Units": st.column_config.NumberColumn("Copies sold (M)", format="%.1f",
                                               help="Copies sold over the games' lives, in millions."),
        "Share": st.column_config.NumberColumn("Share of units", format="percent"),
        "Hit": st.column_config.NumberColumn("Hit rate", format="percent"),
        "Median": st.column_config.NumberColumn("Typical game (M copies)", format="%.2f",
                                                help="Typical game: half sold more, half sold less (millions)."),
        "Biggest game": st.column_config.TextColumn("Biggest game", width="large")})
    big = t[t["Games"] >= 50]
    best_hit = big.loc[big["Hit"].idxmax()]
    most = t.loc[t["Games"].idxmax()]
    takeaway(f"<b>Insight:</b> {t.iloc[0]['pub']} leads with {pct(t.iloc[0]['Share'])} of all copies sold, but the "
             f"best batting average belongs to {best_hit['pub']}: {pct(best_hit['Hit'])} of its games sold a million "
             f"(publishers with 50+ games). {most['pub']} released the most games ({int(most['Games']):,}) yet only "
             f"{pct(most['Hit'])} became million-sellers: volume and hits are different strategies.")
    note(2, 9)


# --- 3. Franchise Fatigue ------------------------------------------------------------------------------------------
FIRST_MIN = 0.1   # million copies: ratios are only measured against first games that sold at least this


@st.cache_resource(show_spinner=False)
def franchise_titles():
    """One row per title in a series (all platforms summed), with its sales relative to the series' first title."""
    s = GAMES[GAMES["series"].notna()].assign(key=lambda d: d["title"].str.lower())
    # Titles that differ only in capitalization (the two scrapes spell some differently) are the same title
    t = s.groupby(["series", "key"]).agg(title=("title", "first"), Entry=("entry", "min"), Year=("year", "min"),
                                         Units=("units", "sum"),
                                         Publisher=("pub", lambda x: x.mode().iat[0]),
                                         Platforms=("platform", lambda x: ", ".join(sorted(set(x)))),
                                         Critic=("critic_score", "median"), cover_id=("cover_id", "first")).reset_index()
    n = t.groupby("series")["key"].transform("size")
    t = t[n >= 3].copy()
    first = t[t["Entry"] == t.groupby("series")["Entry"].transform("min")].groupby("series")["Units"].max()
    t["First"] = t["series"].map(first)
    t["Ratio"] = t["Units"] / t["First"]
    t["Total"] = t.groupby("series")["Units"].transform("sum")
    # A first title VGChartz barely saw (often a PC original, e.g. Call of Duty at 10K) makes every ratio explode
    t["Ratio"] = t["Ratio"].where(t["First"] >= FIRST_MIN)
    names = {}
    for ser, titles in s.groupby("series")["title"]:
        hit = next((x[:len(ser)] for x in titles if x.lower().startswith(ser)), None)
        names[ser] = hit or ser.title()
    t["Name"] = t["series"].map(names)
    return t


ROMAN_NUM = {"ii": "2", "iii": "3", "iiii": "4", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8"}


def title_key(t):
    """Match key for one game written two ways: lowercase, no punctuation, Roman numerals as digits
    ('Black Ops III' = 'Black Ops 3')."""
    words = re.sub(r"[^a-z0-9 ]+", " ", str(t).lower()).split()
    return " ".join(ROMAN_NUM.get(w, w) for w in words)


@st.fragment
def fatigue_section():
    section("Franchises", "Franchise Fatigue",
            "Sequels are the industry's safest bet. But do later games keep their audience, or does each one sell "
            "less than the last? Each game in a series is summed across its consoles and compared with the series' "
            "first game.")
    t = franchise_titles()
    o, fu = GAMES[GAMES["follow_up"] == 0], GAMES[GAMES["follow_up"] == 1]
    kpis([("Typical sequel vs. original", f"{units_fmt(median(fu['units']))} vs. {units_fmt(median(o['units']))}",
           "Copies sold by the typical follow-up game vs. the typical original."),
          ("Million-seller rate", f"{pct(fu['hit'].mean())} vs. {pct(o['hit'].mean())}",
           "Follow-ups vs. originals: out of 100 games, how many sold a million."),
          ("Critic score", f"{median(fu['critic_score']):.1f} vs. {median(o['critic_score']):.1f}",
           "Typical review score (0–10), follow-ups vs. originals."),
          ("Games that are follow-ups", pct(GAMES["follow_up"].mean()),
           "Share of all releases that continue an earlier series.")])
    later = t[(t["Entry"] >= 2) & t["Ratio"].notna()].copy()
    later["Entry #"] = later["Entry"].clip(upper=10)
    e = later.groupby("Entry #").agg(Median=("Ratio", "median"), Beat=("Ratio", lambda r: (r > 1).mean()),
                                     n=("Ratio", "size")).reset_index()
    e["Entry label"] = np.where(e["Entry #"] >= 10, "10+", e["Entry #"].astype(int).astype(str))
    order = list(e["Entry label"])
    e2 = e[e["Entry #"] == 2].iloc[0] if (e["Entry #"] == 2).any() else None
    title = (f"The typical second game sells {e2['Median'] * 100:.0f}% as many copies as the first; only "
             f"{pct(e2['Beat'])} outsell it" if e2 is not None else "Later games vs. the first")

    def build():
        base = alt.Chart(e).encode(x=alt.X("Entry label:N", sort=order, title="Game number in the series",
                                           axis=alt.Axis(labelAngle=0)))
        bars = base.mark_bar(color=NAVY, width={"band": 0.66}).encode(
            y=alt.Y("Median:Q", title="Copies sold ÷ the first game's copies", axis=alt.Axis(format=".0%")),
            tooltip=[alt.Tooltip("Entry label:N", title="Game number"),
                     alt.Tooltip("Median:Q", format=".0%", title="Typical sales vs. first game"),
                     alt.Tooltip("Beat:Q", format=".0%", title="Share outselling the first"),
                     alt.Tooltip("n:Q", title="Games")])
        lab = base.mark_text(dy=-8, fontSize=11, color=INK).encode(y="Median:Q", text=alt.Text("Median:Q",
                                                                                            format=".0%"))
        one = alt.Chart(pd.DataFrame({"y": [1]})).mark_rule(color=BLUE, strokeDash=[4, 3]).encode(y="y:Q")
        return (bars + lab + one).properties(height=300)
    show_chart(build, title, "Typical sales of each later game as a share of its series' first game "
                             "(dashed line = sold the same)")
    kept = t.loc[t["Ratio"].notna(), "series"].nunique()
    note(11, src=SRC_VGC)
    st.caption(f"{kept:,} of {t['series'].nunique():,} series with 3+ games. Series whose first game sold under "
               f"{FIRST_MIN * 1000:.0f}K copies in the data are left out (often a PC original VGChartz barely "
               f"counted), because every later ratio would look huge.")
    takeaway(f"<b>So what:</b> each sequel sells more than a typical new game and hits a million more often, but "
             f"less than the game that started the series. Follow-ups start from proven demand: publishers make "
             f"sequels to games that already sold ({len(fu):,} follow-up releases vs. {len(o):,} originals).")

    series = (t.drop_duplicates("series").sort_values("Total", ascending=False)["series"].tolist())
    name = dict(zip(t["series"], t["Name"]))
    default = series.index("call of duty") if "call of duty" in series else 0
    pick = st.selectbox("Pick a series (3+ games)", series, index=default, format_func=lambda s: name[s],
                        key="fatigue_series")
    d = t[t["series"] == pick].sort_values(["Entry", "Year"]).copy()
    # Publisher-reported totals (all platforms, downloads included) where they exist, and series games released
    # after 2018 that only the reported figures cover
    rep = HITS[(HITS["platform"] == "Multi") & (HITS.get("series") == pick)] if "series" in HITS else HITS.iloc[0:0]
    rep = rep.assign(key=rep["title"].map(title_key)).drop_duplicates("key")
    d["Reported"] = d["title"].map(title_key).map(dict(zip(rep["key"], rep["units_m"])))
    extra = rep[~rep["key"].isin(d["title"].map(title_key))]
    if len(extra):
        d = pd.concat([d, pd.DataFrame({"title": extra["title"], "Year": extra["release_year"].astype(int),
                                        "Units": np.nan, "Reported": extra["units_m"], "Entry": 999,
                                        "cover_id": extra["cover_id"], "Publisher": extra["pub"]})],
                      ignore_index=True)
    d = d.sort_values(["Year", "Entry"]).reset_index(drop=True)
    d["Game"] = d["title"] + " (" + d["Year"].astype(int).astype(str) + ")"
    d["Best"] = d["Reported"].fillna(d["Units"])
    best = d.loc[d["Best"].idxmax()]
    best_src = "publisher-reported" if pd.notna(best["Reported"]) else "VGChartz estimate"
    vg_best = d.loc[d["Units"].idxmax()] if d["Units"].notna().any() else best
    title = f"{best['title']} is the best seller of the {name[pick]} series: {units_fmt(best['Best'])} copies ({best_src})"
    if best_src == "publisher-reported" and vg_best["title"] != best["title"]:
        title += f"; VGChartz alone would have picked {vg_best['title']}"
    names = list(d["Game"])
    # The series' best seller, cover first, right under the picker
    hero, info = st.columns([1, 4])
    with hero:
        covers(pd.DataFrame([best]), "title", None, n=1)
    with info:
        kpis([("Best seller", best["title"], f"{units_fmt(best['Best'])} copies ({best_src}), released "
                                             f"{int(best['Year'])}."),
              ("Games in the series", f"{len(d)}", f"From {int(d['Year'].min())} to {int(d['Year'].max())}."),
              ("Series total (VGChartz)", units_fmt(d["Units"].sum()),
               f"Copies of the games released through {YEAR_MAX}, as VGChartz estimates them."),
              ("Publisher-reported games", f"{int(d['Reported'].notna().sum())}",
               "Games in this series with an official total (the blue markers).")])

    def build():
        base = alt.Chart(d).encode(x=alt.X("Game:N", sort=names, title=None,
                                           axis=alt.Axis(labelAngle=-40, labelLimit=180)))
        tip = ["title:N", alt.Tooltip("Year:Q", format="d"), "Publisher:N",
               alt.Tooltip("Units:Q", format=",.2f", title="VGChartz estimate (M)"),
               alt.Tooltip("Reported:Q", format=",.1f", title="Publisher-reported (M)")]
        bars = base.mark_bar(width={"band": 0.7}).encode(
            y=alt.Y("Units:Q", title="Copies sold, all platforms (millions)"),
            color=alt.condition(f"datum.Entry == {int(d['Entry'].min())}", alt.value(SILVER), alt.value(NAVY)),
            tooltip=tip)
        lab = base.mark_text(dy=-7, fontSize=10, color=INK).encode(y="Units:Q", text=alt.Text("Units:Q", format=".1f"))
        r = base.transform_filter("isValid(datum.Reported)")
        dots = r.mark_point(shape="diamond", size=110, filled=True, color=BLUE, stroke="white", strokeWidth=1).encode(
            y="Reported:Q", tooltip=tip)
        rlab = r.mark_text(dy=-11, fontSize=10, fontWeight=700, color=BLUE).encode(
            y="Reported:Q", text=alt.Text("Reported:Q", format=".0f"))
        return (bars + lab + dots + rlab).properties(height=340)
    show_chart(build, title, f"{name[pick]}: navy bars = VGChartz estimate (mostly boxed copies, through {YEAR_MAX}); "
                             f"blue diamonds = publisher-reported total, downloads included; gray = first game")
    covers(d.sort_values("Best", ascending=False), "title", lambda r: f"{units_fmt(r.Best)} · {int(r.Year)}", n=8)
    gap = d.dropna(subset=["Units", "Reported"])
    if len(gap):
        ratio = (gap["Reported"] / gap["Units"]).median()
        takeaway(f"<b>Insight:</b> where both numbers exist, the publisher's own total is typically "
                 f"{ratio:.1f}× the VGChartz estimate for this series: downloads that store tracking misses. "
                 f"Compare games within one source, not across the two.")
    source(SRC_VGC + "; " + SRC_HITS.split(";")[0],
           NOTE[11] + " " + NOTE[2] + " Publisher totals are worldwide, all platforms, as last announced.")


# --- 4. Publisher Playbooks ----------------------------------------------------------------------------------------
H2H_YEARS = (MODEL_FROM, YEAR_MAX)


@st.fragment
def publishers_section():
    section("Strategy", "Publisher Playbooks",
            f"Where does each publisher place its bets: which genres, which consoles? All exhibits use games released "
            f"{H2H_YEARS[0]}–{H2H_YEARS[1]}.")
    g = GAMES[GAMES["year"].between(*H2H_YEARS)]
    m = g.groupby(["pub_group", "genre"]).agg(units=("units", "sum"), n=("units", "size")).reset_index()
    m["Value"] = m["units"] / m.groupby("pub_group")["units"].transform("sum")
    m = m.rename(columns={"pub_group": "Publisher", "genre": "Genre"})
    top = m[m["Publisher"] != "Other"].loc[lambda d: d["Value"].idxmax()]
    title = f"{top['Publisher']} is the most focused: {pct(top['Value'])} of its sales are {top['Genre']} games"
    show_chart(lambda: heatmap(m, "Genre", "Publisher", GENRES, PUBS, "Share of sales", ".0%", logos=True),
               title, "Share of each publisher's copies sold, by genre (each row adds to 100%)", panel=False)
    note(2, 9, 10)

    f = g.groupby(["pub_group", "family"])["units"].sum().reset_index()
    f["Share"] = f["units"] / f.groupby("pub_group")["units"].transform("sum")
    f = f.rename(columns={"pub_group": "Publisher", "family": "Family", "units": "Units"})
    nin = f[(f["Publisher"] == "Nintendo") & (f["Family"] == "Nintendo")]["Share"]
    third = f[~f["Publisher"].isin(["Nintendo", "Sony", "Microsoft", "Other"])]
    spread = third.groupby("Publisher")["Share"].max().idxmin()
    title = (f"Console makers publish for their own machines (Nintendo: {pct(nin.iat[0] if len(nin) else np.nan)}); "
             f"{spread} spreads its games most evenly")
    exhibit_head(title, "Share of each publisher's copies sold, by console maker")
    family_key()

    def build():
        yax = alt.Y("Publisher:N", sort=PUBS, title=None, axis=alt.Axis(labels=False, domain=False))
        lab = stack_labels(f, "Publisher", "Family", "Share", FAMILY_ORDER, FAMILY_COLOR, yax)
        return (alt.Chart(f).mark_bar(stroke="white", strokeWidth=0.8, height={"band": 0.72}).encode(
            y=yax,
            x=alt.X("Share:Q", stack="normalize", title="Share of copies sold", axis=alt.Axis(format="%")),
            color=alt.Color("Family:N", sort=FAMILY_ORDER, legend=None,
                            scale=alt.Scale(domain=FAMILY_ORDER, range=[FAMILY_COLOR[k] for k in FAMILY_ORDER])),
            order=alt.Order("order:Q"),
            tooltip=["Publisher:N", "Family:N", alt.Tooltip("Share:Q", format=".0%"),
                     alt.Tooltip("Units:Q", format=",.1f", title="Copies (M)")]
        ).transform_calculate(order=f"indexof({json.dumps(FAMILY_ORDER)}, datum.Family)")
            + lab + logo_rows("Publisher", PUBS)).properties(height=38 * len(PUBS))
    show_chart(build)
    note(2, 9)

    exhibit("Head to head", "Pick two publishers to compare their playbooks side by side.")
    names = g.groupby("pub")["units"].sum().sort_values(ascending=False)
    names = list(names[g.groupby("pub").size().reindex(names.index) >= 30].index)
    c1, c2 = st.columns(2)
    a = c1.selectbox("Publisher A", names, index=names.index("Electronic Arts") if "Electronic Arts" in names else 0,
                     key="h2h_a")
    b = c2.selectbox("Publisher B", names, index=names.index("Activision") if "Activision" in names else 1,
                     key="h2h_b")

    def profile(p):
        d = g[g["pub"] == p]
        dated = d[d["month"].notna()]
        return {"Games released": f"{len(d):,}", "Copies sold": units_fmt(d["units"].sum()),
                "Typical game sells": units_fmt(median(d["units"])),
                "Million-seller rate": pct(d["hit"].mean()), "Share that are sequels": pct(d["follow_up"].mean()),
                "Typical critic score (0–10)": f"{median(d['critic_score']):.1f}",
                "Sales from holiday launches": pct(dated[dated["month"] >= 10]["units"].sum() / dated["units"].sum())
                if dated["units"].sum() else "—",
                "Top genre": d.groupby("genre")["units"].sum().idxmax(),
                "Top console maker": d.groupby("family")["units"].sum().idxmax(),
                "Biggest game": d.loc[d["units"].idxmax(), "label"]}
    pa = profile(a)
    h = pd.DataFrame({"Measure": list(pa), a: list(pa.values())})
    if a != b:
        h[b] = list(profile(b).values())
    show_table(h, column_config={"Measure": st.column_config.TextColumn("Measure", width="medium")})
    if a != b:
        da, db = g[g["pub"] == a], g[g["pub"] == b]
        ha, hb = da["hit"].mean(), db["hit"].mean()
        lead, lag = (a, b) if ha >= hb else (b, a)
        takeaway(f"<b>Insight:</b> {lead} turns more of its games into million-sellers ({pct(max(ha, hb))} vs. "
                 f"{pct(min(ha, hb))} for {lag}). {a}'s sales lean on {da.groupby('genre')['units'].sum().idxmax()} "
                 f"games and {b}'s on {db.groupby('genre')['units'].sum().idxmax()}.")
    note(2, 9)


# --- 5. Platforms & Calendar ---------------------------------------------------------------------------------------
@st.fragment
def platforms_section():
    section("Timing", "Platforms & Calendar",
            "When in a console's life do its games sell, and when in the year should a game launch?")
    dated = GAMES[GAMES["month"].notna()].copy()
    hol = dated["month"] >= 10
    hol_u = dated.loc[hol, "units"].sum() / dated["units"].sum()
    hol_g = hol.mean()
    plats = [p for p in LAUNCH if p in set(GAMES["platform"])]
    pick = st.multiselect("Consoles", plats, default=["PS2", "PS3", "PS4", "X360", "XOne", "Wii", "DS"],
                          format_func=lambda p: PLATFORM_NAME.get(p, p), key="plat_pick")
    pk = None
    if pick:
        d = GAMES[GAMES["platform"].isin(pick)].copy()
        d["Years since launch"] = d["year"] - d["platform"].map(LAUNCH)
        d = d[d["Years since launch"].between(0, 10)]
        d = d.groupby(["platform", "family", "Years since launch"]).agg(Units=("units", "sum"),
                                                                        Games=("units", "size")).reset_index()
        d["Platform"] = d["platform"].map(lambda p: PLATFORM_NAME.get(p, p))
        pk = d.loc[d.groupby("Platform")["Units"].idxmax()].copy()
    kpis([("Peak year for a console's games", f"Year {median(pk['Years since launch']):.0f}" if pk is not None else "—",
           "Years after launch when its games typically sell the most (consoles picked)."),
          ("Holiday share of sales", pct(hol_u), "Share of copies sold by games launched October–December."),
          ("Holiday share of launches", pct(hol_g), "Share of games launched October–December."),
          ("Million-seller rate", f"{pct(dated.loc[hol, 'hit'].mean())} vs. {pct(dated.loc[~hol, 'hit'].mean())}",
           "Holiday launches vs. the rest of the year.")])
    if pick:
        title = (f"Games sell best {median(pk['Years since launch']):.0f} years into a console's life; the "
                 f"biggest year here is {pk.loc[pk['Units'].idxmax(), 'Platform']} "
                 f"({units_fmt(pk['Units'].max())} copies)")
        fams = [k for k in FAMILY_ORDER if k in set(d["family"])]

        def build():
            x = alt.X("Years since launch:Q", title="Years since the console launched",
                      axis=alt.Axis(format="d", tickMinStep=1))
            y = alt.Y("Units:Q", title="Copies sold of games released that year (M)")
            lines = alt.Chart(d).mark_line(point=line_points(40), strokeWidth=2).encode(
                x=x, y=y, detail="Platform:N",
                color=alt.Color("family:N", title=None, sort=fams,
                                scale=alt.Scale(domain=fams, range=[FAMILY_COLOR[k] for k in fams])),
                tooltip=["Platform:N", alt.Tooltip("Years since launch:Q", format="d"),
                         alt.Tooltip("Units:Q", format=",.1f", title="Copies (M)"), "Games:Q"])
            # Lines all end near zero, so each console is labeled at its peak year instead (dodged apart)
            lab = pk.copy()
            lab["LabelY"] = dodge(lab["Units"] + d["Units"].max() * 0.05, d["Units"].max() * 0.055)
            lab["Label"] = lab["Platform"] + " " + lab["Units"].map(units_fmt)
            labels = alt.Chart(lab).mark_text(align="center", fontSize=11, fontWeight=600).encode(
                x=x, y=alt.Y("LabelY:Q"), text="Label:N",
                color=alt.Color("family:N", scale=alt.Scale(domain=fams, range=[FAMILY_COLOR[k] for k in fams]),
                                legend=None))
            return (lines + labels).properties(height=340)
        show_chart(build, title, "Copies sold of the games released in each year of a console's life (millions)")
    else:
        st.info("Pick at least one console.")
    note(5, 2, "release_year")

    dated["Month"] = dated["month"].astype(int).map(lambda m: MONTHS[m - 1])
    mth = dated.groupby("Month").agg(units=("units", "sum"), games=("units", "size")).reindex(MONTHS).reset_index()
    mth["Share of copies sold"] = mth["units"] / mth["units"].sum()
    mth["Share of game launches"] = mth["games"] / mth["games"].sum()
    long = mth.melt("Month", ["Share of game launches", "Share of copies sold"], var_name="Measure",
                    value_name="Share")
    title = (f"October–December launches are {pct(hol_g)} of games but {pct(hol_u)} of sales: holiday games sell "
             f"more each")

    def build():
        kinds = ["Share of game launches", "Share of copies sold"]
        base = alt.Chart(long).encode(
            x=alt.X("Month:N", sort=MONTHS, title=None, axis=alt.Axis(labelAngle=0)),
            xOffset=alt.XOffset("Measure:N", sort=kinds),
            y=alt.Y("Share:Q", title="Share of the year", axis=alt.Axis(format="%")))
        bars = base.mark_bar(stroke="white", strokeWidth=0.8).encode(
            color=alt.Color("Measure:N", sort=kinds, title=None, scale=alt.Scale(domain=kinds, range=[SILVER, NAVY])),
            tooltip=["Month:N", "Measure:N", alt.Tooltip("Share:Q", format=".1%")])
        lab = base.mark_text(dy=-7, fontSize=9, color=INK).encode(text=alt.Text("Share:Q", format=".0%"))
        return (bars + lab).properties(height=310)
    show_chart(build, title, "Share of game launches and of copies sold, by launch month")
    note(8, 5, "assoc")


# --- 6. Regional Taste ---------------------------------------------------------------------------------------------
@st.fragment
def regions_section():
    section("Audiences", "Regional Taste", "Do players in North America, Europe and Japan want the same games?")
    r = GAMES.groupby("genre")[REG_COLS].sum().rename(columns=REGIONS)
    n = GAMES.groupby("genre").size()
    share = r / r.sum()
    gap = (share["Japan"] - share["North America"]).sort_values()
    jp_top, na_top = gap.index[-1], gap.index[0]
    kpis([(f"{jp_top} in Japan", pct(share.loc[jp_top, "Japan"]),
           f"Share of Japan's game sales, vs. {pct(share.loc[jp_top, 'North America'])} in North America."),
          (f"{na_top} in North America", pct(share.loc[na_top, "North America"]),
           f"Share of North American sales, vs. {pct(share.loc[na_top, 'Japan'])} in Japan."),
          ("Europe vs. North America", "Close",
           "Europe's genre mix differs from North America's by only a few points in every genre."),
          ("Japan's share of all sales", pct(GAMES["jp_sales"].sum() / GAMES["units"].sum()),
           "Share of all copies sold that were bought in Japan.")])
    long = share.reset_index().melt("genre", var_name="Region", value_name="Value").rename(columns={"genre": "Genre"})
    long["n"] = long["Genre"].map(n)
    title = (f"Japan buys far more {jp_top} games than North America ({pct(share.loc[jp_top, 'Japan'])} vs. "
             f"{pct(share.loc[jp_top, 'North America'])}); North America leans {na_top}")
    show_chart(lambda: heatmap(long, "Region", "Genre", REGION_ORDER, GENRES, "Share of sales", ".0%"),
               title, "Share of each region's copies sold, by genre (each column adds to 100%)", panel=False)
    note(2, 10)

    reg = st.radio("Region", REGION_ORDER, horizontal=True, key="reg_pick")
    col = {v: k for k, v in REGIONS.items()}[reg]
    exhibit(f"The 15 best-selling games in {reg}", "Copies sold in the region, and how much of the game's worldwide "
                                                   "sales that region made up")
    t = with_cover_url(GAMES.nlargest(15, col).copy())
    t["Region share"] = t[col] / t["units"]
    show_table(t[["cover", "title", "platform", "year", "pub", "genre", col, "units", "Region share"]], column_config={
        "cover": cover_col(), "title": st.column_config.TextColumn("Game", width="medium"), "platform": "Console",
        "year": st.column_config.NumberColumn("Year", format="%d"), "pub": "Publisher", "genre": "Genre",
        col: st.column_config.NumberColumn(f"{reg} copies (M)", format="%.2f", help=define(reg)),
        "units": st.column_config.NumberColumn("Worldwide copies (M)", format="%.2f"),
        "Region share": st.column_config.NumberColumn("Share of the game's sales", format="percent",
                                                      help=f"{reg} copies ÷ the game's worldwide copies.")},
        row_height=60)
    top_pub = t["pub"].value_counts()
    takeaway(f"<b>Insight:</b> {top_pub.index[0]} made {int(top_pub.iloc[0])} of "
             f"{reg}'s 15 biggest sellers. For the typical game on this list, {reg} bought "
             f"{pct(median(t['Region share']))} of all its copies"
             + (", far above the region's overall share: these are local favorites." if
                median(t["Region share"]) > 1.5 * GAMES[col].sum() / GAMES["units"].sum() else "."))
    note(2, 5)


# --- 7. Critics & Players ------------------------------------------------------------------------------------------
BANDS = ["Under 5", "5–6", "6–7", "7–8", "8–9", "9+"]
RATING_BANDS = ["Under 60", "60–69", "70–79", "80–89", "90+"]
ESRB_ORDER = ["E", "E10+", "T", "M"]


def band_chart(b, cat, order, xtitle, n_label="Games"):
    def build():
        base = alt.Chart(b).encode(x=alt.X(f"{cat}:N", sort=order, title=xtitle, axis=alt.Axis(labelAngle=0)))
        tip = [alt.Tooltip(f"{cat}:N"), alt.Tooltip("Hit:Q", format=".0%", title="Million-seller rate"),
               alt.Tooltip("Median:Q", format=".2f", title="Typical game (M copies)"),
               alt.Tooltip("n:Q", title=n_label, format=",")]
        bars = base.mark_bar(color=NAVY, width={"band": 0.66}).encode(
            y=alt.Y("Hit:Q", title="Million-seller rate", axis=alt.Axis(format="%")), tooltip=tip)
        lab = base.mark_text(dy=-8, fontSize=11, color=INK).encode(y="Hit:Q", text=alt.Text("Hit:Q", format=".0%"))
        return (bars + lab).properties(height=280)
    return build


def critics_section():
    section("Quality", "Critics & Players",
            "Do better-reviewed games sell more? And what about players' own ratings, age ratings and multiplayer? "
            "Each exhibit uses only the games that have that information.")
    c = GAMES[GAMES["critic_score"].notna()].copy()
    c["Band"] = pd.cut(c["critic_score"], [-0.1, 4.99, 5.99, 6.99, 7.99, 8.99, 10.01], labels=BANDS).astype(str)
    b = c.groupby("Band").agg(Median=("units", "median"), Hit=("hit", "mean"), n=("units", "size")).reindex(BANDS)
    b = b.reset_index()
    lo_hit = c[c["critic_score"] < 6]["hit"].mean()
    p = GAMES[GAMES["user_rating_count"].fillna(0) >= 5].copy()
    mp = GAMES[GAMES["multiplayer"].notna()]
    kpis([("Critics' favorites (9+)", pct(b.iloc[-1]["Hit"]), "Of games critics scored 9 or 10, the share that sold "
                                                              "a million copies."),
          ("Poorly reviewed (under 6)", pct(lo_hit), "The same share for games critics scored under 6."),
          ("Multiplayer vs. single-player", f"{pct(mp[mp['multiplayer'] == 1]['hit'].mean())} vs. "
                                            f"{pct(mp[mp['multiplayer'] == 0]['hit'].mean())}",
           "Million-seller rate of games you can play with others vs. alone only."),
          ("Games with player ratings", f"{len(p):,}", "Games rated by at least 5 players on IGDB.")])
    title = f"{pct(b.iloc[-1]['Hit'])} of games critics scored 9+ sold a million, vs. {pct(lo_hit)} of those under 6"
    show_chart(band_chart(b, "Band", BANDS, "Critic score (0–10)"), title,
               "Million-seller rate by critic score")
    note(12, "assoc")

    if len(p):
        p["Band"] = pd.cut(p["user_rating"], [-1, 59.99, 69.99, 79.99, 89.99, 101], labels=RATING_BANDS).astype(str)
        pb = p.groupby("Band").agg(Median=("units", "median"), Hit=("hit", "mean"),
                                   n=("units", "size")).reindex(RATING_BANDS).reset_index()
        title = (f"Players agree with critics: {pct(pb.iloc[-1]['Hit'])} of games players rate 90+ sold a million, "
                 f"vs. {pct(pb.iloc[0]['Hit'])} of those under 60")
        show_chart(band_chart(pb, "Band", RATING_BANDS, "Player rating on IGDB (0–100)"), title,
                   "Million-seller rate by players' rating")
        source(SRC_IGDB, "Players rate games after release, often years later, so a high rating can reflect a game's "
                         "success as much as explain it. " + NOTE["assoc"])

    e = GAMES[GAMES["esrb"].isin(ESRB_ORDER)]
    if len(e):
        eb = e.groupby("esrb").agg(Median=("units", "median"), Hit=("hit", "mean"),
                                   n=("units", "size")).reindex(ESRB_ORDER).reset_index()
        top = eb.loc[eb["Hit"].idxmax()]
        title = f"{top['esrb']}-rated games are the most likely to sell a million ({pct(top['Hit'])})"
        show_chart(band_chart(eb, "esrb", ESRB_ORDER, "US age rating (ESRB)"), title,
                   "Million-seller rate by age rating: E = everyone, E10+ = 10 and up, T = teen, M = mature (17+)")
        source(SRC_IGDB, "Age ratings exist only for games released in North America (ESRB began in 1994). "
                         + NOTE["assoc"])


# --- 8. Blockbusters Since 2019 (officially reported sales) --------------------------------------------------------
@st.fragment
def hits_section():
    section("The digital era", "Blockbusters Since 2019",
            "VGChartz stops in 2018, and much of what sells now is downloaded. For recent years the most reliable "
            "free numbers are what **publishers themselves report** for their hits, downloads included. These "
            "come from Wikipedia's best-seller lists, where every figure links to its source.")
    if HITS.empty:
        st.info("The hits data isn't built yet (run enrich/build_extended.py).")
        return
    allh = HITS[(HITS["platform"] != "Multi") & HITS["release_year"].between(2001, 2026)].copy()
    h = allh[allh["release_year"] >= 2019].copy()
    pubs = h.groupby("pub")["units_m"].sum().sort_values(ascending=False)
    top_game = h.loc[h["units_m"].idxmax()]
    kpis([("Hits listed since 2019", f"{len(h):,}", "Games released 2019 or later with publisher-reported sales "
                                                    "(mostly 1 million copies or more), per console."),
          ("Copies sold", units_fmt(h["units_m"].sum()), "Total reported sales of those games, downloads included."),
          ("Biggest seller", top_game["title"], f"{units_fmt(top_game['units_m'])} copies on "
                                                f"{top_game['platform_name']}."),
          ("Top publisher", pubs.index[0], f"{pct(pubs.iloc[0] / pubs.sum())} of these hits' sales.")])

    # Long run: the same source for every year, so the line can run past VGChartz's 2018 end
    yr = allh.groupby(["release_year", "family"])["units_m"].sum().reset_index()
    yr = yr.rename(columns={"release_year": "Year", "family": "Family", "units_m": "Units"})
    fams = [f for f in FAMILY_ORDER if f in set(yr["Family"])]
    tot = yr.groupby("Year")["Units"].sum().reset_index()
    tot["Label"] = tot["Units"].map(lambda v: f"{v:,.0f}")
    pre = tot[tot["Year"].between(2010, 2018)]["Units"].mean()
    post = tot[tot["Year"].between(2019, 2025)]["Units"].mean()
    trend = ("about the same as" if abs(post / pre - 1) < 0.15 else "above" if post > pre else "below")
    title = (f"Reported hit sales average {post:,.0f}M copies a year for 2019–25 releases, {trend} the "
             f"{pre:,.0f}M of 2010–18" + (", partly because newer games are still selling and fewer publishers "
                                         "report" if trend == "below" else ""))

    def build():
        bars = alt.Chart(yr).mark_bar(stroke="white", strokeWidth=0.5).encode(
            x=alt.X("Year:O", title=None, axis=alt.Axis(labelAngle=0, values=list(range(2001, 2027, 2)))),
            y=alt.Y("Units:Q", title="Reported copies sold (millions)"),
            color=alt.Color("Family:N", sort=fams, title=None,
                            scale=alt.Scale(domain=fams, range=[FAMILY_COLOR[k] for k in fams])),
            order=alt.Order("o:Q"),
            tooltip=[alt.Tooltip("Year:O"), "Family:N", alt.Tooltip("Units:Q", format=",.1f", title="Copies (M)")]
        ).transform_calculate(o=f"indexof({json.dumps(fams)}, datum.Family)")
        lab = alt.Chart(tot).mark_text(dy=-6, fontSize=9, color=INK).encode(x="Year:O", y="Units:Q", text="Label:N")
        return (bars + lab).properties(height=320)
    show_chart(build, title, "Publisher-reported copies sold of hit games, by release year and console maker "
                             "(millions), 2001–2026")
    source(SRC_HITS, "The same source for every year, so unlike the VGChartz charts this one runs past 2018. It counts "
                     "only games with reported figures (mostly hits above 1 million); recent games are still selling, "
                     "so the latest years will grow. Since about 2020 Sony and Microsoft report fewer titles, which "
                     "understates their consoles. PC appears only for PC-specific figures.")

    exhibit_head(f"{pubs.index[0]} sold {pct(pubs.iloc[0] / pubs.sum())} of the reported hit sales since 2019",
                 "Reported copies sold of hit games released 2019 or later, by publisher (millions)")
    d = pubs.head(12).rename_axis("Publisher").reset_index(name="Units")
    show_chart(lambda: hbar(d, "Publisher", "Units", ",.0f", "Copies sold (millions)", highlight=[d.iloc[0]["Publisher"]],
                            logos=True))
    source(SRC_HITS, "Only games a publisher announced figures for are counted, mostly hits above 1 million, so "
                     "publishers that rarely report numbers (and smaller games) are missing. Figures are 'as of' "
                     "different dates and mix copies sold with copies shipped to stores.")

    fam = h.groupby("family")["units_m"].sum()
    fam = fam / fam.sum()
    plat = h.groupby("platform").agg(Units=("units_m", "sum"), Games=("units_m", "size")).reset_index()
    plat["Platform"] = plat["platform"].map(lambda p: PLATFORM_NAME.get(p, p))
    plat = plat.sort_values("Units", ascending=False)
    exhibit_head(f"Nintendo machines account for {pct(fam.get('Nintendo', 0))} of reported hit sales since 2019",
                 "Reported copies sold of hit games released 2019 or later, by console (millions)")
    show_chart(lambda: hbar(plat, "Platform", "Units", ",.0f", "Copies sold (millions)",
                            tooltip=["Platform:N", alt.Tooltip("Units:Q", format=",.1f", title="Copies (M)"),
                                     alt.Tooltip("Games:Q", title="Hit games")]))
    source(SRC_HITS, "Nintendo reports sales for nearly all its own million-sellers every quarter; Sony and Microsoft "
                     "report far fewer titles, so their consoles are understated here.")

    exhibit("The 12 biggest hits since 2019", "Publisher-reported copies sold, downloads included")
    top = h.sort_values("units_m", ascending=False)
    covers(top, "title", lambda r: f"{units_fmt(r.units_m)} · {r.platform_name}", n=12)
    t = with_cover_url(top.head(40))
    show_table(t[["cover", "title", "platform_name", "release_year", "pub", "units_m", "as_of", "source_link"]],
               column_config={
                   "cover": cover_col(), "title": st.column_config.TextColumn("Game", width="medium"),
                   "platform_name": "Console", "release_year": st.column_config.NumberColumn("Year", format="%d"),
                   "pub": "Publisher", "units_m": st.column_config.NumberColumn("Copies sold (M)", format="%.2f"),
                   "as_of": "As of", "source_link": st.column_config.LinkColumn("Source", display_text="list")},
               row_height=60, height=420)
    t12 = top.head(12)
    nin = (t12["pub"] == "Nintendo").sum()
    takeaway(f"<b>Insight:</b> {nin} of the 12 biggest hits since 2019 are Nintendo games on Nintendo machines, and "
             f"most of the list are new entries in long-running series (Mario, Pokémon, Zelda, Animal Crossing). "
             f"Click 'list' in any row to see the publisher figure behind it.")
    source(SRC_HITS)


# --- 9. Japan Since 2019 ------------------------------------------------------------------------------------------
@st.fragment
def japan_section():
    section("The digital era", "Japan Since 2019",
            "Japan's store sales are tracked every week by Famitsu, so for Japan we can still see almost every game "
            "that sold, not just the biggest hits. Boxed copies only: downloads are not included.")
    if JAPAN.empty:
        st.info("The Japan data isn't built yet (run enrich/build_extended.py).")
        return
    j = JAPAN.copy()
    fam = j.groupby("family")["units_m"].sum()
    fam = fam / fam.sum()
    top = j.loc[j["units_m"].idxmax()]
    kpis([("Games charted", f"{len(j):,}", "Games released 2019 or later that reached Famitsu's weekly top 30."),
          ("Copies sold in Japan", units_fmt(j["units_m"].sum()), "Boxed copies those games sold in Japanese stores."),
          ("Nintendo's share", pct(fam.get("Nintendo", 0)), "Share of those copies sold for Nintendo consoles."),
          ("Biggest seller", top["title"], f"{units_fmt(top['units_m'])} boxed copies in Japan.")])

    py = j.groupby(["release_year", "platform"])["units_m"].sum().reset_index()
    py["Share"] = py["units_m"] / py.groupby("release_year")["units_m"].transform("sum")
    py["Console"] = py["platform"].map(lambda p: PLATFORM_NAME.get(p, p))
    py = py.rename(columns={"release_year": "Year", "units_m": "Units"})
    plats = [p for p in ["NS", "NS2", "PS4", "PS5", "XS"] if p in set(py["platform"])]
    other = sorted(set(py["platform"]) - set(plats))
    order = [PLATFORM_NAME.get(p, p) for p in plats + other]
    rng = [PLATFORM_COLOR.get(p, SILVER) for p in plats] + [SILVER] * len(other)
    ns_share = py[py["platform"] == "NS"].set_index("Year")["Share"]
    title = (f"The Switch took {pct(ns_share.iloc[0])} of Japan's game sales for {int(ns_share.index[0])} releases"
             + (f" and still {pct(ns_share.iloc[-1])} in {int(ns_share.index[-1])}" if len(ns_share) > 1 else ""))

    console_color = dict(zip(order, rng))

    def build():
        xax = alt.X("Year:O", title=None, axis=alt.Axis(labelAngle=0))
        bars = alt.Chart(py).mark_bar(stroke="white", strokeWidth=0.6).encode(
            x=xax,
            y=alt.Y("Share:Q", stack="normalize", title="Share of boxed copies sold", axis=alt.Axis(format="%")),
            color=alt.Color("Console:N", sort=order, title=None, scale=alt.Scale(domain=order, range=rng)),
            order=alt.Order("o:Q"),
            tooltip=[alt.Tooltip("Year:O"), "Console:N", alt.Tooltip("Share:Q", format=".0%"),
                     alt.Tooltip("Units:Q", format=",.2f", title="Copies (M)")]
        ).transform_calculate(o=f"indexof({json.dumps(order)}, datum.Console)")
        lab = stack_labels(py, "Year", "Console", "Share", order, console_color, xax)
        return (bars + lab).properties(height=320)
    show_chart(build, title, "Share of each release year's boxed copies sold in Japan, by console")
    source(SRC_JP, "Each year counts the lifetime sales of the games released that year; games released recently "
                   "are still selling. Famitsu tracks the weekly top 30, so games that never charted are missing.")

    pubs = j.groupby("pub")["units_m"].sum().sort_values(ascending=False).head(12)
    d = pubs.rename_axis("Publisher").reset_index(name="Units")
    exhibit_head(f"{d.iloc[0]['Publisher']} sold {pct(pubs.iloc[0] / j['units_m'].sum())} of boxed games in Japan "
                 f"since 2019", "Boxed copies sold in Japan of games released 2019 or later, by publisher (millions)")
    show_chart(lambda: hbar(d, "Publisher", "Units", ",.1f", "Copies sold in Japan (millions)",
                            highlight=[d.iloc[0]["Publisher"]], logos=True))
    source(SRC_JP)

    exhibit("Japan's 12 best-selling games since 2019", "Boxed copies sold in Japan")
    jt = j.sort_values("units_m", ascending=False)
    covers(jt, "title", lambda r: f"{units_fmt(r.units_m)} · {r.platform_name}", n=12)
    sw = jt.head(12)["family"].eq("Nintendo").sum()
    takeaway(f"<b>Insight:</b> {sw} of Japan's 12 best-selling games since 2019 are on Nintendo machines. Japan "
             f"still buys boxed copies in large numbers, and it buys them mostly for the Switch: the top seller, "
             f"{jt.iloc[0]['title']}, sold {units_fmt(jt.iloc[0]['units_m'])} boxed copies in Japan alone.")
    source(SRC_JP)


# --- 10. PC & Steam -----------------------------------------------------------------------------------------------
OWNER_BANDS = ["Under 50K", "50K–200K", "200K–1M", "1M–5M", "5M+"]


@st.fragment
def steam_section():
    section("The digital era", "PC & Steam",
            "PC games are sold almost entirely as downloads, mostly on Steam, so the store data above barely sees "
            "them. Steam doesn't publish sales, but two public signals give estimates: **SteamSpy's owner ranges** "
            "and the number of **player reviews** (a common rule: each review stands for about 30–60 copies).")
    if STEAM.empty:
        st.info("The Steam data isn't built yet (run enrich/build_extended.py).")
        return
    s = STEAM.copy()
    s["Owners"] = pd.cut(s["owners_low"].fillna(0), [-1, 49_999, 199_999, 999_999, 4_999_999, 1e12],
                         labels=OWNER_BANDS).astype(str)
    big = (s["owners_low"].fillna(0) >= 1_000_000)
    free = s["price_usd"].fillna(-1) == 0
    kpis([("PC games tracked", f"{len(s):,}", "Steam games released 2018 or later with SteamSpy estimates."),
          ("Games with 1M+ owners", f"{big.sum():,}", "Games SteamSpy places at 1 million owners or more."),
          ("Free to play", pct(free.mean()), "Share of these games that cost nothing to download."),
          ("Typical price", f"${median(s.loc[~free, 'price_usd']):.0f}", "Typical price of the paid games, in US dollars.")])

    yr = s.groupby(["release_year", "Owners"]).size().reset_index(name="Games").rename(columns={"release_year": "Year"})
    by_year = s[big].groupby("release_year").size()
    title = (f"About {by_year.median():.0f} new PC games a year reach a million Steam owners"
             if len(by_year) else "PC games by estimated owners")
    rng = [SILVER, SKY, BLUE, NAVY, AMBER]

    shown = yr[yr["Owners"] != "Under 50K"]
    tot = shown.groupby("Year")["Games"].sum().reset_index()

    def build():
        bars = alt.Chart(shown).mark_bar(stroke="white", strokeWidth=0.6).encode(
            x=alt.X("Year:O", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Games:Q", title="Games"),
            color=alt.Color("Owners:N", sort=OWNER_BANDS[1:], title="Estimated owners",
                            scale=alt.Scale(domain=OWNER_BANDS[1:], range=rng[1:])),
            order=alt.Order("o:Q"),
            tooltip=[alt.Tooltip("Year:O"), "Owners:N", "Games:Q"]
        ).transform_calculate(o=f"indexof({json.dumps(OWNER_BANDS)}, datum.Owners)")
        lab = alt.Chart(tot).mark_text(dy=-7, fontSize=10, color=INK).encode(x="Year:O", y="Games:Q",
                                                                             text="Games:Q")
        return (bars + lab).properties(height=310)
    show_chart(build, title, "Steam games released each year with 50,000+ estimated owners, by owner range")
    source(SRC_STEAM, "Owner ranges are SteamSpy estimates: free weekends and giveaways inflate them, and recent "
                      "games are still adding owners. Only games with some following on IGDB or in SteamSpy's top "
                      "list are covered, so the count of small games is incomplete.")

    s["Price band"] = pd.cut(s["price_usd"], [-0.01, 0.001, 9.99, 19.99, 39.99, 1000],
                             labels=["Free", "Under $10", "$10–20", "$20–40", "$40+"]).astype(str)
    pb = s[s["Price band"] != "nan"].groupby("Price band").agg(
        Hit=("owners_low", lambda x: (x.fillna(0) >= 1_000_000).mean()), n=("appid", "size")).reset_index()
    order = ["Free", "Under $10", "$10–20", "$20–40", "$40+"]
    best = pb.loc[pb["Hit"].idxmax()]
    exhibit_head(f"{best['Price band']} games are the most likely to reach a million Steam owners "
                 f"({pct(best['Hit'])})", "Share of games with 1 million or more estimated owners, by current price")

    def build():
        base = alt.Chart(pb).encode(x=alt.X("Price band:N", sort=order, title="Current price on Steam",
                                            axis=alt.Axis(labelAngle=0)))
        bars = base.mark_bar(color=NAVY, width={"band": 0.66}).encode(
            y=alt.Y("Hit:Q", title="Share with 1M+ owners", axis=alt.Axis(format="%")),
            tooltip=["Price band:N", alt.Tooltip("Hit:Q", format=".0%", title="Share with 1M+ owners"),
                     alt.Tooltip("n:Q", title="Games")])
        lab = base.mark_text(dy=-8, fontSize=11, color=INK).encode(y="Hit:Q", text=alt.Text("Hit:Q", format=".0%"))
        return (bars + lab).properties(height=270)
    show_chart(build)
    source(SRC_STEAM, "Free games are easy to claim, so 'owners' overstates how many people play them. Prices are "
                      "today's, not launch prices. The games covered are ones with a following, so these shares are "
                      "much higher than for all Steam games. " + NOTE["assoc"])

    exhibit("The most-reviewed PC games released since 2018",
            "Estimated copies = player reviews × 30 to 60; SteamSpy's owner range alongside")
    t = s.sort_values("reviews", ascending=False)
    covers(t, "title", lambda r: f"{r.reviews / 1e3:,.0f}K reviews · {r.release_year}", n=12)
    tt = with_cover_url(t.head(40)).assign(est=lambda x: x["est_low_m"].map(lambda v: f"{v:,.1f}")
                                           + "–" + x["est_high_m"].map(lambda v: f"{v:,.1f}M"),
                                           owners=lambda x: x["owners_low"].map(lambda v: units_fmt(v / 1e6))
                                           + "–" + x["owners_high"].map(lambda v: units_fmt(v / 1e6)))
    show_table(tt[["cover", "title", "release_year", "publisher", "reviews", "positive_share", "est", "owners",
                   "price_usd"]], column_config={
        "cover": cover_col(), "title": st.column_config.TextColumn("Game", width="medium"),
        "release_year": st.column_config.NumberColumn("Year", format="%d"), "publisher": "Publisher",
        "reviews": st.column_config.NumberColumn("Steam reviews", format="%d"),
        "positive_share": st.column_config.NumberColumn("Positive reviews", format="percent",
                                                        help="Share of Steam reviews that recommend the game."),
        "est": st.column_config.TextColumn("Estimated copies", help=define("reviews")),
        "owners": st.column_config.TextColumn("SteamSpy owners", help=define("owners")),
        "price_usd": st.column_config.NumberColumn("Price ($)", format="%.2f")}, row_height=60, height=420)
    t20 = t.head(20)
    takeaway(f"<b>Insight:</b> {(t20['price_usd'].fillna(0) == 0).sum()} of the 20 most-reviewed PC games since "
             f"2018 are free to play, and many of the rest come from small studios rather than the big console "
             f"publishers: PC is where independent hits break out. Treat the copy estimates as rough ranges.")
    source(SRC_STEAM)


# --- 11. Pitch a Game -----------------------------------------------------------------------------------------------
def comparables(genre, platform, pub, fu, critic, k=8):
    """Closest past games: same genre and console maker, released 2005+, ranked by console, sequel status,
    publisher, critic score and recency."""
    fam = GAMES.loc[GAMES["platform"] == platform, "family"].iat[0]
    pool = GAMES[(GAMES["genre"] == genre) & (GAMES["family"] == fam) & (GAMES["year"] >= 2005)]
    dist = ((pool["platform"] != platform) * 1.0 + (pool["follow_up"] != fu) * 1.0
            + (pool["pub_group"] != pub) * 0.7 + (YEAR_MAX - pool["year"]) / 8)
    if critic is not None:
        dist = dist + (pool["critic_score"] - critic).abs().fillna(2) / 2
    return pool.loc[dist.nsmallest(k).index]


@st.fragment
def pitch_section():
    section("Decide", "Pitch a Game",
            f"**How it works:** describe a game you'd fund. A model that learned from games released {MODEL_FROM}–"
            f"{YEAR_MAX} predicts its sales from choices a publisher makes before launch. Real games missed those "
            "predictions by a known amount, so you get a **range** and a **chance of a million seller**, not a "
            "single number.")
    c1, c2, c3 = st.columns(3)
    genre = c1.selectbox("Genre", GENRE_ORDER, index=GENRE_ORDER.index("Shooter"), key="pitch_genre")
    platform = c2.selectbox("Console", PITCH_PLATFORMS, index=PITCH_PLATFORMS.index("PS4"),
                            format_func=lambda p: PLATFORM_NAME.get(p, p), key="pitch_platform")
    pub = c3.selectbox("Publisher", PUBS, index=PUBS.index("Ubisoft"), key="pitch_pub", help=define("publisher"))
    c4, c5 = st.columns(2)
    kind = c4.radio("Original or sequel", ["Original", "Follow-up"], horizontal=True, key="pitch_kind",
                    help=define("follow-up"))
    crit = c5.select_slider("Critic score", ["No score yet", 6, 7, 8, 9], value="No score yet", key="pitch_critic",
                            help="Leave at 'No score yet' for a funding decision; pick a score to see what reviews "
                                 "add.")
    fu = 1 if kind == "Follow-up" else 0
    critic = None if crit == "No score yet" else float(crit)
    sel = PITCH[(PITCH["genre"] == genre) & (PITCH["platform"] == platform) & (PITCH["pub_group"] == pub)
                & (PITCH["follow_up"] == fu)]
    sel = sel[sel["critic_score"].isna()] if critic is None else sel[sel["critic_score"] == critic]
    if sel.empty:
        st.info("No prediction for that combination.")
        return
    r = sel.iloc[0]
    kpis([("Predicted sales", units_fmt(r["median"]), "What a typical game with these choices sold."),
          ("Likely range", f"{units_fmt(r['p25'])}–{units_fmt(r['p75'])}", "Half of similar games landed in here."),
          ("Bad case to great case", f"{units_fmt(r['p10'])}–{units_fmt(r['p90'])}",
           "Only 1 game in 10 did worse than the low end, and 1 in 10 did better than the high end."),
          ("Chance of a million seller", pct(r["p_hit"]), "How often games like this sold 1 million copies or more.")])
    who = "an independent or smaller publisher" if pub == "Other" else pub
    sc = pd.DataFrame([{"Case": "Bad case (1 in 10 do worse)", "Units": r["p10"]},
                       {"Case": "Weak (1 in 4)", "Units": r["p25"]}, {"Case": "Typical", "Units": r["median"]},
                       {"Case": "Strong (1 in 4)", "Units": r["p75"]},
                       {"Case": "Great case (1 in 10 do better)", "Units": r["p90"]}])
    reach = ("even the weak case clears a million" if r["p25"] >= 1 else "the typical case clears a million"
             if r["median"] >= 1 else "only the strong case clears a million" if r["p75"] >= 1
             else "only the great case clears a million" if r["p90"] >= 1 else "even the great case falls short "
                                                                                 "of a million")
    art = "An" if kind == "Original" else "A"
    title = (f"{art} {kind.lower()} {genre.lower()} game on {PLATFORM_NAME.get(platform, platform)} from {who}: "
             f"{pct(r['p_hit'])} chance of a million seller; {reach}")

    def build():
        order = list(sc["Case"])
        base = alt.Chart(sc).encode(x=alt.X("Case:N", sort=order, title=None,
                                            axis=alt.Axis(labelAngle=0, labelLimit=160)))
        bars = base.mark_bar(width={"band": 0.6}).encode(
            y=alt.Y("Units:Q", title="Copies sold (millions)"),
            color=alt.condition(f"datum.Units >= {HIT_UNITS}", alt.value(BLUE), alt.value(SILVER)),
            tooltip=["Case", alt.Tooltip("Units:Q", format=",.2f", title="Copies (M)")])
        lab = base.mark_text(fontSize=11, color=INK, dy=-8).encode(y="Units:Q", text=alt.Text("Units:Q", format=".2f"))
        rule = alt.Chart(pd.DataFrame({"y": [HIT_UNITS]})).mark_rule(color=NAVY, strokeDash=[4, 3]).encode(y="y:Q")
        return (bars + lab + rule).properties(height=300)
    show_chart(build, title, "Predicted copies sold across the range of outcomes (dashed line = 1 million; "
                             "blue = clears it)")
    note(13, 14, "assoc")

    left, right = st.columns([3, 2])
    with left:
        exhibit("Similar past games", "Same genre and console maker, closest console, sequel status, publisher "
                                      "and year")
        cmp = with_cover_url(comparables(genre, platform, pub, fu, critic))
        show_table(cmp[["cover", "title", "platform", "year", "pub", "kind", "critic_score", "units"]], column_config={
            "cover": cover_col(), "title": st.column_config.TextColumn("Game", width="medium"), "platform": "Console",
            "year": st.column_config.NumberColumn("Year", format="%d"), "pub": "Publisher",
            "kind": "Original / follow-up", "critic_score": st.column_config.NumberColumn("Critic", format="%.1f"),
            "units": st.column_config.NumberColumn("Copies sold (M)", format="%.2f")}, row_height=60)
        takeaway(f"<b>Insight:</b> {int((cmp['units'] >= 1).sum())} of these {len(cmp)} similar games sold a million; "
                 f"the typical one sold {units_fmt(median(cmp['units']))}.")
    with right:
        exhibit("The same pitch on every console", "Everything else held at your choices")
        same = PITCH[(PITCH["genre"] == genre) & (PITCH["pub_group"] == pub) & (PITCH["follow_up"] == fu)]
        same = same[same["critic_score"].isna()] if critic is None else same[same["critic_score"] == critic]
        same = same.assign(Console=same["platform"].map(lambda p: PLATFORM_NAME.get(p, p)))
        show_table(same.sort_values("median", ascending=False)[["Console", "median", "p_hit"]], height=300,
                   column_config={"median": st.column_config.NumberColumn("Predicted copies (M)", format="%.2f"),
                                  "p_hit": st.column_config.NumberColumn("Chance of a million", format="percent")})
        best = same.sort_values("median", ascending=False).iloc[0]
        takeaway(f"<b>Insight:</b> the same pitch does best on {best['Console']} "
                 f"({units_fmt(best['median'])} predicted). Older consoles rank high partly because their games "
                 f"were sold on discs that VGChartz could count.")


# --- 12. Predict the Sales ------------------------------------------------------------------------------------------
FEATURE_NAME = {"follow_up": "Original or sequel", "year": "Release year", "genre": "Genre",
                "platform": "Console", "pub_group": "Publisher", "critic_score": "Critic score"}
SET_NAME = {"Greenlight": "Before launch", "Greenlight + critic score": "Before launch + critic score"}
MODEL_NAME = {"Linear regression": "Simple model (straight-line)", "Random forest": "Flexible model (random forest)"}


def predict_section():
    section("Models", "Predict the Sales",
            "How much of a game's sales can you predict from what is known before launch, and how much do reviews "
            "add? Two models learned from past games and were tested on games they had never seen.")
    recs = []
    for fs, e in MODELS.items():
        for m, folds in e["cv"].items():
            recs.append({"Data": f"{SET_NAME.get(fs, fs)} ({e['n']:,} games)", "Model": MODEL_NAME.get(m, m),
                         "Explained": float(np.mean(folds)), "Low": float(np.min(folds)), "High": float(np.max(folds))})
    d = pd.DataFrame(recs)
    rf = d[d["Model"] == MODEL_NAME["Random forest"]]
    before, after = rf.iloc[0]["Explained"], rf.iloc[-1]["Explained"]
    kpis([("Predictable before launch", pct(before),
           "Share of the differences in sales between games the flexible model predicts from pre-launch choices."),
          ("With critic scores", pct(after), "The same once reviews are in (games with a critic score)."),
          ("Left unexplained", pct(1 - before), "Execution, marketing, competition and luck: what no data here "
                                                "captures before launch."),
          ("Games tested", f"{MODELS['Greenlight']['n']:,}", "Each model was graded on games it hadn't seen.")])
    title = (f"Before launch the data predicts about {pct(before)} of the differences in sales; with reviews, "
             f"{pct(after)}")
    data_order = list(dict.fromkeys(d["Data"]))

    def build():
        models = list(MODEL_NAME.values())
        base = alt.Chart(d).encode(x=alt.X("Data:N", sort=data_order, title=None,
                                           axis=alt.Axis(labelAngle=0, labelLimit=280)),
                                   xOffset=alt.XOffset("Model:N", sort=models))
        bars = base.mark_bar().encode(
            y=alt.Y("Explained:Q", title="Share of sales differences predicted", axis=alt.Axis(format="%"),
                    scale=alt.Scale(domain=[0, 0.6])),
            color=alt.Color("Model:N", sort=models, title=None, scale=alt.Scale(domain=models, range=[SILVER, NAVY])),
            tooltip=["Data:N", "Model:N", alt.Tooltip("Explained:Q", format=".0%", title="Predicted"),
                     alt.Tooltip("Low:Q", format=".0%", title="Worst test round"),
                     alt.Tooltip("High:Q", format=".0%", title="Best test round")])
        err = base.mark_rule(color=BLUE, strokeWidth=1.6).encode(y="Low:Q", y2="High:Q")
        lab = base.mark_text(dy=-10, fontSize=11, color=INK).encode(y="High:Q", text=alt.Text("Explained:Q",
                                                                                              format=".0%"))
        return (bars + err + lab).properties(height=300)
    show_chart(build, title, "Share of the differences in sales the models predict for games they never saw "
                             "(bar = average of 5 test rounds; blue line = worst to best round)")
    note(13, 12)

    fs = st.radio("Which model", list(MODELS), horizontal=True, key="imp_set", format_func=lambda k: SET_NAME.get(k, k))
    imp = pd.DataFrame([{"Factor": FEATURE_NAME.get(k, k), "Importance": v}
                        for k, v in MODELS[fs]["importance"].items()]).sort_values("Importance", ascending=False)
    top = imp.iloc[0]
    show_chart(lambda: hbar(imp, "Factor", "Importance", ".2f", "How much accuracy drops without this factor",
                            highlight=[top["Factor"]]),
               f"{top['Factor']} is the factor the model leans on most ({SET_NAME.get(fs, fs).lower()})",
               "How much the flexible model relies on each factor")
    note(13, "assoc")
    st.caption("This says how much the model leans on a factor, not whether it raises or lowers sales, and not "
               "that changing it would change sales.")


# --- 13. Game Database ----------------------------------------------------------------------------------------------
@st.fragment
def database_section():
    section("Games", "Game Database",
            "**How it works:** filter the games, then sort any column by clicking its header.")
    c1, c2, c3 = st.columns(3)
    query = c1.text_input("Search title, developer or publisher", placeholder="e.g. Zelda, Rockstar, Ubisoft")
    fams = c2.multiselect("Console maker", FAMILY_ORDER, placeholder="All consoles")
    pubs = c3.multiselect("Publisher", PUBS, placeholder="All publishers")
    c4, c5, c6 = st.columns(3)
    genres = c4.multiselect("Genre", GENRES, placeholder="All genres")
    years = c5.slider("Release year", YEAR_MIN, YEAR_MAX, (YEAR_MIN, YEAR_MAX))
    kind = c6.radio("Original or sequel", ["All", "Original", "Follow-up"], horizontal=True, help=define("follow-up"))
    v = GAMES
    if query:
        q = query.lower()
        v = v[v["title"].str.lower().str.contains(q, regex=False)
              | v["developer"].fillna("").str.lower().str.contains(q, regex=False)
              | v["publisher"].fillna("").str.lower().str.contains(q, regex=False)
              | v["pub"].fillna("").str.lower().str.contains(q, regex=False)]
    if fams:
        v = v[v["family"].isin(fams)]
    if pubs:
        v = v[v["pub_group"].isin(pubs)]
    if genres:
        v = v[v["genre"].isin(genres)]
    if kind != "All":
        v = v[v["kind"] == kind]
    v = with_cover_url(v[v["year"].between(*years)].sort_values("units", ascending=False).head(500))
    exhibit(f"{len(v):,} games shown", "The 500 best sellers that match, sorted by copies sold")
    show_table(v[["cover", "title", "platform", "year", "pub", "genre", "kind", "esrb", "critic_score", "user_rating",
                  "na_sales", "eu_sales", "jp_sales", "other_sales", "units"]], height=520, row_height=60,
               column_config={
                   "cover": cover_col(), "title": st.column_config.TextColumn("Title", width="medium"),
                   "platform": "Console", "year": st.column_config.NumberColumn("Year", format="%d"),
                   "pub": "Publisher", "genre": "Genre", "kind": "Original / follow-up", "esrb": "ESRB",
                   "critic_score": st.column_config.NumberColumn("Critic", format="%.1f"),
                   "user_rating": st.column_config.NumberColumn("Player rating", format="%.0f"),
                   "na_sales": st.column_config.NumberColumn("North America (M)", format="%.2f"),
                   "eu_sales": st.column_config.NumberColumn("Europe (M)", format="%.2f"),
                   "jp_sales": st.column_config.NumberColumn("Japan (M)", format="%.2f"),
                   "other_sales": st.column_config.NumberColumn("Rest of world (M)", format="%.2f"),
                   "units": st.column_config.NumberColumn("Copies sold (M)", format="%.2f")})
    if len(v):
        takeaway(f"<b>Insight:</b> of the games shown, {pct((v['units'] >= 1).mean())} sold a million copies; the "
                 f"top seller is {v.iloc[0]['title']} ({units_fmt(v.iloc[0]['units'])}).")
    source(SRC_VGC + "; covers, age ratings and player ratings from IGDB", NOTE[4] + " " + NOTE[1])


# --- 14. Econometrics -------------------------------------------------------------------------------------------------
# Five standard analyses on the same data, each a plain least-squares regression (numpy, computed once per server).
# Standard errors are heteroskedasticity-robust (HC1); 95% intervals = estimate ± 1.96 SE. All are associations.
def ols(y, X):
    """OLS with HC1 robust standard errors. X is a DataFrame (include a constant if wanted)."""
    Xv, yv = X.to_numpy(dtype=float), np.asarray(y, dtype=float)
    beta, *_ = np.linalg.lstsq(Xv, yv, rcond=None)
    e = yv - Xv @ beta
    n, k = Xv.shape
    inv = np.linalg.pinv(Xv.T @ Xv)
    cov = inv @ (Xv.T * e ** 2) @ Xv @ inv * n / max(n - k, 1)
    r2 = 1 - (e ** 2).sum() / ((yv - yv.mean()) ** 2).sum()
    return pd.DataFrame({"term": X.columns, "b": beta, "se": np.sqrt(np.clip(np.diag(cov), 0, None))}), r2, n


def within(df, cols, group):
    """Demean columns within groups (fixed effects by the within transformation)."""
    return df[cols] - df.groupby(group)[cols].transform("mean")


def pct_ci(r):
    """Coefficient on log sales -> % difference with a 95% interval."""
    return r.assign(Effect=np.exp(r["b"]) - 1, Lo=np.exp(r["b"] - 1.96 * r["se"]) - 1,
                    Hi=np.exp(r["b"] + 1.96 * r["se"]) - 1)


def ci_dots(d, cat, order, xtitle, fmt=".0%", ref_label=None):
    """Horizontal estimate-and-interval chart with the estimate printed beside each dot."""
    def build():
        base = alt.Chart(d).encode(y=alt.Y(f"{cat}:N", sort=order, title=None, axis=alt.Axis(labelColor=INK,
                                                                                             labelLimit=240)))
        rule = base.mark_rule(color=SLATE, strokeWidth=1.6).encode(x=alt.X("Lo:Q", title=xtitle,
                                                                            axis=alt.Axis(format=fmt)), x2="Hi:Q")
        dot = base.mark_circle(size=80, opacity=1).encode(
            x="Effect:Q", color=alt.condition("datum.Effect >= 0", alt.value(BLUE), alt.value(NAVY)),
            tooltip=[f"{cat}:N", alt.Tooltip("Effect:Q", format=fmt, title="Estimate"),
                     alt.Tooltip("Lo:Q", format=fmt, title="95% low"), alt.Tooltip("Hi:Q", format=fmt, title="95% high")])
        lab = base.mark_text(align="left", dx=8, dy=-8, fontSize=10, color=INK).encode(
            x="Effect:Q", text=alt.Text("Effect:Q", format="+" + fmt))
        zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=RULE, strokeDash=[3, 3]).encode(x="x:Q")
        return (zero + rule + dot + lab).properties(height=max(160, 26 * len(order)))
    return build


@st.cache_resource(show_spinner=False)
def econ_results():
    out = {}
    # 1. Franchise decay with series fixed effects
    t = franchise_titles()
    t = t[t["First"] >= FIRST_MIN].copy()
    t["ly"] = np.log(t["Units"].clip(lower=0.005))
    t["n"] = t["Entry"].clip(upper=8)
    dums = pd.get_dummies(t["n"].astype(int), prefix="g", dtype=float).drop(columns="g_1", errors="ignore")
    X = within(pd.concat([t[["series"]], dums], axis=1), list(dums.columns), "series")
    y = t["ly"] - t.groupby("series")["ly"].transform("mean")
    r, r2, n = ols(y, X)
    r = pct_ci(r)
    r["Game"] = r["term"].str.replace("g_", "Game ").str.replace("Game 8", "Game 8+")
    out["decay"] = (r, n, t["series"].nunique())
    # 3. Concentration: Lorenz-style shares and publisher HHI by year
    g = GAMES[GAMES["year"] >= MODEL_FROM]
    srt = g["units"].sort_values(ascending=False).to_numpy()
    cum = srt.cumsum() / srt.sum()
    pts = [0.01, 0.05, 0.10, 0.20, 0.50]
    lor = pd.DataFrame({"Top": [f"Top {int(p * 100)}%" for p in pts],
                        "Share": [cum[max(int(len(srt) * p) - 1, 0)] for p in pts], "p": pts})
    curve = pd.DataFrame({"Games": np.linspace(0, 1, 101)})
    curve["Copies"] = [0.0] + [cum[max(int(len(srt) * q) - 1, 0)] for q in curve["Games"][1:]]
    sh = g.groupby(["year", "pub"])["units"].sum()
    sh = sh / sh.groupby(level=0).transform("sum")
    hhi = (sh ** 2).groupby(level=0).sum().mul(10000).rename("HHI").reset_index().rename(columns={"year": "Year"})
    out["conc"] = (lor, curve, hhi)
    # 4. Hedonic regression with year and console fixed effects (releases MODEL_FROM..YEAR_MAX, main platforms)
    h = g[g["platform"] != "Other"].copy()
    h["ly"] = np.log(h["units"].clip(lower=0.005))
    gen = pd.get_dummies(h["genre"], dtype=float).drop(columns="Action")
    pub = pd.get_dummies(h["pub_group"], dtype=float).drop(columns="Other")
    Xh = pd.concat([gen.add_prefix("Genre: "), pub.add_prefix("Publisher: "),
                    h[["follow_up"]].rename(columns={"follow_up": "Sequel or follow-up"}).astype(float),
                    h[["year", "platform"]]], axis=1)
    keys = h["year"].astype(str) + "|" + h["platform"]
    cols = [c for c in Xh.columns if c not in ("year", "platform")]
    Xw = within(Xh.assign(k=keys), cols, "k")
    yw = h["ly"] - h.groupby(keys)["ly"].transform("mean")
    r, r2, n = ols(yw, Xw)
    out["hedonic"] = (pct_ci(r), r2, n)
    # 5. Launch month vs. January, within the same year and console
    m = GAMES[GAMES["month"].notna() & (GAMES["year"] >= MODEL_FROM)].copy()
    m["ly"] = np.log(m["units"].clip(lower=0.005))
    mon = pd.get_dummies(m["month"].astype(int).map(lambda k: MONTHS[k - 1]), dtype=float).drop(columns="Jan")
    mon = mon[[c for c in MONTHS if c in mon]]
    keys = m["year"].astype(str) + "|" + m["platform"]
    Xm = within(pd.concat([mon, keys.rename("k")], axis=1), list(mon.columns), "k")
    ym = m["ly"] - m.groupby(keys)["ly"].transform("mean")
    r, r2, n = ols(ym, Xm)
    r = pct_ci(r)
    m["holiday"] = (m["month"] >= 10).astype(float)
    Xq = within(pd.concat([m[["holiday"]], keys.rename("k")], axis=1), ["holiday"], "k")
    rq, _, _ = ols(ym, Xq)
    out["months"] = (r, pct_ci(rq).iloc[0], n)
    # 2. Front-loading in Japan's weekly charts
    c = CURVES.copy()
    if len(c):
        w1 = c[c["week"] == 1].set_index("game_id")["cum_share"]
        games = c.drop_duplicates("game_id").set_index("game_id")
        games["w1"] = w1
        games = games.dropna(subset=["w1"])
        games["fu"] = (games["kind"] == "Follow-up").astype(float)
        gk = games["release_year"].astype(str) + "|" + games["platform"]
        Xf = within(pd.concat([games[["fu"]], gk.rename("k")], axis=1), ["fu"], "k")
        yf = games["w1"] - games.groupby(gk)["w1"].transform("mean")
        rf_, _, nf = ols(yf, Xf)
        avg = c[c["week"].isin([1, 2, 3, 4, 6, 8, 12, 16, 20, 26])].groupby(["kind", "week"])["cum_share"].mean()
        out["japan"] = (games, rf_.iloc[0], nf, avg.reset_index())
    return out


def econ_section():
    section("Methods", "Econometrics",
            "Five standard analyses that go one step past the charts above. Each is an ordinary least-squares "
            "regression on log sales, so results read as **% differences**. Bars show 95% intervals: if an interval "
            "crosses zero, the data can't tell the difference from no difference. All are **associations**: they "
            "compare like with like more carefully, but they do not prove that a choice causes sales.")
    E = econ_results()

    # 14.1 Franchise decay
    r, n, ns = E["decay"]
    g2 = r[r["Game"] == "Game 2"].iloc[0]
    title = (f"Within the same series, the second game sells {abs(g2['Effect']) * 100:.0f}% "
             f"{'less' if g2['Effect'] < 0 else 'more'} than the first, and later games keep sliding")
    show_chart(ci_dots(r, "Game", list(r["Game"]), "Sales vs. the series' first game"), title,
               "Franchise decay: each later game's sales vs. the first game of the same series (series fixed effects)")
    source(SRC_VGC, f"Method: regression of log copies sold on game number with a fixed effect for each series "
                    f"({ns:,} series, {n:,} games), so each sequel is compared only with its own series and big "
                    f"series don't drive the result. Reads as: the typical Game 2 sells this % more or less than "
                    f"Game 1 of the same series. VGChartz undercounts downloads, which grew over time, so later games "
                    f"are understated and the decay is likely overstated. " + NOTE[11])

    # 14.2 Front-loading in Japan
    if "japan" in E:
        games, rf_, nf, avg = E["japan"]
        med = games.groupby("kind")["w1"].median()
        kpis([("Week-1 share, follow-ups", pct(med.get("Follow-up")), "Typical share of a sequel's lifetime Japan "
                                                                      "sales made in its first week."),
              ("Week-1 share, originals", pct(med.get("Original")), "The same for new games."),
              ("Difference, like for like", f"{rf_['b'] * 100:+.0f} pts",
               f"Follow-ups vs. originals released the same year on the same console (95% interval "
               f"{(rf_['b'] - 1.96 * rf_['se']) * 100:+.0f} to {(rf_['b'] + 1.96 * rf_['se']) * 100:+.0f})."),
              ("Games analyzed", f"{nf:,}", "Games that debuted in Famitsu's chart from mid-2019 on.")])
        avg["Label"] = avg["cum_share"].map(lambda v: f"{v:.0%}")
        lo, hi = rf_["b"] - 1.96 * rf_["se"], rf_["b"] + 1.96 * rf_["se"]
        verdict = ("Sequels are more front-loaded" if lo > 0 else "Originals are more front-loaded" if hi < 0
                   else "Sequels and originals are about equally front-loaded")
        title = (f"{verdict}: typical week-one share {pct(med.get('Follow-up'))} for follow-ups vs. "
                 f"{pct(med.get('Original'))} for originals in Japan")

        def build():
            base = alt.Chart(avg).encode(
                x=alt.X("week:Q", title="Weeks since launch", axis=alt.Axis(values=[1, 4, 8, 12, 16, 20, 26])),
                y=alt.Y("cum_share:Q", title="Share of lifetime sales made so far", axis=alt.Axis(format="%"),
                        scale=alt.Scale(domain=[0, 1])),
                color=alt.Color("kind:N", title=None, scale=alt.Scale(domain=["Follow-up", "Original"],
                                                                     range=[NAVY, BLUE])))
            line = base.mark_line(strokeWidth=2.4, point=line_points())
            lab = base.mark_text(dy=-10, fontSize=10).encode(text="Label:N")
            return (line + lab).properties(height=300)
        show_chart(build, title, "Front-loading: average share of a game's lifetime Japan sales reached by each "
                                 "week after launch")
        source(SRC_JP, "Method: each game's cumulative sales divided by its latest lifetime total, week by week; the "
                       "like-for-like difference is a regression of week-1 share on a follow-up flag with "
                       "release-year × console fixed effects. Boxed copies in Japan only, games that reached the "
                       "weekly top 30. A game's total stops updating once it drops out of the top 30, so small games look more "
                       "front-loaded than they are. A front-loaded launch is the games version of a movie's steep "
                       "week-2 drop.")

    # 14.3 Concentration
    lor, curve, hhi = E["conc"]
    top1 = lor.iloc[0]["Share"]
    title = f"Blockbuster economics: the top 1% of games sold {pct(top1)} of all copies, the top 10% sold {pct(lor.iloc[2]['Share'])}"

    def build():
        base = alt.Chart(curve).encode(x=alt.X("Games:Q", title="Share of games (best sellers first)",
                                               axis=alt.Axis(format="%")),
                                       y=alt.Y("Copies:Q", title="Share of copies sold", axis=alt.Axis(format="%")))
        line = base.mark_line(color=NAVY, strokeWidth=2.4)
        eq = alt.Chart(pd.DataFrame({"Games": [0, 1], "Copies": [0, 1]})).mark_line(
            color=RULE, strokeDash=[4, 3]).encode(x="Games:Q", y="Copies:Q")
        pts = alt.Chart(lor).encode(x="p:Q", y="Share:Q")
        dots = pts.mark_circle(color=BLUE, size=70, opacity=1)
        lab = pts.mark_text(align="left", dx=8, dy=8, fontSize=10, color=INK).encode(
            text=alt.Text("label:N")).transform_calculate(label="datum.Top + ': ' + format(datum.Share, '.0%')")
        return (eq + line + dots + lab).properties(height=300)
    show_chart(build, title, f"Concentration of sales: share of copies sold by the best-selling games, releases "
                             f"{MODEL_FROM}–{YEAR_MAX} (dashed line = every game sells the same)")
    hhi["Label"] = hhi["HHI"].map(lambda v: f"{v:,.0f}")
    title = (f"Publisher concentration (HHI) moved from {hhi.iloc[0]['HHI']:,.0f} to {hhi.iloc[-1]['HHI']:,.0f}: "
             f"{'a moderately concentrated' if hhi['HHI'].mean() >= 1500 else 'an unconcentrated'} market by the "
             f"usual antitrust yardstick (under 1,500)")

    def build():
        base = alt.Chart(hhi).encode(x=year_axis(), y=alt.Y("HHI:Q", title="HHI (0–10,000)"))
        return (base.mark_line(color=NAVY, strokeWidth=2.4, point=line_points())
                + base.mark_text(dy=-10, fontSize=10, color=INK).encode(text="Label:N")).properties(height=260)
    show_chart(build, title, "Herfindahl-Hirschman Index of publisher shares, by release year")
    source(SRC_VGC, "Method: HHI = the sum of each publisher's squared market share (in %), the standard antitrust "
                    "measure; under 1,500 is usually called unconcentrated, 1,500–2,500 moderately concentrated. "
                    "Shares of boxed copies only. " + NOTE[2] + " " + NOTE[9])

    # 14.4 Hedonic regression
    r, r2, n = E["hedonic"]
    r["Factor"] = r["term"]
    order = list(r.sort_values("Effect", ascending=False)["Factor"])
    best = r.loc[r["Effect"].idxmax()]
    title = (f"Holding genre, publisher, year and console fixed, {best['Factor'].split(': ')[-1]} goes with the "
             f"biggest sales premium ({best['Effect']:+.0%})")
    show_chart(ci_dots(r, "Factor", order, "Sales vs. the reference group"), title,
               "What goes with sales, all else equal: % difference in copies sold vs. an Action game, an "
               "'Other' publisher and an original")
    source(SRC_VGC, f"Method: hedonic regression of log copies sold on genre, publisher group and sequel status, with "
                    f"a fixed effect for every year × console pair ({n:,} games, {MODEL_FROM}–{YEAR_MAX}; R² within "
                    f"year-console = {r2:.2f}). Each estimate compares games released the same year on the same "
                    f"console. " + NOTE["assoc"])

    # 14.5 Launch month
    r, hol, n = E["months"]
    r["Month"] = r["term"]
    title = (f"Within the same year and console, holiday (Oct–Dec) launches sell {hol['Effect']:+.0%} vs. the rest of "
             f"the year (95% interval {hol['Lo']:+.0%} to {hol['Hi']:+.0%})")
    show_chart(ci_dots(r, "Month", [c for c in MONTHS if c in set(r["Month"])], "Sales vs. a January launch"),
               title, "Launch month: % difference in copies sold vs. January, same year and console")
    source(SRC_VGC, f"Method: regression of log copies sold on launch-month indicators with a fixed effect for every "
                    f"year × console pair ({n:,} games). The holiday figure comes from the same model with one "
                    f"October–December indicator. " + NOTE[8] + " " + NOTE["assoc"])
    takeaway("<b>Insight:</b> these five analyses tighten the patterns from the charts above by comparing like with "
             "like: sequels against their own series, launches against games from the same year and console. The "
             "patterns hold up, but none of them can separate the choice from the expectations behind it, so read "
             "them as evidence for an argument, not as forecasts.")


# --- Sidebar: menu + glossary ---------------------------------------------------------------------------------------
GLOSSARY = {
    "Copies sold (units)": define("units"),
    "Million seller (hit)": define("million-seller"),
    "Million-seller rate": define("hit rate"),
    "Typical game": "The middle game: half sold more, half sold less. Unlike an average, it isn't pulled up by a "
                    "few giant hits.",
    "Publisher": define("publisher"),
    "Follow-up / sequel": define("follow-up"),
    "Console maker": "PlayStation (Sony), Nintendo, Xbox (Microsoft), PC, Sega or other.",
    "Boxed copies": "Physical copies sold in stores. VGChartz counts these; downloads are largely missing.",
    "Critic score": define("critic"),
    "Player rating": define("player rating"),
    "ESRB": define("esrb"),
    "Holiday launch": define("holiday"),
    "Steam owners": define("owners"),
    "Steam reviews": define("reviews"),
    "Predicted share": define("explained"),
}
with st.sidebar:
    st.markdown("### Sections")
    st.markdown("\n".join(f"{NAV_NUM[t]}. [{t}](#{a})" for t, a in NAV.items()))
    st.markdown("### Glossary")
    for term, text in GLOSSARY.items():
        st.markdown(f"**{term}**  \n<span style='color:{MUTED};font-size:.85rem'>{text}</span>",
                    unsafe_allow_html=True)
    st.markdown("### Sources")
    st.markdown(f"<span style='color:{MUTED};font-size:.8rem'>VGChartz; Wikipedia best-seller lists (publisher "
                f"figures); Famitsu via Gematsu; SteamSpy; IGDB (covers, ratings). Logos: Wikimedia Commons, public "
                f"domain, trademarks of their owners. Full list in the project README.</span>", unsafe_allow_html=True)


# --- Page: one long scroll, in NAV order -----------------------------------------------------------------------------
def divider(head, text):
    st.markdown(f"<div class='deeper'><b>{head}</b><br>{text}</div>", unsafe_allow_html=True)


market_section()        # 1
winning_section()       # 2
fatigue_section()       # 3
divider("Go deeper", "That's the end of the in-class stops. Next: publisher playbooks, timing, regional taste and "
                     "what critics and players reward.")
publishers_section()    # 4
platforms_section()     # 5
regions_section()       # 6
critics_section()       # 7
divider("The digital era, 2019–2026", "VGChartz stops in 2018. These sections use other sources to show what sold "
                                      "since: publishers' own figures for hits, Japan's store charts, and Steam for PC.")
hits_section()          # 8
japan_section()         # 9
steam_section()         # 10
divider("Build your pitch", "Pitch your own game, see how far prediction gets you, and look up any game.")
pitch_section()         # 11
predict_section()       # 12
database_section()      # 13
divider("Methods", "Five econometric analyses that test the patterns above more carefully.")
econ_section()          # 14
