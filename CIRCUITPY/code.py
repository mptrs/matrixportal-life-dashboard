# Matrix Portal M4 + 64x32 matrix (landscape or portrait): Game of Life  <->  rotating dashboard
#
# Buttons on the board:
#   UP / DOWN short       -> Life: faster / slower   ·   dashboard: next / previous screen
#   UP or DOWN long       -> switch between Game of Life and the dashboard
#   UP + DOWN together    -> Life: new world   ·   dashboard: next screen
#   UP + DOWN hold 2 s    -> standby (screen off); any button wakes it up
# External button (A1 to GND, optional): short = switch, long = new world / next screen
import gc
import os
import time
import board
import displayio
import framebufferio
import keypad
import rgbmatrix
import adafruit_ticks as ticks
import tz

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

# Standby (screen off). Hold UP + DOWN to enter it manually; any button wakes it up.
# The night times (automatic standby) are set in settings.toml: NIGHT_START / NIGHT_END.
STANDBY_HOLD_MS = 2000
NIGHT_WAKE_MINUTES = 10    # woken up at night: back to standby after this long without a button press
# -------------------------------------------------------------------------



def _clock_setting(name, default):
    """Read "HH:MM" from settings.toml as (hour, minute); an empty value means off."""
    text = os.getenv(name, default)
    if not text:
        return None
    hour, minute = text.split(":")
    return int(hour), int(minute)


NIGHT_START = _clock_setting("NIGHT_START", "22:00")
NIGHT_END = _clock_setting("NIGHT_END", "08:00")

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
    """Turns button presses into actions: 'switch', 'next', 'prev', 'reset' and 'standby'.

    UP / DOWN (on the board): short = 'next' / 'prev', long = 'switch',
    both together = 'reset', both held for STANDBY_HOLD_MS = 'standby'.
    External button: short = 'switch', long = 'reset'.
    """
    EXTERNAL, UP, DOWN = 0, 1, 2

    def __init__(self, pins, long_ms, standby_ms):
        self.keys = keypad.Keys(pins, value_when_pressed=False, pull=True)
        self.long_ms = long_ms
        self.standby_ms = standby_ms
        self.down_since = {}  # button -> press time, or None once it has triggered an action
        self.pressed = set()  # buttons that are physically down right now
        self.combo_since = None  # time UP + DOWN were both pressed
        self.combo_fired = False
        self.muted = False  # ignore everything until all buttons are released
        self.any_press = False  # was any button pressed during the last poll?
        self.event = keypad.Event()

    def mute_until_released(self):
        """Forget the current press (used after waking up, so it does nothing else)."""
        self.down_since.clear()
        self.combo_since = None
        self.muted = bool(self.pressed)

    def poll(self):
        actions = []
        held = self.down_since
        self.any_press = False
        while self.keys.events.get_into(self.event):
            k = self.event.key_number
            if self.event.pressed:
                self.pressed.add(k)
                self.any_press = True
                if self.muted:
                    continue
                held[k] = self.event.timestamp
                if self.UP in held and self.DOWN in held:
                    held[self.UP] = held[self.DOWN] = None
                    self.combo_since = self.event.timestamp
                    self.combo_fired = False
            else:
                self.pressed.discard(k)
                if self.muted:
                    held.pop(k, None)
                    self.muted = bool(self.pressed)
                    continue
                if k in held and held.pop(k) is not None:  # short press
                    actions.append({self.EXTERNAL: "switch", self.UP: "next",
                                    self.DOWN: "prev"}[k])
                if self.combo_since is not None and k in (self.UP, self.DOWN):
                    if not self.combo_fired:  # UP + DOWN released before the standby time
                        actions.append("reset")
                    self.combo_since = None
        now = ticks.ticks_ms()
        if (self.combo_since is not None and not self.combo_fired
                and ticks.ticks_diff(now, self.combo_since) >= self.standby_ms):
            self.combo_fired = True
            actions.append("standby")
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
def is_night():
    """True during the night period, None if the time is not known (yet)."""
    now = net.now()
    if NIGHT_START is None or NIGHT_END is None or now is None:
        return None
    local = now + tz.utc_offset(now, *HOME_TZ)
    minute = (local // 60) % 1440
    start = NIGHT_START[0] * 60 + NIGHT_START[1]
    end = NIGHT_END[0] * 60 + NIGHT_END[1]
    if start <= end:
        return start <= minute < end
    return minute >= start or minute < end  # across midnight, e.g. 22:00 - 08:00


def set_standby(on):
    global standby
    standby = on
    if on:
        dashboard.gifs.stop()
        display.root_group = blank
        display.brightness = 0  # the matrix is fully off
        print("Standby on")
    else:
        display.brightness = 1
        mode.enter()
        print("Standby off")


buttons = Buttons((BUTTON_PIN, board.BUTTON_UP, board.BUTTON_DOWN), LONG_PRESS_MS, STANDBY_HOLD_MS)
blank = displayio.Group()
standby = False
night = is_night()
last_activity = ticks.ticks_ms()
next_night_check = ticks.ticks_ms()

mode = dashboard if START_MODE == "dashboard" else life
mode.enter()
if night:
    set_standby(True)

while True:
    actions = buttons.poll()
    if standby:
        if buttons.any_press:  # any button wakes it up, and does nothing else
            buttons.mute_until_released()
            last_activity = ticks.ticks_ms()
            set_standby(False)
        else:
            air.tick()  # keep measuring so the CO2 graph stays complete
    else:
        for action in actions:
            last_activity = ticks.ticks_ms()
            if action == "standby":
                set_standby(True)
                break
            if action == "switch":
                mode = dashboard if mode is life else life
                mode.enter()
            else:
                mode.handle(action)
        if actions and "standby" in actions:
            continue
        air.tick()
        mode.tick()
        if orientation:
            new_rotation = orientation.changed()
            if new_rotation is not None:
                rotate(new_rotation)

    # Night mode: check once a second
    now_ms = ticks.ticks_ms()
    if not ticks.ticks_less(now_ms, next_night_check):
        next_night_check = ticks.ticks_add(now_ms, 1000)
        was_night, night = night, is_night()
        if night and not was_night and not standby:          # 22:00: go to sleep
            set_standby(True)
        elif was_night and night is False and standby:       # 08:00: wake up
            set_standby(False)
        elif (night and not standby and ticks.ticks_diff(now_ms, last_activity)
              >= NIGHT_WAKE_MINUTES * 60000):                # woken at night, left alone
            set_standby(True)

    if standby or mode is dashboard:
        time.sleep(0.01)
