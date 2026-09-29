# Matrix Portal M4 + 64x32 matrix (liggend of staand): Game of Life  <->  roterend dashboard
#
# Knoppen op het bordje:
#   UP / DOWN kort        -> Life: sneller / langzamer   ·   dashboard: volgend / vorig scherm
#   UP of DOWN lang       -> wissel tussen Game of Life en dashboard
#   UP + DOWN tegelijk    -> Life: nieuwe wereld   ·   dashboard: volgend scherm
# Externe knop (A1 naar GND, optioneel): kort = wisselen, lang = nieuwe wereld / volgend scherm
import gc
import time
import board
import displayio
import framebufferio
import keypad
import rgbmatrix
import adafruit_ticks as ticks

# ------------------------------------------------------------ instellingen
AUTO_ROTATE = True         # stand bepalen met de accelerometer; draai je het paneel, dan draait het beeld mee
# Vaste stand, als AUTO_ROTATE uit staat of het paneel plat ligt:
PORTRAIT = True            # True = staand (32 breed, 64 hoog), False = liggend (64x32)
FLIP = True                # True als het beeld op z'n kop staat (True = bordje onderaan)
BRIGHTNESS = 0.7           # 0.1 .. 1.0 (kleuren worden gedimd, zeer donker = soms onzichtbaar)
START_MODE = "life"        # "life" of "dashboard"
BUTTON_PIN = board.A1      # externe knop: tussen deze pin en GND
LONG_PRESS_MS = 800

# Snelheden van Game of Life in ms per generatie (snelste eerst). Het bordje heeft
# zelf ~170 ms nodig per generatie, dus 0 = zo snel als het kan.
LIFE_SPEEDS_MS = (0, 300, 500, 800, 1200, 2000)
LIFE_SPEED = 1             # startsnelheid: index in LIFE_SPEEDS_MS
LIFE_MAX_GENS = None       # None = geen limiet: een wereld loopt tot hij echt vastloopt of zich herhaalt

# Volgorde van het dashboard. Elke "gif" speelt de volgende GIF: na elk scherm een GIF.
ORDER = ("clock", "gif", "air", "gif", "weather", "gif", "forecast", "gif", "world", "gif")
# Seconden per scherm. Een GIF speelt minstens één keer helemaal, en maximaal 2x zo lang.
DURATIONS = {"clock": 20, "air": 10, "weather": 10, "forecast": 10, "world": 10, "gif": 10}

# Tijdzones: (standaard UTC-offset in uren, zomertijdregel "EU" / "US" / "AU" / None)
HOME_TZ = (1, "EU")        # Amsterdam: UTC+1, zomertijd volgens EU-regels
WORLD_CLOCKS = (           # max. 4; namen van max. 8 letters passen staand het best
    ("NEW YORK", -5, "US"),
    ("LONDEN", 0, "EU"),
    ("TOKIO", 9, None),
    ("SYDNEY", 10, "AU"),
)
AIR_GRAPH_MINUTES = 120    # hoeveel tijd de CO2-grafiek beslaat
CO2_ALERT_PPM = 1200       # vanaf hier knippert er een rood puntje tijdens Game of Life
# -------------------------------------------------------------------------

from net import Net
from air import Air
from life import Life
from dashboard import Dashboard
from orientation import Orientation

orientation = Orientation() if AUTO_ROTATE else None
rotation = orientation and orientation.current
if rotation is None:
    rotation = (90 if PORTRAIT else 0) + (180 if FLIP else 0)
print("Rotatie:", rotation)

displayio.release_displays()
matrix = rgbmatrix.RGBMatrix(
    width=64, height=32, bit_depth=4,
    rgb_pins=[board.MTX_R1, board.MTX_G1, board.MTX_B1,
              board.MTX_R2, board.MTX_G2, board.MTX_B2],
    addr_pins=[board.MTX_ADDRA, board.MTX_ADDRB, board.MTX_ADDRC, board.MTX_ADDRD],
    clock_pin=board.MTX_CLK, latch_pin=board.MTX_LAT, output_enable_pin=board.MTX_OE)
