# gfx.py - kleuren, mini-lettertype (3x5), weer-iconen en de maan.
# Bevat bewust geen displayio: alles tekent op een "bitmap" met bmp[x, y] = kleurindex.
import math

# Kleurindexen van het dashboard-canvas
(BLACK, WHITE, GREY, YELLOW, ORANGE, BLUE, LIGHTBLUE, CLOUD,
 DARKGREY, RED, GREEN, MOON, MOON_DARK, MOON_SHADE, CYAN, DIM) = range(16)

COLORS = (
    0x000000,  # BLACK
    0xFFFFFF,  # WHITE
    0x707070,  # GREY
    0xFFC820,  # YELLOW
    0xFF6A00,  # ORANGE
    0x1848FF,  # BLUE
    0x50A8FF,  # LIGHTBLUE
    0xB8B8C8,  # CLOUD
    0x383838,  # DARKGREY
    0xFF2020,  # RED
    0x20E040,  # GREEN
    0xFFF2C8,  # MOON
    0x282838,  # MOON_DARK
    0xB0A488,  # MOON_SHADE
    0x00D8D8,  # CYAN
    0x202020,  # DIM
)


def scale(color, amount):
    """Maak een 0xRRGGBB-kleur donkerder (amount 0..1)."""
    r = int(((color >> 16) & 0xFF) * amount)
    g = int(((color >> 8) & 0xFF) * amount)
    b = int((color & 0xFF) * amount)
    return (r << 16) | (g << 8) | b


def fill_rect(bmp, x, y, w, h, color):
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, bmp.width), min(y + h, bmp.height)
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            bmp[xx, yy] = color


# ---------------------------------------------------------------- lettertype
# Per teken: het teken zelf + 15 bits (5 rijen van 3 pixels, linksboven eerst).
_FONT_DATA = (
    "0111101101101111", "1010110010010111", "2111001111100111", "3111001111001111",
    "4101101111001001", "5111100111001111", "6111100111101111", "7111001010010010",
    "8111101111101111", "9111101111001111",
    "A010101111101101", "B110101110101110", "C011100100100011", "D110101101101110",
    "E111100110100111", "F111100110100100", "G011100101101011", "H101101111101101",
    "I111010010010111", "J001001001101010", "K101101110101101", "L100100100100111",
    "M101111111101101", "N110101101101101", "O010101101101010", "P110101110100100",
    "Q010101101110011", "R110101110101101", "S011100010001110", "T111010010010010",
    "U101101101101111", "V101101101101010", "W101101111111101", "X101101010101101",
    "Y101101010010010", "Z111001010100111",
    " 000000000000000", ":000010000010000", "-000000111000000", ".000000000000010",
    "/001001010100100", "%101001010100101", "°010101010000000", "+000010111010000",
    "!010010010000010", "?110001010000010", "↑010111010010010", "↓010010010111010",
)
FONT = {s[0]: int(s[1:], 2) for s in _FONT_DATA}
# Smalle tekens (alleen de middelste kolom wordt gebruikt)
_ADVANCE = {" ": 2, ":": 2, ".": 2, "!": 2}


def text_width(text, scale_=1):
    if not text:
        return 0
    return (sum(_ADVANCE.get(ch, 4) for ch in text) - 1) * scale_


