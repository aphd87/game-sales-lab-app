"""Game Sales Lab: classroom dashboard on the video game business, built on VGChartz unit sales. Companion to the
Behind the Box Office Lab and built on the same code: one long page, the same design system, the same shared chart
cache (every chart is built once per distinct set of inputs and shared by all sessions, see show_chart) and the same
hover definitions.

Everything is precomputed by build_data.py into data/ (merged VGChartz games, prediction-model scores, the pitch
grid), so a click only filters a ~19,000-row table. Nothing is fitted while students use the app.
APP_PASSWORD, if set as a secret or environment variable, gates the app; locally there is no password.
"""
import hashlib
import hmac
import inspect
import json
import os
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
# Same roles as the Box Office Lab: each color role means one thing everywhere on the page.
#   Publisher identity  PUB_COLOR        only when a chart is split by publisher group
#   Genre               GENRE_COLOR (CAT) only for genres
#   Platform family     FAMILY_COLOR     only for console makers (the Box Office Lab's deeper emotion palette, so
#                                        it never looks like a genre)
#   Region              REGION_COLOR     a blue-to-gray ramp: North America, Europe, Japan, rest of world
#   Focus vs. comparison  FOCUS / COMPARE   neutral two-group splits (follow-up vs. original, one pick vs. all)
#   Good vs. bad        GOOD / BAD        outcomes with a sign
#   Magnitude           light blue -> BLUE heatmaps
BLUE, INK, GRAY, MUTED = "#3582F0", "#111827", "#9ca3af", "#6b7280"
PANEL, SOFT = "#eaeaf2", "#9aa3b2"
FOCUS, COMPARE = BLUE, SOFT
GOOD, BAD = BLUE, INK
RULE = MUTED
KEYLINE = "#374151"
RAMP3 = ["#b9d3f8", "#76a9f4", BLUE]
CAT = ["#3582F0", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
FONT = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"
GENRE_ORDER = ["Action", "Sports", "Shooter", "Role-Playing", "Platform", "Racing", "Misc", "Simulation"]
GENRE_COLOR = dict(zip(GENRE_ORDER, CAT)) | {"Other": GRAY}
FAMILY_ORDER = ["PlayStation", "Nintendo", "Xbox", "PC", "Sega", "Other"]
FAMILY_COLOR = {"PlayStation": "#006482", "Nintendo": "#a60455", "Xbox": "#315418", "PC": "#937104",
                "Sega": "#690d95", "Other": "#8b9099"}
REGIONS = {"na_sales": "North America", "eu_sales": "Europe", "jp_sales": "Japan", "other_sales": "Rest of world"}
REGION_ORDER = list(REGIONS.values())
REGION_COLOR = dict(zip(REGION_ORDER, ["#1d4f9e", BLUE, "#9cc2f7", "#cfd5de"]))
PUB_ORDER = ["Nintendo", "Electronic Arts", "Activision", "Sony", "Ubisoft", "Take-Two", "Microsoft", "Sega"]
# Each publisher group keeps one color in every chart (the Box Office Lab's validated studio colors plus a teal-green
# for Microsoft). The first green tried, #1b7a4b, collapsed into Nintendo's magenta under deuteranopia (CIEDE2000
# 3.3); #0f6e5e lowers no pair's separation under protan, deutan or tritan simulation (Machado 2009, 2026-11-25).
# Sega is white, so its marks get a charcoal keyline and its text is charcoal.
PUB_COLOR = {"Nintendo": "#c2185b", "Electronic Arts": "#e5631f", "Activision": "#7d8899", "Sony": "#8e3aa8",
             "Ubisoft": "#7a5216", "Take-Two": "#d9a900", "Microsoft": "#0f6e5e", "Sega": "#ffffff"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HIT_UNITS = 1.0           # million units = a hit
YEAR_MIN, YEAR_MAX = 1980, 2018


def pub_text(p):
    return KEYLINE if p == "Sega" else PUB_COLOR.get(p, INK)


def pub_expr(field):
    expr = f"'{KEYLINE}'"
    for p in reversed(PUB_ORDER):
        expr = f"datum['{field}'] == '{p}' ? '{pub_text(p)}' : {expr}"
    return alt.ExprRef(expr=expr)


NAV = {"Market Size": "market", "Who's Winning": "winning", "Franchise Fatigue": "fatigue",
       "Publisher Playbooks": "publishers", "Platforms & Calendar": "platforms", "Regional Taste": "regions",
       "Critics & Sales": "critics", "Pitch a Game": "pitch", "Predict the Sales": "predict",
       "Game Database": "database"}
NAV_NUM = {t: str(i) for i, t in enumerate(NAV, start=1)}
CLASS_STOPS = 3
BUILD_STOPS = 7

# --- Definitions on hover (first match wins, so specific phrases come first) ---------------------------------------
DEFINE_RULES = [
    ("million-seller", f"A game (on one platform) that sold at least {HIT_UNITS:.0f} million units over its life."),
    ("hit rate", f"Share of games (each platform version counted separately) that sold at least {HIT_UNITS:.0f} "
                 f"million units: the million-seller rate."),
    ("chance of a million", "Share of the model's past misses that would still leave this game above 1 million units."),
    ("10th–90th", "The range from a bad case (only 1 game in 10 did worse) to a good case (only 1 in 10 did better)."),
    ("likely range", "The middle 50% of outcomes: half of comparable past games landed inside this range."),
    ("predicted", "The model's median prediction of lifetime units for these choices."),
    ("top-5 share", "Share of the year's units sold by the five biggest publisher groups that year."),
    ("share of units", "The group's units ÷ all units in the comparison."),
    ("units", "Lifetime unit sales in millions, as estimated by VGChartz (mostly boxed retail; digital sales are "
              "largely missing, so recent years are undercounted)."),
    ("north america", "Unit sales in the US and Canada (millions)."),
    ("europe", "Unit sales in Europe and other PAL territories (millions)."),
    ("japan", "Unit sales in Japan (millions)."),
    ("rest of world", "Unit sales outside North America, Europe and Japan (millions)."),
    ("critic", "VGChartz critic score, 0–10 (an average of professional reviews). Only about 4,600 games have one."),
    ("follow-up", "A later entry in a franchise: a game whose series (title before the subtitle or number) had an "
                  "earlier release. Detected from titles, so it is approximate."),
    ("original", "A game that is the first entry in its series, or not part of a series."),
    ("entries", "Distinct titles in the franchise (each title counted once, all platforms summed)."),
    ("explained by the data", "Share of the differences in units between games that a model can predict on games it "
                              "never saw (cross-validated R²)."),
    ("r²", "Share of the variation in the outcome the model explains on games it never saw: 1 = perfect, 0 = no "
           "better than guessing the average."),
    ("importance", "How much the random forest's score drops when this feature is scrambled. Bigger = relied on more."),
    ("holiday", "Games released October–December."),
    ("games", "Number of game-platform releases in the group (a game on three consoles counts three times)."),
    ("publisher", "The publisher group: labels rolled up to their parent (EA Sports → Electronic Arts, Rockstar and "
                  "2K → Take-Two, Blizzard → Activision), as owned during the data's years."),
    ("platform", "The console or PC the version was released on."),
    ("genre", "VGChartz genre. Genres outside the main eight (adventure, fighting, strategy, puzzle and others) "
              "are grouped as Other."),
    ("year", "Year of release (first release date for that platform)."),
]
def define(label):
    """Hover definition for a measure's label, or None. 'Median ...' labels say so."""
    low = str(label).lower()
    for key, text in DEFINE_RULES:
        if key in low:
            if low.startswith("median") or "· follow-up vs. original" in low:
                text = "Median = the middle game (half above, half below), which ignores a few huge outliers. " + text
            return text
    return None


def measure_help(names):
    """Help text for a 'Measure' picker: every option with its definition."""
    return "  \n".join(f"**{n}**: {define(n) or ''}" for n in names)


# Default every st.metric's hover help to the label's definition (an explicit help= still wins).
_metric = st.delta_generator.DeltaGenerator.metric


def _metric_with_help(self, label, value, *args, help=None, **kw):
    return _metric(self, label, value, *args, help=help or define(label), **kw)


st.delta_generator.DeltaGenerator.metric = _metric_with_help

st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="st-"], .stMarkdown, .stCaption, button, input, textarea {{ font-family: {FONT}; }}
h1 {{ font-weight: 700 !important; letter-spacing: -0.025em; color: {INK}; line-height: 1.15 !important; }}
h2, h3, h4 {{ font-weight: 650 !important; letter-spacing: -0.015em; color: {INK}; }}
.kicker {{ text-transform: uppercase; letter-spacing: .09em; font-size: .74rem; font-weight: 600; color: {BLUE};
           margin-bottom: -.35rem; }}
.lede {{ font-size: 1.05rem; color: #374151; max-width: 62rem; }}
.rule {{ border: 0; border-top: 1px solid #e5e7eb; margin: 1.6rem 0 1.2rem; }}
[data-testid="stMetric"] {{ background: #fff; border: 1px solid #e5e7eb; border-left: 3px solid {BLUE};
                            border-radius: 4px; padding: .7rem .9rem; }}
[data-testid="stMetricLabel"] p {{ text-transform: uppercase; letter-spacing: .05em; font-size: .7rem !important;
                                   color: {MUTED}; font-weight: 600; }}
[data-testid="stMetricValue"] {{ font-size: 1.35rem !important; font-weight: 650; color: {INK}; }}
[data-testid="stMetricLabel"] *, [data-testid="stMetricValue"] * {{ white-space: normal !important;
    overflow: visible !important; text-overflow: clip !important; line-height: 1.25; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 1.4rem; border-bottom: 1px solid #e5e7eb; }}
.stTabs [data-baseweb="tab"] p {{ font-weight: 600; font-size: .95rem; }}
.chapter {{ border-top: 2px solid {INK}; margin: 3.2rem 0 1.1rem; }}
.navbar {{ display: flex; flex-wrap: wrap; gap: .45rem; margin: .6rem 0 1.4rem; padding: .5rem 0;
           background: #fff; border-bottom: 1px solid #e5e7eb; }}
/* Section pills stay pinned under Streamlit's header while scrolling; headings land below the bar when clicked */
div[data-testid="stElementContainer"]:has(.navbar), div.element-container:has(.navbar) {{
    position: sticky; top: 3.75rem; z-index: 990; }}
.jump {{ position: relative; }} .jump span {{ position: absolute; top: -11rem; }}
.navbar a {{ text-decoration: none; font-size: .82rem; font-weight: 600; color: {INK}; border: 1px solid #e5e7eb;
             border-radius: 999px; padding: .28rem .8rem; background: #fff; }}
.navbar a:hover {{ border-color: {BLUE}; color: {BLUE}; }}
.navbar a b {{ color: {BLUE}; margin-right: .3rem; }}
.navbar .navsep {{ font-size: .72rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
                   color: {MUTED}; align-self: center; margin: 0 .2rem 0 .5rem; }}
.deeper {{ margin: 3.6rem 0 0; padding: .9rem 1.1rem; border: 1px dashed #cbd5e1; border-radius: 8px;
           color: {MUTED}; background: #fafbfc; }}
section[data-testid="stSidebar"] a {{ text-decoration: none; color: {INK}; }}
[data-testid="stIconMaterial"], .material-symbols-rounded, [class*="material-symbols"] {{
    font-family: 'Material Symbols Rounded' !important; }}
[data-testid="stCaptionContainer"] p, .stCaption p {{ color: {MUTED}; }}
.skey {{ display: flex; flex-wrap: wrap; gap: .6rem; margin: .4rem 0 .2rem; }}
.skey-card {{ flex: 1 1 96px; max-width: 150px; text-align: center; padding: .5rem .4rem .45rem;
              border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }}
.skey-logo {{ height: 40px; display: flex; align-items: center; justify-content: center; }}
.skey-logo img {{ max-height: 40px; max-width: 100%; object-fit: contain; }}
.skey-swatch {{ height: 5px; border-radius: 3px; margin: .45rem .3rem .3rem; }}
.skey-name {{ font-size: .8rem; font-weight: 650; }}
.skey-note {{ font-size: .72rem; color: {MUTED}; margin-bottom: .6rem; }}
.takeaway {{ border-left: 3px solid {BLUE}; background: #f5f9ff; padding: .75rem 1rem; margin: .4rem 0 1rem;
             color: {INK}; border-radius: 0 4px 4px 0; }}
.takeaway b {{ color: {BLUE}; }}
</style>""", unsafe_allow_html=True)
# st.dataframe takes width="stretch" from Streamlit 1.46; older versions (e.g. a local 1.45) need use_container_width
_NEW_WIDTH = tuple(int(x) for x in st.__version__.split(".")[:2]) >= (1, 46)
_LAZY_DOWNLOAD = tuple(int(x) for x in st.__version__.split(".")[:2]) >= (1, 67)   # download_button(data=callable)


def _stretch(fn):
    return {"width": "stretch"} if _NEW_WIDTH and "width" in inspect.signature(fn).parameters \
        else {"use_container_width": True}


def show_table(df, column_config=None, **kw):
    """st.dataframe in house style, with each column header's hover help filled in from define()."""
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




# --- Shared chart cache -------------------------------------------------------------------------------------------
# Building an Altair chart and converting it to Vega-Lite costs ~20-80 ms of server CPU, and a full page draws 29 of
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


def show_chart(build, title=None, subtitle=None, panel=True):
    """House style for every chart, after seaborn's darkgrid: a soft gray-blue panel with white gridlines, no axis
    lines or ticks. The heading names the measure (subtitle); the insight (title) goes in an Insight box under the
    chart, so every chart ends with its answer. Heatmaps pass panel=False (white background, as in seaborn).

    build is a no-argument function returning the Altair chart (cached across sessions, see above); a chart object
    also works but is drawn uncached. build() must only use values it closes over plus this module's constants."""
    is_fn = inspect.isfunction(build)
    key = None
    if is_fn and _altair_to_spec is not None:
        try:
            key = (_builder_key(build), title, subtitle, panel)
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
        chart = _house_style(build() if is_fn else build, title, subtitle, panel)
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
    if title and subtitle:
        takeaway(f"<b>Insight:</b> {title}")


def _house_style(chart, title, subtitle, panel):
    if subtitle or title:
        chart = chart.properties(title=alt.TitleParams(text=subtitle or title, anchor="start"))
    grid = dict(grid=True, gridColor="white", gridWidth=1.2, domain=False, ticks=False)
    chart = (chart.configure(font=FONT, background="white", padding={"left": 4, "right": 18, "top": 6, "bottom": 4})
             .configure_view(stroke=None, fill=PANEL if panel else "white")
             .configure_title(fontSize=15, fontWeight=600, color=INK, subtitleColor=MUTED, subtitleFontSize=12,
                              subtitleFontWeight="normal", anchor="start", offset=14, subtitlePadding=5)
             .configure_axis(labelColor=KEYLINE, titleColor=MUTED, labelFontSize=11, titleFontSize=11,
                             titleFontWeight="normal", labelPadding=6, domain=False, ticks=False)
             .configure_axisQuantitative(**grid)
             .configure_axisTemporal(**grid)
             .configure_axisDiscrete(grid=False)
             .configure_legend(labelFontSize=11, labelColor=KEYLINE, symbolType="circle", symbolSize=80,
                               titleFontSize=11, titleColor=MUTED, columnPadding=14))
    return chart


def section(kicker, title, how):
    """Chapter opener on the one-page scroll. The anchor comes from NAV, so the menu links land here."""
    # The jump target sits above the heading so the pinned section bar doesn't cover it
    st.markdown(f"<div class='chapter'></div><div class='jump'><span id='{NAV[title]}'></span></div>"
                f"<div class='kicker'>{NAV_NUM[title]} · {kicker}</div>", unsafe_allow_html=True)
    st.subheader(title, anchor=False)
    st.markdown(how)


def exhibit(title):
    st.markdown(f"<hr class='rule'><h4 style='margin-bottom:.2rem'>{title}</h4>", unsafe_allow_html=True)


def takeaway(html):
    st.markdown(f"<div class='takeaway'>{html}</div>", unsafe_allow_html=True)



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
@st.cache_resource(show_spinner="Loading the game data…")
def load():
    games = pd.DataFrame(json.loads((DATA / "games.json").read_text(encoding="utf-8")))
    games["units"] = games["total_sales"]
    games["kind"] = np.where(games["follow_up"] == 1, "Follow-up", "Original")
    games["label"] = games["title"] + " (" + games["platform"] + ", " + games["year"].astype(str) + ")"
    models = json.loads((DATA / "models.json").read_text(encoding="utf-8"))
    pitch = json.loads((DATA / "pitch.json").read_text(encoding="utf-8"))
    return games, models, pd.DataFrame(pitch["rows"]), pitch["platforms"]


GAMES, MODELS, PITCH, PITCH_PLATFORMS = load()
PLATFORM_NAME = dict(zip(GAMES["platform"], GAMES["platform_name"]))
GENRES = GENRE_ORDER + ["Other"]
PUBS = PUB_ORDER + ["Other"]
REG_COLS = list(REGIONS)
# North American launch year of each platform, for "years since launch"
LAUNCH = {"NES": 1985, "GB": 1989, "GEN": 1989, "SNES": 1991, "PS": 1995, "SAT": 1995, "N64": 1996, "DC": 1999,
          "PS2": 2000, "XB": 2001, "GC": 2001, "GBA": 2001, "DS": 2004, "PSP": 2005, "X360": 2005, "PS3": 2006,
          "Wii": 2006, "3DS": 2011, "PSV": 2012, "WiiU": 2012, "PS4": 2013, "XOne": 2013, "NS": 2017}


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


def line_points(size=60):
    return alt.OverlayMarkDef(size=size, filled=True, stroke="white", strokeWidth=1.5)


def year_axis(title=None):
    return alt.X("Year:Q", title=title, axis=alt.Axis(format="d", tickMinStep=1), scale=alt.Scale(nice=False))


def notes(*text):
    """The qualifiers under a chart, in the house caption style."""
    st.caption("*" + " ".join(text) + "*")


NOTE = {   # the README's assumptions, in one sentence each, repeated under the charts they apply to
    1: "VGChartz estimates, not reported sales.",
    2: "Mostly boxed retail: digital sales are largely missing, so recent years, PC and digital-heavy publishers are "
       "undercounted.",
    3: "Coverage ends in 2018.",
    4: "Merged from two VGChartz scrapes; about 1,700 games (mostly Nintendo's own) come from the 2016 file and their "
       "sales stop at 2016 levels.",
    5: "Each platform version counts as its own game.",
    6: "Units, not revenue: a budget game and a full-price game count the same.",
    8: "Month views use the 97% of games with a full release date.",
    9: "Publishers are rolled up to their parent as owned at the time (Rockstar and 2K in Take-Two, Blizzard in "
       "Activision); later deals such as Microsoft buying Activision are not applied.",
    10: "VGChartz genre labels; genres outside the main eight are grouped as Other.",
    11: "Franchises are detected from titles, so they are approximate: series whose entries have different names are "
        "missed, and unrelated games that share a name can be lumped together.",
    12: "Critic scores exist for only about 4,600 games, mostly bigger releases, so these results describe that subset.",
    13: "Models are fit on games released 2000–2018 and graded on games they never saw (5-fold cross-validation).",
    14: "Pitch predictions assume a 2018 release and describe comparable past games, not a forecast for today's "
        "market.",
    "assoc": "Descriptive, not causal: publishers choose which games get sequels, big platforms and holiday dates.",
    "release_year": "Units are the lifetime sales of games released in each year, not sales made during that year.",
}


def note(*keys):
    notes(*(NOTE[k] for k in keys))


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


def pub_lines(d, x, y, pick, tooltip, point_size=50):
    """One line per publisher group in its own color, labeled at its last point. Sega's white line sits on a
    charcoal keyline."""
    color = alt.Color("Publisher:N", scale=alt.Scale(domain=pick, range=[PUB_COLOR[p] for p in pick]), legend=None)
    halo = alt.Chart(d).transform_filter("datum.Publisher == 'Sega'").encode(x=x, y=y)
    main = alt.Chart(d).mark_line(point=line_points(point_size), strokeWidth=2.2).encode(
        x=x, y=y, color=color, tooltip=tooltip)
    last = end_labels(d, x.shorthand.split(":")[0], y.shorthand.split(":")[0], "Publisher")
    labels = alt.Chart(last).mark_text(align="left", dx=8, fontSize=11, fontWeight=600,
                                       color=pub_expr("Publisher")).encode(x=x, y=alt.Y("LabelY:Q"), text="Publisher:N")
    return alt.layer(halo.mark_line(color=KEYLINE, strokeWidth=4.4),
                     halo.mark_circle(color=KEYLINE, size=point_size + 45, opacity=1), main, labels)


def heatmap(d, x, y, x_order, y_order, legend_title, fmt_str, y_color=None, count_title="Games"):
    """Light-blue-to-blue heatmap with the value printed in each cell. y_color is an Altair color expression for the
    row labels (publisher colors), or None for ink."""
    yaxis = alt.Axis(labelFontWeight=600, labelColor=y_color) if y_color is not None else alt.Axis(labelFontWeight=600)
    base = alt.Chart(d).encode(x=alt.X(f"{x}:N", sort=x_order, title=None, axis=alt.Axis(labelAngle=0, orient="top")),
                               y=alt.Y(f"{y}:N", sort=y_order, title=None, axis=yaxis))
    rect = base.mark_rect(stroke="white", strokeWidth=2, cornerRadius=2).encode(
        color=alt.Color("Value:Q", title=legend_title, scale=alt.Scale(range=["#eef4fe", BLUE]),
                        legend=alt.Legend(orient="right", gradientLength=160, format=fmt_str)),
        tooltip=[alt.Tooltip(f"{y}:N"), alt.Tooltip(f"{x}:N"), alt.Tooltip("Value:Q", format=fmt_str, title=legend_title),
                 alt.Tooltip("n:Q", title=count_title, format=",")])
    cut = d["Value"].max() * 0.75 if len(d) else 0   # white text only on the darker cells of the scale
    text = base.mark_text(fontSize=11).encode(
        text=alt.Text("Value:Q", format=fmt_str),
        color=alt.condition(f"datum.Value > {cut}", alt.value("white"), alt.value(INK)))
    return (rect + text).properties(height=34 * len(y_order) + 24)


CSV_COLS = {"title": "Title", "platform": "Platform", "family": "Platform family", "year": "Year",
            "release": "Release date", "genre": "Genre", "genre_raw": "VGChartz genre", "publisher": "Publisher label",
            "pub": "Publisher group", "developer": "Developer", "kind": "Original / follow-up", "series": "Series",
            "entry": "Entry number", "critic_score": "Critic score (0-10)", "na_sales": "North America (M units)",
            "eu_sales": "Europe (M units)", "jp_sales": "Japan (M units)", "other_sales": "Rest of world (M units)",
            "total_sales": "Total (M units)", "source": "Source"}


def csv_bytes(v):
    return v[list(CSV_COLS)].rename(columns=CSV_COLS).to_csv(index=False).encode("utf-8")


# --- Header -------------------------------------------------------------------------------------------------------
st.markdown("<div class='kicker'>Media &amp; Entertainment Businesses · Games data lab</div>", unsafe_allow_html=True)
st.title("Game Sales Lab: What Sells in the Video Game Business?")
st.markdown(f"<p class='lede'>{len(GAMES):,} game releases on {GAMES['platform'].nunique()} platforms, "
            f"{YEAR_MIN}–{YEAR_MAX}, from VGChartz's unit-sales estimates: the market, the publishers, the franchises, "
            f"the platforms and the critics. Companion to the Behind the Box Office Lab.</p>", unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def headline_numbers():
    g = GAMES
    recent = g[g["year"] >= 2000]
    by = recent.groupby(["year", "pub"])["units"].sum().reset_index()
    top5 = by.groupby("year").apply(lambda d: d.nlargest(5, "units")["units"].sum() / d["units"].sum(),
                                    include_groups=False)
    rf = lambda fs: float(np.mean(MODELS.get(fs, {}).get("cv", {}).get("Random forest", [np.nan])))
    return {"units": g["units"].sum(), "n": len(g), "hit": g["hit"].mean(), "top5": float(top5.mean()),
            "top5_lo": float(top5.min()), "top5_hi": float(top5.max()),
            "r2": rf("Greenlight"), "r2_critic": rf("Greenlight + critic score")}


H = headline_numbers()
cols = st.columns(4)
cols[0].metric("Units tracked", units_fmt(H["units"]),
               help=f"Lifetime unit sales of all {H['n']:,} game releases, {YEAR_MIN}–{YEAR_MAX} (VGChartz estimates, "
                    f"mostly boxed retail).")
cols[1].metric("Million-seller rate", pct(H["hit"]))
cols[2].metric("Top-5 publisher share, 2000–18", pct(H["top5"]),
               help=f"Average share of each year's units sold by that year's five biggest publisher groups (range "
                    f"{pct(H['top5_lo'])}–{pct(H['top5_hi'])}).")
cols[3].metric("Units explained by the data", pct(H["r2"]),
               help=f"Random forest, cross-validated, games released 2000–2018, from genre, platform, publisher, "
                    f"follow-up status and year. Adding the critic score (subset with scores): {pct(H['r2_critic'])}.")

st.info(
    "**What this data can tell you.** These are VGChartz **estimates** of **boxed retail units**, not publisher-"
    "reported sales: digital downloads are largely missing, so recent years, PC games and digital-heavy publishers "
    "are undercounted, and the data **ends in 2018**. Counts are **units, not revenue**, and a game on three consoles "
    "counts as three games. Every finding shows what has **gone together** with bigger sales; it does **not** prove "
    "that a choice *causes* them. Publishers pick which games get sequels, big budgets and holiday dates, and those "
    "choices travel together. Full list: the README's *Assumptions and limits*."
)
c1, c2 = st.columns(2)
c1.markdown("**The Problem**  \n"
            "A game takes years and tens of millions of dollars to make, and most releases never sell a million "
            "copies. Publishers and platform owners have to decide which games to fund, on which consoles, for which "
            "regions and when to launch them, while players move to digital storefronts and subscriptions and the "
            "biggest franchises take a growing share of attention.")
c2.markdown("**The Solution**  \n"
            "This lab puts four decades of game releases in one place: the **market** (how big, and where), the "
            "**publishers** (who wins and with what playbook), the **franchise** (do follow-ups hold up?), the "
            "**platform and calendar**, and the **critics**. Then pitch your own game and see what comparable games "
            "sold. Use it to build the evidence behind your Bottom Line Up Front.")
_pills = [f"<a href='#{a}'><b>{NAV_NUM[t]}</b>{t}</a>" for t, a in NAV.items()]
st.markdown("<div class='navbar'><span class='navsep' style='margin-left:0'>In class</span>"
            + "".join(_pills[:CLASS_STOPS]) + "<span class='navsep'>Go deeper</span>"
            + "".join(_pills[CLASS_STOPS:BUILD_STOPS]) + "<span class='navsep'>Build your pitch</span>"
            + "".join(_pills[BUILD_STOPS:]) + "</div>", unsafe_allow_html=True)
st.caption("Hover any number, column header or ⓘ for its definition. Section menu and full glossary: the › arrow at "
           "the top left.")


# --- 1. Market Size ------------------------------------------------------------------------------------------------
def market_section():
    section("Market", "Market Size",
            "How many games does the industry sell, where, and on whose hardware? Each year below counts the "
            "lifetime units of the games released that year.")
    exhibit("How big is the market, and where are the players?")
    y = GAMES.groupby("year")[REG_COLS].sum().rename(columns=REGIONS)
    y["Total"] = y.sum(axis=1)
    peak = int(y["Total"].idxmax())
    reg_share = GAMES[REG_COLS].sum() / GAMES["units"].sum()
    long = y.drop(columns="Total").reset_index().melt("year", var_name="Region", value_name="Units")
    long = long.rename(columns={"year": "Year"})
    title = (f"Retail units peaked with the {peak} release year at {units_fmt(y.loc[peak, 'Total'])}; North America "
             f"bought {pct(reg_share['na_sales'])} of all units, Japan {pct(reg_share['jp_sales'])}")

    def build():
        return alt.Chart(long).mark_area(stroke="white", strokeWidth=0.6).encode(
            x=year_axis(), y=alt.Y("Units:Q", stack=True, title="Units (millions)"),
            color=alt.Color("Region:N", sort=REGION_ORDER,
                            scale=alt.Scale(domain=REGION_ORDER, range=[REGION_COLOR[r] for r in REGION_ORDER]),
                            legend=alt.Legend(orient="top", title=None)),
            order=alt.Order("order:Q"),
            tooltip=[alt.Tooltip("Year:Q", format="d"), "Region:N", alt.Tooltip("Units:Q", format=",.1f",
                                                                                 title="Units (M)")]
        ).transform_calculate(order=f"indexof({json.dumps(REGION_ORDER)}, datum.Region)").properties(height=320)
    show_chart(build, title, "Lifetime units of the games released each year, by region (millions)")
    note(1, 2, 3, 6, "release_year")
    takeaway("<b>Read with care:</b> much of the fall after 2010 is downloads that VGChartz can't see, not players "
             "leaving. Compare the shape before 2010, when almost everything was sold on a disc or cartridge.")

    exhibit("Whose hardware do the games sell on?")
    f = GAMES.groupby(["year", "family"])["units"].sum().reset_index().rename(columns={"year": "Year",
                                                                                       "family": "Family"})
    f["Units"] = f["units"]
    f["Share"] = f["units"] / f.groupby("Year")["units"].transform("sum")
    f = f[f["Year"] >= 1985]
    late = GAMES[GAMES["year"].between(2014, 2018)].groupby("family")["units"].sum()
    late = late / late.sum()
    lead = late.idxmax()
    title = (f"{lead} platforms carried {pct(late[lead])} of software units for 2014–18 releases, "
             f"{late.drop(lead).idxmax()} {pct(late.drop(lead).max())}")

    def build():
        return alt.Chart(f).mark_area(stroke="white", strokeWidth=0.6).encode(
            x=year_axis(), y=alt.Y("Share:Q", stack="normalize", title="Share of units",
                                   axis=alt.Axis(format="%")),
            color=alt.Color("Family:N", sort=FAMILY_ORDER,
                            scale=alt.Scale(domain=FAMILY_ORDER, range=[FAMILY_COLOR[k] for k in FAMILY_ORDER]),
                            legend=alt.Legend(orient="top", title=None)),
            order=alt.Order("order:Q"),
            tooltip=[alt.Tooltip("Year:Q", format="d"), "Family:N", alt.Tooltip("Share:Q", format=".0%"),
                     alt.Tooltip("Units:Q", format=",.1f", title="Units (M)")]
        ).transform_calculate(order=f"indexof({json.dumps(FAMILY_ORDER)}, datum.Family)").properties(height=300)
    show_chart(build, title, "Share of each release year's units by platform family (handhelds included)")
    note(1, 2, 3, 6)
    st.caption("*PC is the most undercounted family: almost all PC games are sold as downloads (Steam), which VGChartz "
               "does not track.*")


# --- 2. Who's Winning ----------------------------------------------------------------------------------------------
@st.fragment
def winning_section():
    section("Competition", "Who's Winning",
            "Which publishers sell the most games, and is the business getting more concentrated? Shares are of all "
            "units released in a year.")
    exhibit("Publisher share of units by year")
    pick = st.multiselect("Publishers", PUB_ORDER, default=["Nintendo", "Electronic Arts", "Activision", "Sony",
                                                              "Ubisoft", "Take-Two", "Microsoft"],
                          key="win_pubs", help=define("publisher"))
    years = st.slider("Release years", 1990, YEAR_MAX, (1995, YEAR_MAX), key="win_years")
    g = GAMES[GAMES["year"].between(*years)]
    s = g.groupby(["year", "pub_group"])["units"].sum().reset_index()
    s["Share"] = s["units"] / s.groupby("year")["units"].transform("sum")
    s = s.rename(columns={"year": "Year", "pub_group": "Publisher", "units": "Units"})
    if pick:
        d = s[s["Publisher"].isin(pick)]
        tot = g[g["pub_group"].isin(pick)].groupby("pub_group")["units"].sum()
        tot = tot / g["units"].sum()
        top = tot.idxmax()
        title = f"{top} sold the most units among these publishers, {pct(tot[top])} of {years[0]}–{years[1]} units"
        order = [p for p in PUB_ORDER if p in pick]

        def build():
            x, y = year_axis(), alt.Y("Share:Q", title="Share of units", axis=alt.Axis(format="%"))
            tip = [alt.Tooltip("Year:Q", format="d"), "Publisher:N", alt.Tooltip("Share:Q", format=".1%"),
                   alt.Tooltip("Units:Q", format=",.1f", title="Units (M)")]
            return pub_lines(d, x, y, order, tip).properties(height=340)
        show_chart(build, title, "Share of each release year's units, by publisher group")
    else:
        st.info("Pick at least one publisher.")
    note(2, 9)

    exhibit("Is the business getting more concentrated?")
    by = g.groupby(["year", "pub"])["units"].sum().reset_index()
    rows = []
    for yr, d in by.groupby("year"):
        t5 = d.nlargest(5, "units")
        rows.append({"Year": yr, "Top-5 share": t5["units"].sum() / d["units"].sum(),
                     "Top five": ", ".join(t5["pub"])})
    c = pd.DataFrame(rows)
    if len(c) >= 2:
        first, last = c.iloc[0], c.iloc[-1]
        title = (f"The five biggest publishers sold {pct(last['Top-5 share'])} of {int(last['Year'])} units vs. "
                 f"{pct(first['Top-5 share'])} in {int(first['Year'])}")

        def build():
            base = alt.Chart(c).encode(x=year_axis(), y=alt.Y("Top-5 share:Q", title="Top-5 share of units",
                                                              axis=alt.Axis(format="%"), scale=alt.Scale(zero=False)))
            return base.mark_line(color=FOCUS, strokeWidth=2.4, point=line_points()).encode(
                tooltip=[alt.Tooltip("Year:Q", format="d"), alt.Tooltip("Top-5 share:Q", format=".0%"),
                         "Top five:N"]).properties(height=260)
        show_chart(build, title, "Share of the year's units sold by that year's five biggest publisher groups")
    st.caption("*Publisher groups here are every parent company, not just the eight named above. Hover a point to see "
               "which five led that year. " + NOTE[2] + " " + NOTE[9] + "*")

    exhibit("Publisher scorecard")
    t = g.groupby("pub").agg(Games=("units", "size"), Units=("units", "sum"), Hit=("hit", "mean"),
                             Median=("units", "median")).reset_index()
    best = g.loc[g.groupby("pub")["units"].idxmax(), ["pub", "label"]].set_index("pub")["label"]
    t["Biggest game"] = t["pub"].map(best)
    t["Share"] = t["Units"] / g["units"].sum()
    t = t.sort_values("Units", ascending=False).head(25)
    show_table(t[["pub", "Games", "Units", "Share", "Hit", "Median", "Biggest game"]], column_config={
        "pub": "Publisher", "Games": st.column_config.NumberColumn("Games", format="%d"),
        "Units": st.column_config.NumberColumn("Units (M)", format="%.1f"),
        "Share": st.column_config.NumberColumn("Share of units", format="percent"),
        "Hit": st.column_config.NumberColumn("Hit rate", format="percent"),
        "Median": st.column_config.NumberColumn("Median units (M)", format="%.2f"),
        "Biggest game": st.column_config.TextColumn("Biggest game", width="large")})
    st.caption(f"*Top 25 publisher groups by units, {years[0]}–{years[1]} releases. Click a header to sort. "
               + NOTE[2] + "*")


# --- 3. Franchise Fatigue ------------------------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def franchise_titles():
    """One row per title in a series (all platforms summed), with its units relative to the series' first title."""
    s = GAMES[GAMES["series"].notna()].assign(key=lambda d: d["title"].str.lower())
    # Titles that differ only in capitalization (the two scrapes spell some differently) are the same title
    t = s.groupby(["series", "key"]).agg(title=("title", "first"), Entry=("entry", "min"), Year=("year", "min"),
                                         Units=("units", "sum"),
                                           Publisher=("pub", lambda x: x.mode().iat[0]),
                                           Platforms=("platform", lambda x: ", ".join(sorted(set(x)))),
                                           Critic=("critic_score", "median")).reset_index()
    n = t.groupby("series")["key"].transform("size")
    t = t[n >= 3].copy()
    first = t[t["Entry"] == t.groupby("series")["Entry"].transform("min")].groupby("series")["Units"].max()
    t["First"] = t["series"].map(first)
    t["Ratio"] = t["Units"] / t["First"]
    t["Total"] = t.groupby("series")["Units"].transform("sum")
    # A first title VGChartz barely saw (often a PC original, e.g. Call of Duty at 10K) makes every ratio explode,
    # so ratios are only measured against first titles that sold at least FIRST_MIN
    t["Ratio"] = t["Ratio"].where(t["First"] >= FIRST_MIN)
    t["Name"] = t["series"].map(series_names(s))
    return t


FIRST_MIN = 0.1   # million units


def series_names(s):
    """Display name of each series: its own spelling at the start of a title (else title case)."""
    out = {}
    for ser, titles in s.groupby("series")["title"]:
        hit = next((x[:len(ser)] for x in titles if x.lower().startswith(ser)), None)
        out[ser] = hit or ser.title()
    return out


@st.fragment
def fatigue_section():
    section("Franchises", "Franchise Fatigue",
            "Sequels are the industry's safest bet. But do later entries keep their audience, or does each one sell "
            "less than the last? Here every title in a series is summed across its platforms and compared with the "
            "series' first title.")
    t = franchise_titles()
    exhibit("Do later entries sell more or less than the first?")
    later = t[(t["Entry"] >= 2) & t["Ratio"].notna()].copy()
    later["Entry #"] = later["Entry"].clip(upper=10)
    e = later.groupby("Entry #").agg(Median=("Ratio", "median"), Beat=("Ratio", lambda r: (r > 1).mean()),
                                     n=("Ratio", "size")).reset_index()
    e["Entry label"] = np.where(e["Entry #"] >= 10, "10+", e["Entry #"].astype(int).astype(str))
    order = list(e["Entry label"])
    e2 = e[e["Entry #"] == 2].iloc[0] if (e["Entry #"] == 2).any() else None
    title = (f"The median second entry sold {e2['Median']:.2f}× its series' first title; "
             f"{pct(e2['Beat'])} outsold it" if e2 is not None else "Later entries vs. the first")

    def build():
        base = alt.Chart(e).encode(x=alt.X("Entry label:N", sort=order, title="Entry number in the series",
                                           axis=alt.Axis(labelAngle=0)))
        bars = base.mark_bar(color=FOCUS, cornerRadiusEnd=3, width={"band": 0.7}).encode(
            y=alt.Y("Median:Q", title="Median units ÷ first title's units"),
            tooltip=[alt.Tooltip("Entry label:N", title="Entry"), alt.Tooltip("Median:Q", format=".2f",
                                                                             title="Median × first title"),
                     alt.Tooltip("Beat:Q", format=".0%", title="Share outselling the first"),
                     alt.Tooltip("n:Q", title="Titles")])
        lab = base.mark_text(dy=-8, fontSize=11, color=INK).encode(y="Median:Q", text=alt.Text("Median:Q",
                                                                                            format=".2f"))
        one = alt.Chart(pd.DataFrame({"y": [1]})).mark_rule(color=RULE, strokeDash=[4, 3]).encode(y="y:Q")
        return (bars + lab + one).properties(height=300)
    show_chart(build, title, "Median units of each later title relative to its series' first title "
                             "(dashed line = sold the same)")
    note(11)
    kept = t.loc[t["Ratio"].notna(), "series"].nunique()
    st.caption(f"*{kept:,} of {t['series'].nunique():,} series with 3+ titles; the rest are left out because their "
               f"first title sold under {FIRST_MIN * 1000:.0f}K units in the data (often a PC original VGChartz "
               f"barely counted), which would make every later ratio huge. Units are summed across each title's "
               f"platforms. A series' first title in this data can be a later entry if earlier ones predate "
               f"VGChartz's coverage.*")

    o, fu = GAMES[GAMES["follow_up"] == 0], GAMES[GAMES["follow_up"] == 1]
    cols = st.columns(4)
    cols[0].metric("Median units · follow-up vs. original",
                   f"{units_fmt(median(fu['units']))} vs. {units_fmt(median(o['units']))}")
    cols[1].metric("Hit rate · follow-up vs. original", f"{pct(fu['hit'].mean())} vs. {pct(o['hit'].mean())}")
    cols[2].metric("Median critic · follow-up vs. original",
                   f"{median(fu['critic_score']):.1f} vs. {median(o['critic_score']):.1f}")
    cols[3].metric("Share of games that are follow-ups", pct(GAMES["follow_up"].mean()),
                   help="Share of game releases (each platform counted) whose series had an earlier title.")
    takeaway(f"<b>So what:</b> follow-ups sell more per release and hit a million more often. Descriptive only: "
             f"publishers make sequels to games that already sold, so follow-ups start from proven demand "
             f"({len(fu):,} follow-up releases vs. {len(o):,} originals).")

    exhibit("Pick a franchise")
    series = (t.drop_duplicates("series").sort_values("Total", ascending=False)["series"].tolist())
    name = dict(zip(t["series"], t["Name"]))
    default = series.index("call of duty") if "call of duty" in series else 0
    pick = st.selectbox("Series (title before the subtitle or number; 3+ titles)", series, index=default,
                        format_func=lambda s: name[s], key="fatigue_series")
    d = t[t["series"] == pick].sort_values(["Entry", "Year"]).copy()
    d["Name"] = d["title"] + " (" + d["Year"].astype(str) + ")"
    best = d.loc[d["Units"].idxmax()]
    title = (f"{best['title']} is the best seller of {name[pick]}: {units_fmt(best['Units'])}"
             + (f", {best['Ratio']:.1f}× the first title" if pd.notna(best["Ratio"]) and best["Entry"] > d["Entry"].min()
                else f" (the first title sold {units_fmt(best['First'])}, too little in the data to compare)"
                if pd.isna(best["Ratio"]) else ""))
    names = list(d["Name"])

    def build():
        base = alt.Chart(d).encode(x=alt.X("Name:N", sort=names, title=None,
                                           axis=alt.Axis(labelAngle=-40, labelLimit=180)))
        bars = base.mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("Units:Q", title="Units, all platforms (millions)"),
            color=alt.condition(f"datum.Entry == {int(d['Entry'].min())}", alt.value(COMPARE), alt.value(FOCUS)),
            tooltip=["title:N", alt.Tooltip("Year:Q", format="d"), "Publisher:N", "Platforms:N",
                     alt.Tooltip("Units:Q", format=",.2f", title="Units (M)"),
                     alt.Tooltip("Ratio:Q", format=".2f", title="× first title"),
                     alt.Tooltip("Critic:Q", format=".1f", title="Critic score")])
        return bars.properties(height=320)
    show_chart(build, title, f"{name[pick]}: units of each title, in release order (gray = first title)")
    note(11, 2)


# --- 4. Publisher Playbooks ----------------------------------------------------------------------------------------
H2H_YEARS = (2000, YEAR_MAX)


@st.fragment
def publishers_section():
    section("Strategy", "Publisher Playbooks",
            f"Where does each publisher place its bets: which genres, which consoles? All charts use "
            f"{H2H_YEARS[0]}–{H2H_YEARS[1]} releases.")
    g = GAMES[GAMES["year"].between(*H2H_YEARS)]
    exhibit("Genre mix: share of each publisher's units")
    m = g.groupby(["pub_group", "genre"]).agg(units=("units", "sum"), n=("units", "size")).reset_index()
    m["Value"] = m["units"] / m.groupby("pub_group")["units"].transform("sum")
    m = m.rename(columns={"pub_group": "Publisher", "genre": "Genre"})
    top = m[m["Publisher"] != "Other"].loc[lambda d: d["Value"].idxmax()]
    title = f"{top['Publisher']} is the most concentrated: {pct(top['Value'])} of its units are {top['Genre']} games"
    show_chart(lambda: heatmap(m, "Genre", "Publisher", GENRES, PUBS, "Share of units", ".0%",
                               y_color=pub_expr("value")),
               title, "Share of each publisher's units by genre (rows sum to 100%)", panel=False)
    note(2, 9, 10)

    exhibit("Platform mix: whose consoles does each publisher sell on?")
    f = g.groupby(["pub_group", "family"])["units"].sum().reset_index()
    f["Share"] = f["units"] / f.groupby("pub_group")["units"].transform("sum")
    f = f.rename(columns={"pub_group": "Publisher", "family": "Family", "units": "Units"})
    nin = f[(f["Publisher"] == "Nintendo") & (f["Family"] == "Nintendo")]["Share"]
    third = f[~f["Publisher"].isin(["Nintendo", "Sony", "Microsoft", "Other"])]
    spread = third.groupby("Publisher")["Share"].max().idxmin()
    title = (f"Platform owners stay home (Nintendo: {pct(nin.iat[0] if len(nin) else np.nan)} on its own hardware); "
             f"{spread} spreads most evenly across consoles")

    def build():
        return alt.Chart(f).mark_bar(stroke="white", strokeWidth=0.8).encode(
            y=alt.Y("Publisher:N", sort=PUBS, title=None,
                    axis=alt.Axis(labelColor=pub_expr("value"), labelFontWeight=600)),
            x=alt.X("Share:Q", stack="normalize", title="Share of units", axis=alt.Axis(format="%")),
            color=alt.Color("Family:N", sort=FAMILY_ORDER,
                            scale=alt.Scale(domain=FAMILY_ORDER, range=[FAMILY_COLOR[k] for k in FAMILY_ORDER]),
                            legend=alt.Legend(orient="top", title=None)),
            order=alt.Order("order:Q"),
            tooltip=["Publisher:N", "Family:N", alt.Tooltip("Share:Q", format=".0%"),
                     alt.Tooltip("Units:Q", format=",.1f", title="Units (M)")]
        ).transform_calculate(order=f"indexof({json.dumps(FAMILY_ORDER)}, datum.Family)").properties(height=330)
    show_chart(build, title, "Share of each publisher's units by platform family")
    note(2, 9)

    exhibit("Head to head")
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
        return {"Games": f"{len(d):,}", "Units": units_fmt(d["units"].sum()),
                "Median units per game": units_fmt(median(d["units"])),
                "Million-seller rate": pct(d["hit"].mean()), "Follow-up share of games": pct(d["follow_up"].mean()),
                "Median critic score": f"{median(d['critic_score']):.1f}",
                "Holiday share of units": pct(dated[dated["month"] >= 10]["units"].sum() / dated["units"].sum())
                if dated["units"].sum() else "—",
                "Top genre (units)": d.groupby("genre")["units"].sum().idxmax(),
                "Top platform family": d.groupby("family")["units"].sum().idxmax(),
                "Biggest game": d.loc[d["units"].idxmax(), "label"]}
    h = pd.DataFrame({"Measure": list(profile(a)), a: list(profile(a).values()), b: list(profile(b).values())}) \
        if a != b else pd.DataFrame({"Measure": list(profile(a)), a: list(profile(a).values())})
    show_table(h, column_config={"Measure": st.column_config.TextColumn("Measure", width="medium")})
    st.caption(f"*Publisher groups with 30+ releases, {H2H_YEARS[0]}–{H2H_YEARS[1]}. Holiday = October–December "
               f"releases. " + NOTE[2] + " " + NOTE[9] + "*")


# --- 5. Platforms & Calendar ---------------------------------------------------------------------------------------
@st.fragment
def platforms_section():
    section("Timing", "Platforms & Calendar",
            "When in a console's life do its games sell, and when in the year should a game launch?")
    exhibit("Software sales over a console's life")
    plats = [p for p in LAUNCH if p in set(GAMES["platform"])]
    pick = st.multiselect("Platforms", plats, default=["PS2", "PS3", "PS4", "X360", "XOne", "Wii", "DS"],
                          format_func=lambda p: PLATFORM_NAME.get(p, p), key="plat_pick")
    if pick:
        d = GAMES[GAMES["platform"].isin(pick)].copy()
        d["Years since launch"] = d["year"] - d["platform"].map(LAUNCH)
        d = d[d["Years since launch"].between(0, 10)]
        d = d.groupby(["platform", "family", "Years since launch"]).agg(Units=("units", "sum"),
                                                                        Games=("units", "size")).reset_index()
        d["Platform"] = d["platform"].map(lambda p: PLATFORM_NAME.get(p, p))
        peak = d.loc[d.groupby("platform")["Units"].idxmax()]
        title = (f"Software sales peak a median {median(peak['Years since launch']):.0f} years after launch; the "
                 f"biggest single year here is {peak.loc[peak['Units'].idxmax(), 'Platform']} "
                 f"({units_fmt(peak['Units'].max())})")
        fams = [k for k in FAMILY_ORDER if k in set(d["family"])]

        def build():
            x = alt.X("Years since launch:Q", title="Years since the console launched (North America)",
                      axis=alt.Axis(format="d", tickMinStep=1))
            y = alt.Y("Units:Q", title="Units of games released that year (millions)")
            lines = alt.Chart(d).mark_line(point=line_points(45), strokeWidth=2).encode(
                x=x, y=y, detail="Platform:N",
                color=alt.Color("family:N", title=None, sort=fams,
                                scale=alt.Scale(domain=fams, range=[FAMILY_COLOR[k] for k in fams]),
                                legend=alt.Legend(orient="top")),
                tooltip=["Platform:N", alt.Tooltip("Years since launch:Q", format="d"),
                         alt.Tooltip("Units:Q", format=",.1f", title="Units (M)"), "Games:Q"])
            # Lines all end near zero, so each platform is labeled at its peak year instead (dodged apart)
            pk = d.loc[d.groupby("Platform")["Units"].idxmax()].copy()
            pk["LabelY"] = dodge(pk["Units"] + d["Units"].max() * 0.05, d["Units"].max() * 0.055)
            labels = alt.Chart(pk).mark_text(align="center", fontSize=11, fontWeight=600).encode(
                x=x, y=alt.Y("LabelY:Q"), text="Platform:N",
                color=alt.Color("family:N", scale=alt.Scale(domain=fams, range=[FAMILY_COLOR[k] for k in fams]),
                                legend=None))
            return (lines + labels).properties(height=340)
        show_chart(build, title, "Lifetime units of the games released in each year of a console's life")
    else:
        st.info("Pick at least one platform.")
    note(5, 2, "release_year")
    st.caption("*Shows each console's first ten years. Late-life years for PS4, Xbox One and Switch are cut off by the 2018 end of the data and depressed "
               "by digital sales.*")

    exhibit("When do games launch, and when do they sell?")
    dated = GAMES[GAMES["month"].notna()].copy()
    dated["Month"] = dated["month"].astype(int).map(lambda m: MONTHS[m - 1])
    mth = dated.groupby("Month").agg(units=("units", "sum"), games=("units", "size")).reindex(MONTHS).reset_index()
    mth["Share of units"] = mth["units"] / mth["units"].sum()
    mth["Share of games"] = mth["games"] / mth["games"].sum()
    long = mth.melt("Month", ["Share of units", "Share of games"], var_name="Measure", value_name="Share")
    hol = dated["month"] >= 10
    hol_u = dated.loc[hol, "units"].sum() / dated["units"].sum()
    hol_g = hol.mean()
    title = (f"October–December releases are {pct(hol_g)} of games but {pct(hol_u)} of units: holiday launches "
             f"sell more per game")

    def build():
        kinds = ["Share of games", "Share of units"]
        return alt.Chart(long).mark_bar(stroke="white", strokeWidth=0.8, cornerRadiusEnd=3).encode(
            x=alt.X("Month:N", sort=MONTHS, title=None, axis=alt.Axis(labelAngle=0)),
            xOffset=alt.XOffset("Measure:N", sort=kinds),
            y=alt.Y("Share:Q", title="Share of the year", axis=alt.Axis(format="%")),
            color=alt.Color("Measure:N", sort=kinds, scale=alt.Scale(domain=kinds, range=[COMPARE, FOCUS]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["Month:N", "Measure:N", alt.Tooltip("Share:Q", format=".1%")]).properties(height=300)
    show_chart(build, title, "Share of game releases and of lifetime units, by release month")
    cols = st.columns(3)
    cols[0].metric("Holiday share of units", pct(hol_u))
    cols[1].metric("Holiday share of games", pct(hol_g), help="Share of dated releases launched October–December.")
    cols[2].metric("Hit rate · holiday vs. rest of year",
                   f"{pct(dated.loc[hol, 'hit'].mean())} vs. {pct(dated.loc[~hol, 'hit'].mean())}")
    note(8, 5, "assoc")


# --- 6. Regional Taste ---------------------------------------------------------------------------------------------
@st.fragment
def regions_section():
    section("Audiences", "Regional Taste",
            "Do players in North America, Europe and Japan want the same games?")
    exhibit("Genre share of each region's units")
    r = GAMES.groupby("genre")[REG_COLS].sum().rename(columns=REGIONS)
    n = GAMES.groupby("genre").size()
    share = r / r.sum()
    long = share.reset_index().melt("genre", var_name="Region", value_name="Value").rename(columns={"genre": "Genre"})
    long["n"] = long["Genre"].map(n)
    gap = (share["Japan"] - share["North America"]).sort_values()
    title = (f"Japan buys {gap.index[-1]} games far more than North America ({pct(share.loc[gap.index[-1], 'Japan'])} "
             f"vs. {pct(share.loc[gap.index[-1], 'North America'])}); North America leans {gap.index[0]} "
             f"({pct(share.loc[gap.index[0], 'North America'])} vs. {pct(share.loc[gap.index[0], 'Japan'])})")
    show_chart(lambda: heatmap(long, "Region", "Genre", REGION_ORDER, GENRES, "Share of units", ".0%"),
               title, "Share of each region's units by genre, all years (columns sum to 100%)", panel=False)
    note(2, 10)

    exhibit("Top games in a region")
    reg = st.radio("Region", REGION_ORDER, horizontal=True, key="reg_pick")
    col = {v: k for k, v in REGIONS.items()}[reg]
    t = GAMES.nlargest(15, col).copy()
    t["Region share"] = t[col] / t["units"]
    show_table(t[["title", "platform", "year", "pub", "genre", col, "units", "Region share"]], column_config={
        "title": st.column_config.TextColumn("Game", width="medium"), "platform": "Platform",
        "year": st.column_config.NumberColumn("Year", format="%d"), "pub": "Publisher", "genre": "Genre",
        col: st.column_config.NumberColumn(f"{reg} units (M)", format="%.2f",
                                           help=define(reg)),
        "units": st.column_config.NumberColumn("Units, all regions (M)", format="%.2f"),
        "Region share": st.column_config.NumberColumn("Share of the game's units", format="percent",
                                                      help=f"{reg} units ÷ the game's worldwide units.")})
    note(2, 5)


# --- 7. Critics & Sales --------------------------------------------------------------------------------------------
BANDS = ["Under 5", "5–6", "6–7", "7–8", "8–9", "9+"]


def critics_section():
    section("Quality", "Critics & Sales",
            "Do better-reviewed games sell more? Only games with a VGChartz critic score are included.")
    c = GAMES[GAMES["critic_score"].notna()].copy()
    c["Band"] = pd.cut(c["critic_score"], [-0.1, 4.99, 5.99, 6.99, 7.99, 8.99, 10.01], labels=BANDS).astype(str)
    b = c.groupby("Band").agg(Median=("units", "median"), Hit=("hit", "mean"), n=("units", "size")).reindex(BANDS)
    b = b.reset_index()
    hi = b.iloc[-1]
    lo_hit = c[c["critic_score"] < 6]["hit"].mean()
    title = (f"{pct(hi['Hit'])} of games scoring 9+ sold a million, vs. {pct(lo_hit)} of games scoring under 6")
    exhibit("Units and hit rate by critic score")

    def build():
        base = alt.Chart(b).encode(x=alt.X("Band:N", sort=BANDS, title="Critic score (0–10)",
                                           axis=alt.Axis(labelAngle=0)))
        tip = [alt.Tooltip("Band:N", title="Critic score"), alt.Tooltip("Median:Q", format=".2f",
                                                                        title="Median units (M)"),
               alt.Tooltip("Hit:Q", format=".0%", title="Hit rate"), alt.Tooltip("n:Q", title="Games", format=",")]
        bars = base.mark_bar(color=FOCUS, cornerRadiusEnd=3, width={"band": 0.7}).encode(
            y=alt.Y("Hit:Q", title="Hit rate (share selling 1M+)", axis=alt.Axis(format="%")), tooltip=tip)
        lab = base.mark_text(dy=-8, fontSize=11, color=INK).encode(y="Hit:Q", text=alt.Text("Hit:Q", format=".0%"))
        return (bars + lab).properties(height=290)
    show_chart(build, title, "Million-seller rate by critic score band")
    cols = st.columns(len(BANDS))
    for i, r in b.iterrows():
        cols[i].metric(f"Median units · {r['Band']}", units_fmt(r["Median"]),
                       help=f"{int(r['n']):,} games. Median = the middle game (half above, half below).")
    note(12, "assoc")
    st.caption("*Better games may sell more, but bigger publishers also spend more on both development and "
               "marketing, and critics review the games people already expect to be big. The score band is not "
               "a lever on its own.*")


# --- 8. Pitch a Game -----------------------------------------------------------------------------------------------
def comparables(genre, platform, pub, fu, critic, k=8):
    """Closest past games: same genre and platform family, released 2005+, ranked by platform match, follow-up status,
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
            "**How it works:** describe a game you'd greenlight. A random forest fit on games released 2000–2018 "
            "predicts its lifetime units from the choices a publisher makes before launch. Real games missed those "
            "predictions by a known spread, so you get a **range** and a **chance of a million seller**, not a "
            "single number.")
    c1, c2, c3 = st.columns(3)
    genre = c1.selectbox("Genre", GENRE_ORDER, index=GENRE_ORDER.index("Shooter"), key="pitch_genre")
    platform = c2.selectbox("Platform", PITCH_PLATFORMS, index=PITCH_PLATFORMS.index("PS4"),
                            format_func=lambda p: PLATFORM_NAME.get(p, p), key="pitch_platform")
    pub = c3.selectbox("Publisher", PUBS, index=PUBS.index("Ubisoft"), key="pitch_pub", help=define("publisher"))
    c4, c5 = st.columns(2)
    kind = c4.radio("Original or follow-up", ["Original", "Follow-up"], horizontal=True, key="pitch_kind",
                    help=define("follow-up"))
    crit = c5.select_slider("Critic score", ["No score yet", 6, 7, 8, 9], value="No score yet", key="pitch_critic",
                            help="Leave at 'No score yet' for a greenlight decision; pick a score to see what reviews "
                                 "add (that model uses only the ~4,600 games with a score).")
    fu = 1 if kind == "Follow-up" else 0
    critic = None if crit == "No score yet" else float(crit)
    sel = PITCH[(PITCH["genre"] == genre) & (PITCH["platform"] == platform) & (PITCH["pub_group"] == pub)
                & (PITCH["follow_up"] == fu)]
    sel = sel[sel["critic_score"].isna()] if critic is None else sel[sel["critic_score"] == critic]
    if sel.empty:
        st.info("No prediction for that combination.")
        return
    r = sel.iloc[0]
    cols = st.columns(4)
    cols[0].metric("Predicted lifetime units", units_fmt(r["median"]))
    cols[1].metric("Likely range (middle 50%)", f"{units_fmt(r['p25'])}–{units_fmt(r['p75'])}")
    cols[2].metric("10th–90th percentile", f"{units_fmt(r['p10'])}–{units_fmt(r['p90'])}")
    cols[3].metric("Chance of a million seller", pct(r["p_hit"]))
    who = "an independent or smaller publisher" if pub == "Other" else pub
    takeaway(f"A {kind.lower()} {genre.lower()} game on {PLATFORM_NAME.get(platform, platform)} from {who}"
             f"{'' if critic is None else f', reviewed at {critic:.0f}/10'}: typical outcome "
             f"<b>{units_fmt(r['median'])}</b> units, with a <b>{pct(r['p_hit'])} chance</b> of selling a million.")

    sc = pd.DataFrame([{"Case": "Bad case (1 in 10 do worse)", "Units": r["p10"]},
                       {"Case": "Weak (1 in 4)", "Units": r["p25"]}, {"Case": "Typical", "Units": r["median"]},
                       {"Case": "Strong (1 in 4)", "Units": r["p75"]},
                       {"Case": "Great case (1 in 10 do better)", "Units": r["p90"]}])
    title = (f"{pct(r['p_hit'])} chance of a million seller: "
             + ("even the weak case clears 1M" if r["p25"] >= 1 else "the typical case clears 1M" if r["median"] >= 1
                else "only the strong case clears 1M" if r["p75"] >= 1
                else "only the great case clears 1M" if r["p90"] >= 1 else "even the great case falls short of 1M"))

    def build():
        order = list(sc["Case"])
        base = alt.Chart(sc).encode(x=alt.X("Case:N", sort=order, title=None,
                                            axis=alt.Axis(labelAngle=0, labelLimit=150)))
        bars = base.mark_bar(cornerRadiusEnd=3, width={"band": 0.6}).encode(
            y=alt.Y("Units:Q", title="Lifetime units (millions)"),
            color=alt.condition(f"datum.Units >= {HIT_UNITS}", alt.value(FOCUS), alt.value(COMPARE)),
            tooltip=["Case", alt.Tooltip("Units:Q", format=",.2f", title="Units (M)")])
        lab = base.mark_text(fontSize=11, color=INK, dy=-8).encode(y="Units:Q", text=alt.Text("Units:Q", format=".2f"))
        rule = alt.Chart(pd.DataFrame({"y": [HIT_UNITS]})).mark_rule(color=RULE, strokeDash=[4, 3]).encode(y="y:Q")
        return (bars + lab + rule).properties(height=300)
    show_chart(build, title, "Predicted lifetime units across the range of outcomes (dashed line = 1 million; "
                             "blue = clears it)")
    note(13, 14, "assoc")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Comparable games** (same genre and platform family, closest platform, status, publisher and "
                    "year)")
        cmp = comparables(genre, platform, pub, fu, critic)
        show_table(cmp[["title", "platform", "year", "pub", "kind", "critic_score", "units"]], column_config={
            "title": st.column_config.TextColumn("Game", width="medium"), "platform": "Platform",
            "year": st.column_config.NumberColumn("Year", format="%d"), "pub": "Publisher",
            "kind": "Original / follow-up", "critic_score": st.column_config.NumberColumn("Critic", format="%.1f"),
            "units": st.column_config.NumberColumn("Units (M)", format="%.2f")})
    with right:
        st.markdown("**The same pitch on every platform**")
        same = PITCH[(PITCH["genre"] == genre) & (PITCH["pub_group"] == pub) & (PITCH["follow_up"] == fu)]
        same = same[same["critic_score"].isna()] if critic is None else same[same["critic_score"] == critic]
        same = same.assign(Platform=same["platform"].map(lambda p: PLATFORM_NAME.get(p, p)))
        show_table(same.sort_values("median", ascending=False)[["Platform", "median", "p_hit"]], height=300,
                   column_config={"median": st.column_config.NumberColumn("Predicted units (M)", format="%.2f"),
                                  "p_hit": st.column_config.NumberColumn("Chance of a million", format="percent")})
        st.caption("*Everything else held at your choices. Older platforms rank high because their games were sold on "
                   "discs VGChartz could count.*")


# --- 9. Predict the Sales ------------------------------------------------------------------------------------------
FEATURE_NAME = {"follow_up": "Follow-up or original", "year": "Release year", "genre": "Genre",
                "platform": "Platform", "pub_group": "Publisher group", "critic_score": "Critic score"}


def predict_section():
    section("Models", "Predict the Sales",
            "How much of a game's sales can you predict from what is known before launch, and what does adding the "
            "critics' verdict buy you? Two models, each graded on games it never saw.")
    exhibit("How much do the models explain?")
    recs = []
    for fs, e in MODELS.items():
        for m, folds in e["cv"].items():
            recs.append({"Data": f"{fs} ({e['n']:,} games)", "Model": m, "R²": float(np.mean(folds)),
                         "Low": float(np.min(folds)), "High": float(np.max(folds))})
    d = pd.DataFrame(recs)
    best = d.loc[d["R²"].idxmax()]
    g_rf = d[(d["Model"] == "Random forest") & d["Data"].str.startswith("Greenlight (")]["R²"]
    title = (f"Before launch the data explains about {pct(g_rf.iat[0] if len(g_rf) else np.nan)} of the differences "
             f"in units; with critic scores, {pct(best['R²'])} (random forest)")
    data_order = list(dict.fromkeys(d["Data"]))

    def build():
        models = ["Linear regression", "Random forest"]
        base = alt.Chart(d).encode(x=alt.X("Data:N", sort=data_order, title=None,
                                           axis=alt.Axis(labelAngle=0, labelLimit=260)),
                                   xOffset=alt.XOffset("Model:N", sort=models))
        bars = base.mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("R²:Q", title="Cross-validated R²", scale=alt.Scale(domain=[0, 0.6])),
            color=alt.Color("Model:N", sort=models, scale=alt.Scale(domain=models, range=[COMPARE, FOCUS]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["Data:N", "Model:N", alt.Tooltip("R²:Q", format=".2f"),
                     alt.Tooltip("Low:Q", format=".2f", title="Worst fold"),
                     alt.Tooltip("High:Q", format=".2f", title="Best fold")])
        err = base.mark_rule(color=KEYLINE, strokeWidth=1.4).encode(y="Low:Q", y2="High:Q")
        lab = base.mark_text(dy=-10, fontSize=11, color=INK).encode(y="High:Q", text=alt.Text("R²:Q", format=".2f"))
        return (bars + err + lab).properties(height=300)
    show_chart(build, title, "Share of the variation in log lifetime units explained on unseen games "
                             "(bar = average of 5 folds, line = worst to best fold)")
    note(13, 12)

    exhibit("What the random forest relies on")
    fs = st.radio("Feature set", list(MODELS), horizontal=True, key="imp_set")
    imp = pd.DataFrame([{"Feature": FEATURE_NAME.get(k, k), "Importance": v}
                        for k, v in MODELS[fs]["importance"].items()]).sort_values("Importance", ascending=False)
    top = imp.iloc[0]

    def build():
        base = alt.Chart(imp).encode(y=alt.Y("Feature:N", sort=list(imp["Feature"]), title=None))
        bars = base.mark_bar(color=FOCUS, cornerRadiusEnd=3, height={"band": 0.68}).encode(
            x=alt.X("Importance:Q", title="Importance (drop in R² when the feature is scrambled)",
                    axis=alt.Axis(format=".1f", tickCount=5)),
            tooltip=["Feature:N", alt.Tooltip("Importance:Q", format=".3f")])
        lab = base.mark_text(align="left", dx=4, fontSize=11, color=INK).encode(
            x="Importance:Q", text=alt.Text("Importance:Q", format=".2f"))
        return (bars + lab).properties(height=max(170, 36 * len(imp)))
    show_chart(build, f"{top['Feature']} carries the most weight in the {fs.lower()} model",
               "Random forest permutation importance")
    note(13, "assoc")
    st.caption("*Importance says how much the model leans on a feature, not which direction it pushes sales or "
               "whether changing it would change sales. Platform and year partly stand in for how much of the "
               "market VGChartz could see.*")


# --- 10. Game Database ---------------------------------------------------------------------------------------------
@st.fragment
def database_section():
    section("Games", "Game Database",
            "**How it works:** filter the games, sort any column by clicking its header, and download what you see.")
    c1, c2, c3 = st.columns(3)
    query = c1.text_input("Search title, developer or publisher", placeholder="e.g. Zelda, Rockstar, Ubisoft")
    fams = c2.multiselect("Platform family", FAMILY_ORDER, placeholder="All platforms")
    pubs = c3.multiselect("Publisher group", PUBS, placeholder="All publishers")
    c4, c5, c6 = st.columns(3)
    genres = c4.multiselect("Genre", GENRES, placeholder="All genres")
    years = c5.slider("Release year", YEAR_MIN, YEAR_MAX, (YEAR_MIN, YEAR_MAX))
    kind = c6.radio("Original or follow-up", ["All", "Original", "Follow-up"], horizontal=True,
                    help=define("follow-up"))
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
    v = v[v["year"].between(*years)].sort_values("units", ascending=False)
    show_table(v[["title", "platform", "year", "pub", "developer", "genre", "kind", "critic_score", "na_sales",
                  "eu_sales", "jp_sales", "other_sales", "units"]], height=380, column_config={
        "title": st.column_config.TextColumn("Title", width="medium"), "platform": "Platform",
        "year": st.column_config.NumberColumn("Year", format="%d"), "pub": "Publisher", "developer": "Developer",
        "genre": "Genre", "kind": "Original / follow-up",
        "critic_score": st.column_config.NumberColumn("Critic", format="%.1f"),
        "na_sales": st.column_config.NumberColumn("North America (M)", format="%.2f"),
        "eu_sales": st.column_config.NumberColumn("Europe (M)", format="%.2f"),
        "jp_sales": st.column_config.NumberColumn("Japan (M)", format="%.2f"),
        "other_sales": st.column_config.NumberColumn("Rest of world (M)", format="%.2f"),
        "units": st.column_config.NumberColumn("Units (M)", format="%.2f")})
    st.caption(f"*{len(v):,} of {len(GAMES):,} games match. Source: VGChartz. " + NOTE[4] + " " + NOTE[1] + "*")
    st.download_button(f"⬇ Download these {len(v):,} games (CSV)",
                       (lambda: csv_bytes(v)) if _LAZY_DOWNLOAD else csv_bytes(v), "game_sales_lab_games.csv",
                       "text/csv", on_click="ignore")


# --- Sidebar: menu + glossary ---------------------------------------------------------------------------------------
GLOSSARY = {
    "Units": define("units"),
    "Million seller (hit)": define("million-seller"),
    "Hit rate": define("hit rate"),
    "Publisher group": define("publisher"),
    "Follow-up": define("follow-up"),
    "Platform family": "The console maker: PlayStation, Nintendo, Xbox, PC, Sega or Other.",
    "Boxed retail": "Physical copies sold in stores. VGChartz tracks these; downloads are largely missing.",
    "Critic score": define("critic"),
    "Holiday release": define("holiday"),
    "R²": define("r²"),
    "Cross-validation": "Scoring a model on games it didn't learn from, several times over, for an honest grade.",
    "Importance": define("importance"),
}
with st.sidebar:
    st.markdown("### Sections")
    st.markdown("\n".join(f"{NAV_NUM[t]}. [{t}](#{a})" for t, a in NAV.items()))
    st.markdown("### Glossary")
    for term, text in GLOSSARY.items():
        st.markdown(f"**{term}**  \n<span style='color:{MUTED};font-size:.85rem'>{text}</span>",
                    unsafe_allow_html=True)

# --- Page: one long scroll, in NAV order -----------------------------------------------------------------------------
market_section()        # 1
winning_section()       # 2
fatigue_section()       # 3
st.markdown("<div class='deeper'><b>Go deeper.</b> That's the end of the in-class stops. The sections below are the "
            "full lab for your write-up: publisher playbooks, platforms and release timing, regional taste and the "
            "critics.</div>", unsafe_allow_html=True)
publishers_section()    # 4
platforms_section()     # 5
regions_section()       # 6
critics_section()       # 7
st.markdown("<div class='deeper'><b>Build your pitch.</b> Pitch your own game, see how far prediction gets you, and "
            "look up any game in the data.</div>", unsafe_allow_html=True)
pitch_section()         # 8
predict_section()       # 9
database_section()      # 10
