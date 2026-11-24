
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
# Each publisher group keeps one color in every chart (the Box Office Lab's validated studio colors plus a green).
# Sega is white, so its marks get a charcoal keyline and its text is charcoal.
PUB_COLOR = {"Nintendo": "#c2185b", "Electronic Arts": "#e5631f", "Activision": "#7d8899", "Sony": "#8e3aa8",
             "Ubisoft": "#7a5216", "Take-Two": "#d9a900", "Microsoft": "#1b7a4b", "Sega": "#ffffff"}
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
