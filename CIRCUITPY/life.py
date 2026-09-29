# life.py - Conway's Game of Life (64x32 landscape or 32x64 portrait). The world wraps around
# (a torus): whatever leaves on the right comes back on the left.
import os
from binascii import crc32
import displayio
import bitmaptools
import adafruit_ticks as ticks
import gfx

STALE_GENS = 40  # how long a finished world stays on screen before a new one starts
# Number of generations remembered to detect repetition. On this wrap-around screen a
# glider needs 256 generations for one lap, so 1024 also catches combinations.
HISTORY = 1024
SPEED_BAR_MS = 1500  # how long the speed bar at the bottom stays visible

# Color index: 0 = dead, 1 = just born, 2..6 = older and older, 7 = just died (trail)
THEMES = (
    (0x000000, 0xFFFFFF, 0x60E0FF, 0x20A0FF, 0x1060E0, 0x0830B0, 0x041C80, 0x101828),  # ocean
    (0x000000, 0xFFFFA0, 0xFFD000, 0xFF9000, 0xFF5000, 0xD02000, 0x901000, 0x281000),  # fire
    (0x000000, 0xD0FFD0, 0x40FF40, 0x10D010, 0x08A008, 0x047004, 0x024802, 0x0C200C),  # matrix
    (0x000000, 0xFFFFFF, 0xFF40C0, 0xC040FF, 0x7040FF, 0x4060FF, 0x2080C0, 0x200C28),  # neon
)


class Life:
    def __init__(self, display, brightness, speeds_ms, speed, max_gens, air=None,
                 alert_ppm=1200, density=0.33):
        self.display = display
        self.w, self.h = display.width, display.height
        self.air = air
        self.alert_ppm = alert_ppm
        self.brightness = brightness
        self.speeds_ms = speeds_ms  # time per generation, fastest first
        self.speed = speed
        self.max_gens = max_gens
        self.density = density
        self.bitmap = displayio.Bitmap(self.w, self.h, 8)
        self.palette = displayio.Palette(8)
        self.group = displayio.Group()
        self.group.append(displayio.TileGrid(self.bitmap, pixel_shader=self.palette))
        # Blinking red dot in the top right corner when CO2 is too high
        dot = displayio.Bitmap(2, 2, 1)
        dot_palette = displayio.Palette(1)
        dot_palette[0] = gfx.scale(0xFF0000, max(brightness, 0.5))
        self.dot = displayio.TileGrid(dot, pixel_shader=dot_palette, x=self.w - 2, y=0)
        self.dot.hidden = True
        self.group.append(self.dot)
        # Speed bar at the bottom, briefly shown after UP/DOWN
        self.bar = displayio.Bitmap(self.w, 1, 2)
        bar_palette = displayio.Palette(2)
        bar_palette.make_transparent(0)
        bar_palette[1] = gfx.scale(0xFFFFFF, max(brightness, 0.5))
        self.bar_tile = displayio.TileGrid(self.bar, pixel_shader=bar_palette, y=self.h - 1)
        self.bar_tile.hidden = True
        self.bar_until = 0
        self.group.append(self.bar_tile)
        n = self.w * self.h
        self.cur = bytearray(n)
        self.nxt = bytearray(n)
        self.age = bytearray(n)
        self.history = [-1] * HISTORY  # ring buffer with fingerprints of earlier states
        self.theme = -1
        self.reset()

    def enter(self):
        self.display.root_group = self.group
        self.next_at = ticks.ticks_ms()

    def handle(self, action):
        if action == "next":        # UP: faster
            self._set_speed(self.speed - 1)
        elif action == "prev":      # DOWN: slower
            self._set_speed(self.speed + 1)
        elif action == "reset":
            self.reset()

    def _set_speed(self, speed):
        self.speed = max(0, min(len(self.speeds_ms) - 1, speed))
        n = len(self.speeds_ms)
        length = (n - self.speed) * self.w // n
        for x in range(self.w):
            self.bar[x, 0] = 1 if x < length else 0
        self.bar_tile.hidden = False
        self.bar_until = ticks.ticks_add(ticks.ticks_ms(), SPEED_BAR_MS)
        self.next_at = ticks.ticks_ms()
        print("Life speed:", self.speeds_ms[self.speed], "ms")

    def reset(self):
        """New random world, with the next color theme."""
        self.theme = (self.theme + 1) % len(THEMES)
        for i, color in enumerate(THEMES[self.theme]):
            self.palette[i] = gfx.scale(color, self.brightness)
        limit = int(256 * self.density)
        noise = os.urandom(len(self.cur))
        for i in range(len(self.cur)):
            v = 1 if noise[i] < limit else 0
            self.cur[i] = v
            self.age[i] = v
        self.gen = 0
        self.stale = 0
        for i in range(HISTORY):
            self.history[i] = -1
        self.hist_i = 0
        self.next_at = ticks.ticks_ms()
        bitmaptools.arrayblit(self.bitmap, self.age)

    def tick(self):
        now = ticks.ticks_ms()
        if self.air is not None:
            co2 = self.air.co2
            self.dot.hidden = co2 is None or co2 < self.alert_ppm or (now // 700) % 2 == 1
        if not self.bar_tile.hidden and not ticks.ticks_less(now, self.bar_until):
            self.bar_tile.hidden = True
        if ticks.ticks_less(now, self.next_at):
            return
        self.next_at = ticks.ticks_add(now, self.speeds_ms[self.speed])
        self.step()
        bitmaptools.arrayblit(self.bitmap, self.age)
        self.gen += 1

        # Finished? Once the whole world is exactly as it was before, everything repeats
        # forever from then on. We keep a fingerprint (CRC32) per state; hash() is no good
        # for this on CircuitPython (it returns the same value for every world).
        # Only when it matches STALE_GENS times in a row is it a real repetition and not
        # an accidental fingerprint collision.
        h = crc32(self.cur) & 0x3FFFFFFF  # small int: costs no extra memory
        if h in self.history:
            self.stale += 1
        else:
            self.stale = 0
            self.history[self.hist_i] = h
            self.hist_i = (self.hist_i + 1) % HISTORY
        if self.stale > STALE_GENS or (self.max_gens and self.gen > self.max_gens):
            self.reset()

    def step(self):
        cur, nxt, age = self.cur, self.nxt, self.age
        W, H = self.w, self.h
        for y in range(H):
            row = y * W
            up = ((y - 1) % H) * W
            dn = ((y + 1) % H) * W
            # Sum per column over 3 rows, with the opposite edges wrapped in left/right
            cs = [a + b + c for a, b, c in zip(cur[up:up + W], cur[row:row + W], cur[dn:dn + W])]
            cs = [cs[-1]] + cs + [cs[0]]
            for x in range(W):
                i = row + x
                s = cs[x] + cs[x + 1] + cs[x + 2]  # 3x3 block including the cell itself
                if cur[i]:
                    if s == 3 or s == 4:  # 2 or 3 neighbors: stays alive
                        nxt[i] = 1
                        if age[i] < 6:
                            age[i] += 1
                    else:
                        nxt[i] = 0
                        age[i] = 7
                elif s == 3:  # exactly 3 neighbors: born
                    nxt[i] = 1
                    age[i] = 1
                else:
                    nxt[i] = 0
                    if age[i]:
                        age[i] = 0
        self.cur, self.nxt = nxt, cur