def draw_text(bmp, text, x, y, color, scale_=1):
    """Teken tekst met linkerbovenhoek op (x, y). Geeft de x na de tekst terug."""
    for ch in text:
        adv = _ADVANCE.get(ch, 4)
        bits = FONT.get(ch) or FONT.get(ch.upper())
        if bits:
            ox = x - scale_ if adv == 2 else x
            for i in range(15):
                if (bits >> (14 - i)) & 1:
                    fill_rect(bmp, ox + (i % 3) * scale_, y + (i // 3) * scale_,
                              scale_, scale_, color)
        x += adv * scale_
    return x


def draw_text_centered(bmp, text, cx, y, color, scale_=1):
    return draw_text(bmp, text, cx - text_width(text, scale_) // 2, y, color, scale_)


def draw_parts(bmp, parts, cx, y, scale_=1):
    """Tekst in meerdere kleuren, gecentreerd: parts = ((tekst, kleur), ...)."""
    x = cx - text_width("".join(p[0] for p in parts), scale_) // 2
    for text, color in parts:
        x = draw_text(bmp, text, x, y, color, scale_)


# ------------------------------------------------------------------ iconen
# Lagen van 12x12; '.' is transparant. Een icoon is een stapel lagen met offset.
_LAYERS = {
    "sun": (
        ".....YY.....",
        ".Y...YY...Y.",
        "..Y......Y..",
        "....OOOO....",
        "...OYYYYO...",
        "YY.OYYYYO.YY",
        "YY.OYYYYO.YY",
        "...OYYYYO...",
        "....OOOO....",
        "..Y......Y..",
        ".Y...YY...Y.",
        ".....YY.....",
    ),
    "moon": (
        "............",
        "....MMMM....",
        "..MMMM......",
        ".MMMM.......",
        ".MMM........",
        ".MMM........",
        ".MMM........",
        ".MMMM.......",
        "..MMMM......",
        "....MMMM....",
        "............",
        "............",
    ),
    "cloud": (
        "............",
        "............",
        "............",
        ".....WWW....",
        "...WWWWWW...",
        "..WWWWWWWWW.",
        ".WWWWWWWWWWW",
        ".GGGGGGGGGGG",
        "..GGGGGGGGG.",
        "............",
        "............",
        "............",
    ),
    "rain": (
        "............", "............", "............", "............",
        "............", "............", "............",
        "..L...L...L.",
        ".L...L...L..",
        "............",
        "....L...L...",
        "...L...L....",
    ),
    "snow": (
        "............", "............", "............", "............",
        "............", "............", "............",
        "..W....W....",
        "............",
        "....W....W..",
        "............",
        ".W....W.....",
    ),
    "bolt": (
        "............", "............", "............", "............", "............",
        "......YY....",
        ".....YY.....",
        "....YYYY....",
        "......Y.....",
        ".....Y......",
        "....Y.......",
        "............",
    ),
    "fog": (
        "............",
        "............",
        "............",
        "GGGGGGGG....",
        "............",
        "..GGGGGGGGGG",
        "............",
        "GGGGGGGGGG..",
        "............",
        "...GGGGGGGG.",
        "............",
        "............",
    ),
}
_CHAR_COLORS = {"Y": YELLOW, "O": ORANGE, "W": WHITE, "G": CLOUD, "L": LIGHTBLUE, "M": MOON}
_GREY_CLOUD = {"W": CLOUD, "G": GREY}
_STORM_CLOUD = {"W": GREY, "G": DARKGREY}

# (laag, dx, dy, kleurvervanging)
_RECIPES = {
    "clear": (("sun", 0, 0, None),),
    "partly": (("sun", -1, -1, None), ("cloud", 1, 4, None)),
    "cloudy": (("cloud", -1, -2, _GREY_CLOUD), ("cloud", 1, 2, None)),
    "fog": (("fog", 0, 0, None),),
    "rain": (("cloud", 0, -3, None), ("rain", 0, 0, None)),
    "snow": (("cloud", 0, -3, None), ("snow", 0, 0, None)),
    "storm": (("cloud", 0, -3, _STORM_CLOUD), ("bolt", 0, 0, None)),
}


def weather_kind(code):
    """WMO-weercode (Open-Meteo) -> icoonnaam."""
    if code <= 1:
        return "clear"
    if code == 2:
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    return "rain"


def draw_icon(bmp, kind, x, y, scale_=1, night=False):
    for name, dx, dy, recolor in _RECIPES.get(kind, _RECIPES["cloudy"]):
        if night and name == "sun":
            name = "moon"
        for ry, row in enumerate(_LAYERS[name]):
            yy = ry + dy
            if not 0 <= yy < 12:
                continue
            for rx, ch in enumerate(row):
                xx = rx + dx
                if ch == "." or not 0 <= xx < 12:
                    continue
                color = recolor[ch] if recolor and ch in recolor else _CHAR_COLORS[ch]
                fill_rect(bmp, x + xx * scale_, y + yy * scale_, scale_, scale_, color)


# -------------------------------------------------------------------- maan
_NEW_MOON = 947182440  # 6 jan 2000 18:14 UTC, een bekende nieuwe maan
_SYNODIC = 29.530588853
# Een paar "zeeën" op de maan (x, y, straal), genormaliseerd op -1..1
_CRATERS = ((-0.35, -0.25, 0.24), (0.25, 0.2, 0.18), (-0.1, 0.5, 0.15),
            (0.35, -0.4, 0.12), (-0.5, 0.2, 0.1))


def moon_phase(unix_utc):
    """0 = nieuwe maan, 0.25 = eerste kwartier, 0.5 = vol, 0.75 = laatste kwartier."""
    days = (unix_utc - _NEW_MOON) / 86400
    return (days % _SYNODIC) / _SYNODIC


def draw_moon(bmp, cx, cy, r, phase):
    """Maan met straal r; pixels cx-r .. cx+r-1. Wassend = rechts verlicht (NL)."""
    k = math.cos(2 * math.pi * phase)
    waxing = phase < 0.5
    for py in range(-r, r):
        ny = (py + 0.5) / r
        edge = math.sqrt(max(0.0, 1 - ny * ny)) * k
        for px in range(-r, r):
            nx = (px + 0.5) / r
            if nx * nx + ny * ny > 1:
                continue
            lit = nx > edge if waxing else nx < -edge
            color = MOON_DARK
            if lit:
                color = MOON
                for mx, my, mr in _CRATERS:
                    if (nx - mx) ** 2 + (ny - my) ** 2 < mr * mr:
                        color = MOON_SHADE
                        break
            bmp[cx + px, cy + py] = color
