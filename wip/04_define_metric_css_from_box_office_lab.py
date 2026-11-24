def define(label):
    """Hover definition for a measure's label, or None. 'Median ...' labels say so."""
    low = str(label).lower()
    for key, text in DEFINE_RULES:
        if key in low:
            if low.startswith("median") or "· follow-up vs. original" in low:
                text = "Median = the middle film (half above, half below), which ignores a few huge outliers. " + text
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
