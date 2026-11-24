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

