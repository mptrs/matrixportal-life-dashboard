# Matrix Portal M4 + 64x32 matrix (landscape or portrait): Game of Life  <->  rotating dashboard
#
# Buttons on the board:
#   UP / DOWN short       -> Life: faster / slower   ·   dashboard: next / previous screen
#   UP or DOWN long       -> switch between Game of Life and the dashboard
#   UP + DOWN together    -> Life: new world   ·   dashboard: next screen
# External button (A1 to GND, optional): short = switch, long = new world / next screen
import gc
import time
import board
import displayio
import framebufferio
import keypad
import rgbmatrix
import adafruit_ticks as ticks

# ---------------------------------------------------------------- settings
AUTO_ROTATE = True         # follow the accelerometer: turn the panel and the image turns with it
# Fixed orientation, used when AUTO_ROTATE is off or the panel lies flat:
PORTRAIT = True            # True = portrait (32 wide, 64 high), False = landscape (64x32)
FLIP = True                # True if the image is upside down (True = board at the bottom)
BRIGHTNESS = 0.7           # 0.1 .. 1.0 (colors are dimmed; very dark colors may disappear)
START_MODE = "life"        # "life" or "dashboard"
BUTTON_PIN = board.A1      # external button: between this pin and GND
LONG_PRESS_MS = 800

# Game of Life speeds in ms per generation (fastest first). The board itself needs
# ~170 ms per generation, so 0 = as fast as it can.
LIFE_SPEEDS_MS = (0, 300, 500, 800, 1200, 2000)
LIFE_SPEED = 1             # starting speed: index into LIFE_SPEEDS_MS
LIFE_MAX_GENS = None       # None = no limit: a world runs until it is truly finished (repeats itself)

# Dashboard order. Each "gif" plays the next GIF: a GIF after every screen.
ORDER = ("clock", "gif", "air", "gif", "weather", "gif", "forecast", "gif", "world", "gif")
# Seconds per screen. A GIF always plays at least once completely, and at most 2x this long.
DURATIONS = {"clock": 20, "air": 10, "weather": 10, "forecast": 10, "world": 10, "gif": 10}

# Timezones: (standard UTC offset in hours, DST rule "EU" / "US" / "AU" / None)
HOME_TZ = (1, "EU")        # e.g. Amsterdam: UTC+1 with EU daylight saving time
WORLD_CLOCKS = (           # max. 4; names of up to 8 letters fit best in portrait
    ("NEW YORK", -5, "US"),
    ("LONDON", 0, "EU"),
    ("TOKYO", 9, None),
    ("SYDNEY", 10, "AU"),
)
AIR_GRAPH_MINUTES = 120    # time span of the CO2 graph
CO2_ALERT_PPM = 1200       # above this, a red dot blinks during Game of Life
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
print("Rotation:", rotation)

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
    """Turns button presses into actions: 'switch', 'next', 'prev' and 'reset'.

    UP / DOWN (on the board): short = 'next' / 'prev', long = 'switch',
    both together = 'reset'. External button: short = 'switch', long = 'reset'.
    """
    EXTERNAL, UP, DOWN = 0, 1, 2

    def __init__(self, pins, long_ms):
        self.keys = keypad.Keys(pins, value_when_pressed=False, pull=True)
        self.long_ms = long_ms
        self.down_since = {}  # button -> press time, or None once it has triggered an action
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
                if held.pop(k) is not None:  # short press
                    actions.append({self.EXTERNAL: "switch", self.UP: "next",
                                    self.DOWN: "prev"}[k])
        now = ticks.ticks_ms()
        for k, since in held.items():
            if since is not None and ticks.ticks_diff(now, since) >= self.long_ms:
                held[k] = None
                actions.append("reset" if k == self.EXTERNAL else "switch")
        return actions


def build_screens(life_speed):
    """(Re)build the screens for the current width/height of the display."""
    portrait = display.height > display.width
    # Portrait and landscape GIFs each have their own folder
    gifs = "/gifs_portrait" if portrait else "/gifs_landscape"
    dash = Dashboard(display, net, air, BRIGHTNESS, ORDER, DURATIONS, gifs, HOME_TZ, WORLD_CLOCKS)
    lf = Life(display, BRIGHTNESS, LIFE_SPEEDS_MS, life_speed, LIFE_MAX_GENS, air, CO2_ALERT_PPM)
    return dash, lf


def rotate(new_rotation):
    """Rotate the image without a restart. WiFi, weather, time and the CO2 graph are kept."""
    global dashboard, life, mode
    was_life = mode is life
    old_portrait = display.height > display.width
    display.rotation = new_rotation
    print("Rotated to", new_rotation)
    if (display.height > display.width) == old_portrait:
        mode.enter()  # 180 degrees: same size, everything simply continues
        return
    # Portrait <-> landscape: different size, rebuild the screens
    speed = life.speed
    screen = dashboard.index  # continue on the same dashboard screen
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
    print("Screens rebuilt, free memory:", gc.mem_free())


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
