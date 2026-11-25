"""Shared lookups for build_data.py and enrich/build_extended.py: platforms, genres, publisher groups, franchise keys.
Kept in one place so the VGChartz data and the 2019+ layers group publishers and platforms the same way."""
import re
import unicodedata

HIT_UNITS = 1.0   # million-seller

# --- Platforms: family, generation, handheld --------------------------------------------------------------------
PLATFORMS = {  # code: (name, family, generation, handheld)
    "2600": ("Atari 2600", "Other", 2, 0), "NES": ("NES", "Nintendo", 3, 0), "GB": ("Game Boy", "Nintendo", 4, 1),
    "SNES": ("SNES", "Nintendo", 4, 0), "GEN": ("Genesis", "Sega", 4, 0), "GG": ("Game Gear", "Sega", 4, 1),
    "SCD": ("Sega CD", "Sega", 4, 0), "NG": ("Neo Geo", "Other", 4, 0), "TG16": ("TurboGrafx-16", "Other", 4, 0),
    "PS": ("PlayStation", "PlayStation", 5, 0), "N64": ("Nintendo 64", "Nintendo", 5, 0),
    "SAT": ("Saturn", "Sega", 5, 0), "3DO": ("3DO", "Other", 5, 0), "GBC": ("Game Boy Color", "Nintendo", 5, 1),
    "WS": ("WonderSwan", "Other", 5, 1), "PCFX": ("PC-FX", "Other", 5, 0),
    "DC": ("Dreamcast", "Sega", 6, 0), "PS2": ("PlayStation 2", "PlayStation", 6, 0), "XB": ("Xbox", "Xbox", 6, 0),
    "GC": ("GameCube", "Nintendo", 6, 0), "GBA": ("Game Boy Advance", "Nintendo", 6, 1),
    "DS": ("Nintendo DS", "Nintendo", 7, 1), "PSP": ("PSP", "PlayStation", 7, 1), "Wii": ("Wii", "Nintendo", 7, 0),
    "X360": ("Xbox 360", "Xbox", 7, 0), "PS3": ("PlayStation 3", "PlayStation", 7, 0),
    "3DS": ("Nintendo 3DS", "Nintendo", 8, 1), "PSV": ("PS Vita", "PlayStation", 8, 1),
    "WiiU": ("Wii U", "Nintendo", 8, 0), "PS4": ("PlayStation 4", "PlayStation", 8, 0),
    "XOne": ("Xbox One", "Xbox", 8, 0), "NS": ("Switch", "Nintendo", 8, 1),
    "PS5": ("PlayStation 5", "PlayStation", 9, 0), "XS": ("Xbox Series", "Xbox", 9, 0), "PC": ("PC", "PC", 0, 0),
}

# --- Genres: the main eight keep their own color, the rest are Other ----------------------------------------------
GENRE_MAP = {"Action-Adventure": "Action", "Party": "Misc", "Music": "Misc", "Education": "Misc",
             "Board Game": "Misc", "Sandbox": "Misc", "Visual Novel": "Adventure", "MMO": "Role-Playing"}
MAIN_GENRES = ["Action", "Sports", "Shooter", "Role-Playing", "Platform", "Racing", "Misc", "Simulation"]

# --- Publishers: labels rolled up to the parent group (as of the data's years, not today's owners) ----------------
PUB_RULES = [
    ("Nintendo", r"^nintendo|the pokemon company"),
    ("Electronic Arts", r"electronic arts|^ea |^ea$|ea sports|ea games|ea canada"),
    ("Activision", r"activision|blizzard|treyarch|infinity ward|vivendi|sierra"),
    ("Sony", r"sony|scea|scee|sce |playstation"),
    ("Ubisoft", r"ubisoft|red storm"),
    ("Take-Two", r"take-two|take two|rockstar|2k|global star"),
    ("Microsoft", r"microsoft|xbox game studios"),
    ("Sega", r"^sega|atlus"),
    ("Square Enix", r"square|enix|eidos"),
    ("Bandai Namco", r"namco|bandai"),
    ("Konami", r"konami"),
    ("Capcom", r"capcom"),
    ("Warner Bros.", r"warner"),
    ("THQ", r"^thq"),
    ("Bethesda", r"bethesda|zenimax"),
    ("Disney", r"disney|lucasarts|buena vista"),
]
PUB_ORDER = ["Nintendo", "Electronic Arts", "Activision", "Sony", "Ubisoft", "Take-Two", "Microsoft", "Sega"]


def pub_group(p):
    # Accents removed first, so "The Pokémon Company" matches the same rule as "The Pokemon Company"
    low = unicodedata.normalize("NFKD", str(p)).encode("ascii", "ignore").decode().lower()
    for name, pat in PUB_RULES:
        if re.search(pat, low):
            return name
    return str(p)


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


ROMAN = r"(?:ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii)"


def series_of(title):
    """Franchise key: the title before a subtitle, without a trailing number, year or roman numeral.
    'Call of Duty: Black Ops' -> 'call of duty'; 'FIFA 18' -> 'fifa'; 'Grand Theft Auto V' -> 'grand theft auto'."""
    t = unicodedata.normalize("NFKD", str(title)).encode("ascii", "ignore").decode().lower()
    t = re.split(r"\s*:\s*|\s+[-–]\s+|\s*\(", t)[0]
    t = re.sub(rf"\s+(\d{{1,4}}|{ROMAN}|20\d\d|'\d\d)\b.*$", "", t)
    t = re.sub(r"[^a-z0-9 &']", "", t).strip()
    return SERIES_ALIAS.get(t, t)


SERIES_ALIAS = {"fifa soccer": "fifa", "fifa street": "fifa", "spiderman": "spider-man", "madden": "madden nfl",
                "pokemon mystery dungeon": "pokemon", "tom clancy's ghost recon": "ghost recon",
                "tom clancy's rainbow six": "rainbow six", "tom clancy's splinter cell": "splinter cell"}