display = framebufferio.FramebufferDisplay(
    matrix, auto_refresh=True, rotation=rotation)


class Buttons:
    """Vertaalt knoppen naar acties: 'switch', 'next', 'prev' en 'reset'.

    UP / DOWN (op het bordje): kort = 'next' / 'prev', lang = 'switch',
    allebei tegelijk = 'reset'. Externe knop: kort = 'switch', lang = 'reset'.
    """
    EXTERNAL, UP, DOWN = 0, 1, 2

    def __init__(self, pins, long_ms):
        self.keys = keypad.Keys(pins, value_when_pressed=False, pull=True)
        self.long_ms = long_ms
        self.down_since = {}  # knop -> tijdstip, of None als hij al iets gedaan heeft
        self.event = keypad.Event()

    def poll(self):
        actions = []
        held = self.down_since
        while self.keys.events.get_into(self.event):
            k = self.event.key_number
            if self.event.pressed:
                held[k] = self.event.timestamp
                if self.UP in held and self.DOWN in held:
                    held[self.UP] = held[self.DOWN] = None
                    actions.append("reset")
            elif k in held:
                if held.pop(k) is not None:  # kort ingedrukt
                    actions.append({self.EXTERNAL: "switch", self.UP: "next",
                                    self.DOWN: "prev"}[k])
        now = ticks.ticks_ms()
        for k, since in held.items():
            if since is not None and ticks.ticks_diff(now, since) >= self.long_ms:
                held[k] = None
                actions.append("reset" if k == self.EXTERNAL else "switch")
        return actions


def build_screens(life_speed):
    """(Opnieuw) de schermen maken voor de huidige breedte/hoogte van het display."""
    portrait = display.height > display.width
    # Staande en liggende GIFs hebben elk een eigen map
    gifs = "/gifs_staand" if portrait else "/gifs"
    dash = Dashboard(display, net, air, BRIGHTNESS, ORDER, DURATIONS, gifs, HOME_TZ, WORLD_CLOCKS)
    lf = Life(display, BRIGHTNESS, LIFE_SPEEDS_MS, life_speed, LIFE_MAX_GENS, air, CO2_ALERT_PPM)
    return dash, lf


def rotate(new_rotation):
    """Beeld meedraaien zonder herstart. Wifi, weer, tijd en CO2-grafiek blijven bewaard."""
    global dashboard, life, mode
    was_life = mode is life
    old_portrait = display.height > display.width
    display.rotation = new_rotation
    print("Gedraaid naar", new_rotation)
    if (display.height > display.width) == old_portrait:
        mode.enter()  # 180 graden: zelfde afmetingen, alles loopt gewoon door
        return
    # Staand <-> liggend: andere afmetingen, schermen opnieuw opbouwen
    speed = life.speed
    screen = dashboard.index  # op hetzelfde dashboardscherm verdergaan
    dashboard.gifs.stop()
    display.root_group = None
    dashboard = life = mode = None
    gc.collect()
    air.set_width(display.width)
    dashboard, life = build_screens(speed)
    dashboard.index = screen % len(dashboard.order)
    mode = life if was_life else dashboard
    mode.enter()
    gc.collect()
    print("Schermen opnieuw opgebouwd, vrij geheugen:", gc.mem_free())


net = Net()
air = Air(AIR_GRAPH_MINUTES, display.width)
mode = None
dashboard, life = build_screens(LIFE_SPEED)
dashboard.message(("WIFI", "..."), 6)
net.update()
buttons = Buttons((BUTTON_PIN, board.BUTTON_UP, board.BUTTON_DOWN), LONG_PRESS_MS)

mode = dashboard if START_MODE == "dashboard" else life
mode.enter()

while True:
    for action in buttons.poll():
        if action == "switch":
            mode = dashboard if mode is life else life
            mode.enter()
        else:
            mode.handle(action)
    air.tick()
    mode.tick()
    if orientation:
        new_rotation = orientation.changed()
        if new_rotation is not None:
            rotate(new_rotation)
    if mode is dashboard:
        time.sleep(0.01)
