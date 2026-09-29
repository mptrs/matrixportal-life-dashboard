# dashboard.py - rotating dashboard: clock + moon, indoor air, weather, forecast,
# world clocks and GIFs. Every screen has a landscape (64x32) and a portrait (32x64) layout.
import os
import time
import displayio
import adafruit_ticks as ticks
import gfx
import tz

DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
RIGHT_CX = 46  # landscape: center of the text area right of the moon / icon


def _deg(value):
    return "%d°" % round(value)


def _fit(text, width):
    while gfx.text_width(text) > width:
        text = text[:-1]
    return text


def co2_color(ppm):
    if ppm < 800:
        return gfx.GREEN
    if ppm < 1200:
        return gfx.YELLOW
    if ppm < 1500:
        return gfx.ORANGE
    return gfx.RED


class GifPlayer:
    """Plays sprite sheets: BMPs with all frames stacked vertically.
    The frame time is in the file name, e.g. 'nyan_d80.bmp' = 80 ms per frame."""

    def __init__(self, folder, w, h, brightness):
        self.folder = folder
        self.w, self.h = w, h
        self.brightness = brightness
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
        self.files = sorted(n for n in names if n.lower().endswith(".bmp") and not n.startswith("."))
        self.index = 0
        self.group = displayio.Group()
        self.tile = None
        self.loops = 0

    def start(self):
        name = self.files[self.index]
        self.index = (self.index + 1) % len(self.files)
        self.delay = 100
        base = name[:-4]
        if "_d" in base:
            try:
                self.delay = max(20, int(base.rsplit("_d", 1)[1]))
            except ValueError:
                pass
        bmp = displayio.OnDiskBitmap(self.folder + "/" + name)
        if bmp.width != self.w:
            raise ValueError("%s is %d wide, expected %d" % (name, bmp.width, self.w))
        shader = bmp.pixel_shader
        if isinstance(shader, displayio.Palette):
            for i in range(len(shader)):
                shader[i] = gfx.scale(shader[i], self.brightness)
        self.frames = max(1, bmp.height // self.h)
        self.tile = displayio.TileGrid(bmp, pixel_shader=shader,
                                       tile_width=self.w, tile_height=self.h)
        self.group.append(self.tile)
        self.frame = 0
        self.loops = 0
        self.next_at = ticks.ticks_add(ticks.ticks_ms(), self.delay)
        print("GIF:", name, self.frames, "frames")

    def tick(self):
        now = ticks.ticks_ms()
        if self.tile is None or ticks.ticks_less(now, self.next_at):
            return
        self.next_at = ticks.ticks_add(now, self.delay)
        self.frame += 1
        if self.frame >= self.frames:
            self.frame = 0
            self.loops += 1
        self.tile[0] = self.frame

    def stop(self):
        if self.tile is not None:
            self.group.remove(self.tile)
            self.tile = None


class Dashboard:
    def __init__(self, display, net, air, brightness, order, durations, gif_folder,
                 home_tz, world_clocks):
        self.display = display
        self.net = net
        self.air = air
        self.durations = durations
        self.home_tz = home_tz
        self.world_clocks = world_clocks
        self.w, self.h = display.width, display.height
        self.portrait = self.h > self.w
        self.canvas = displayio.Bitmap(self.w, self.h, 16)
        self.palette = displayio.Palette(16)
        for i, color in enumerate(gfx.COLORS):
            self.palette[i] = gfx.scale(color, brightness)
        self.group = displayio.Group()
        self.group.append(displayio.TileGrid(self.canvas, pixel_shader=self.palette))
        self.gifs = GifPlayer(gif_folder, self.w, self.h, brightness)
        self.order = [s for s in order
                      if (s != "gif" or self.gifs.files) and (s != "air" or air.sensor)
                      and (s != "world" or world_clocks)]
        self.order = self.order or ["clock"]
        self.index = 0
        self.current = None
        self.started = ticks.ticks_ms()
        self._last_sec = self._last_min = self._sun_shown = self._air_shown = None

    # ---- controlled from code.py
    def enter(self):
        self._show()

    def handle(self, action):
        if action == "prev":        # DOWN: previous screen
            self._advance(-1)
        else:                       # UP or both buttons: next screen
            self._advance()

    def tick(self):
        elapsed = ticks.ticks_diff(ticks.ticks_ms(), self.started)
        limit = self.durations.get(self.current, 10) * 1000
        if self.current == "gif":
            self.gifs.tick()
            # Let a GIF play completely at least once, but not forever
            if (self.gifs.loops and elapsed >= limit) or elapsed >= 2 * limit:
                self._advance()
            return
        if self.current == "clock":
            self._draw_clock(False)
        elif self.current == "air" and self.air.co2 != self._air_shown:
            self._draw_air()
        elif self.current == "world":
            now = self.net.now()
            if now is not None and now // 60 != self._last_min:
                self._draw_world()
        if elapsed >= limit:
            self._advance()

    def message(self, lines, color=gfx.WHITE):
        c = self.canvas
        c.fill(0)
        y = self.h // 2 - (len(lines) * 8 - 3) // 2
        for line in lines:
            gfx.draw_text_centered(c, line, self.w // 2, y, color)
            y += 8
        self.display.root_group = self.group

    def local_now(self):
        now = self.net.now()
        return None if now is None else now + tz.utc_offset(now, *self.home_tz)

    # ---- screens
    def _advance(self, step=1):
        self.index = (self.index + step) % len(self.order)
        self._show()

    def _show(self):
        self.gifs.stop()
        self.current = self.order[self.index]
        self.started = ticks.ticks_ms()
        self._last_min = None
        if self.current == "gif":
            try:
                self.gifs.start()
                self.display.root_group = self.gifs.group
                return
            except Exception as e:  # noqa - broken or wrongly oriented BMP: skip it
                print("GIF failed:", e)
                self.current = "clock"
        self.display.root_group = self.group
        self._draw()
        if self.net.stale():
            self.net.update()  # may take a few seconds
            self._draw()

    def _draw(self):
        if self.current == "clock":
            self._draw_clock(True)
        elif self.current == "weather":
            self._draw_weather()
        elif self.current == "forecast":
            self._draw_forecast()
        elif self.current == "air":
            self._draw_air()
        elif self.current == "world":
            self._draw_world()

    # ---- clock + moon
    def _draw_clock(self, full):
        local = self.local_now()
        if local is None:
            if full:
                self.message(("CLOCK", "NOT", "SYNCED"), gfx.GREY)
            return
        sec = local % 60
        if not full and sec == self._last_sec:
            return
        self._last_sec = sec
        lt = time.localtime(local)
        c = self.canvas
        w = self.net.weather
        T = gfx.draw_text_centered

        if full or local // 60 != self._last_min:
            self._last_min = local // 60
            c.fill(0)
            phase = gfx.moon_phase(self.net.now())
            date = "%s %d %s" % (DAYS[lt.tm_wday], lt.tm_mday, MONTHS[lt.tm_mon - 1])
            if self.portrait:
                gfx.draw_moon(c, 16, 11, 10, phase)
                T(c, "%02d" % lt.tm_hour, 16, 22, gfx.WHITE, 2)
                T(c, "%02d" % lt.tm_min, 16, 35, gfx.WHITE, 2)
                T(c, date, 16, 47, gfx.GREY)
                if w:
                    T(c, "↑" + w["days"][0]["sunrise"], 16, 53, gfx.YELLOW)
                    T(c, "↓" + w["days"][0]["sunset"], 16, 59, gfx.ORANGE)
            else:
                gfx.draw_moon(c, 13, 16, 12, phase)
                T(c, date, RIGHT_CX, 15, gfx.GREY)
            self._sun_shown = None

        # Every second: blinking colon
        colon = gfx.GREY if sec % 2 == 0 else gfx.BLACK
        if self.portrait:
            c[15, 33] = c[16, 33] = colon
            return
        gfx.fill_rect(c, 28, 2, 36, 10, 0)
        gfx.draw_parts(c, (("%02d" % lt.tm_hour, gfx.WHITE), (":", colon),
                           ("%02d" % lt.tm_min, gfx.WHITE)), RIGHT_CX, 2, 2)
        # Landscape has room for one line: sunrise / sunset alternate every 4 seconds
        which = (sec // 4) % 2
        if w and which != self._sun_shown:
            self._sun_shown = which
            gfx.fill_rect(c, 26, 24, 38, 5, 0)
            d0 = w["days"][0]
            if which == 0:
                T(c, "↑" + d0["sunrise"], RIGHT_CX, 24, gfx.YELLOW)
            else:
                T(c, "↓" + d0["sunset"], RIGHT_CX, 24, gfx.ORANGE)

    # ---- today's weather
    def _draw_weather(self):
        w = self.net.weather
        if not w:
            self.message(("NO", "WEATHER", "DATA"), gfx.GREY)
            return
        c = self.canvas
        c.fill(0)
        d0 = w["days"][0]
        kind = gfx.weather_kind(w["code"])
        temp = "%d" % round(w["temp"])
        minmax = (("%d" % round(d0["min"]), gfx.LIGHTBLUE), ("/", gfx.GREY),
                  (_deg(d0["max"]), gfx.ORANGE))
        rain = None if d0["rain"] is None else "%d%%" % d0["rain"]
        if self.portrait:
            gfx.draw_icon(c, kind, 4, 1, 2, night=not w["is_day"])
            self._big_temp(temp, 16, 28)
            gfx.draw_parts(c, minmax, 16, 42)
            if rain:
                self._dots_h(49)
                gfx.draw_text_centered(c, "RAIN", 16, 52, gfx.GREY)
                gfx.draw_text_centered(c, rain, 16, 58, gfx.LIGHTBLUE)
        else:
            gfx.draw_icon(c, kind, 1, 4, 2, night=not w["is_day"])
            self._big_temp(temp, RIGHT_CX, 2)
            gfx.draw_parts(c, minmax, RIGHT_CX, 15)
            if rain:
                gfx.draw_parts(c, (("RAIN ", gfx.GREY), (rain, gfx.LIGHTBLUE)), RIGHT_CX, 24)

    def _big_temp(self, temp, cx, y):
        x = cx - (gfx.text_width(temp, 2) + 5) // 2
        x = gfx.draw_text(self.canvas, temp, x, y, gfx.WHITE, 2)
        gfx.draw_text(self.canvas, "°", x, y, gfx.WHITE)

    # ---- forecast for the next 3 days
    def _draw_forecast(self):
        w = self.net.weather
        if not w:
            self.message(("NO", "WEATHER", "DATA"), gfx.GREY)
            return
        c = self.canvas
        c.fill(0)
        T = gfx.draw_text_centered
        for i, d in enumerate(w["days"][1:4]):
            y, m, dd = (int(p) for p in d["date"].split("-"))
            day = DAYS[tz.weekday(y, m, dd)]
            kind = gfx.weather_kind(d["code"])
            if self.portrait:
                top = i * 22
                gfx.draw_icon(c, kind, 0, top + 4)
                T(c, day, 23, top + 1, gfx.WHITE)
                T(c, _deg(d["max"]), 23, top + 8, gfx.ORANGE)
                T(c, _deg(d["min"]), 23, top + 14, gfx.LIGHTBLUE)
                if i < 2:
                    self._dots_h(top + 21)
            else:
                cx = 11 + i * 21
                T(c, day, cx, 0, gfx.WHITE)
                gfx.draw_icon(c, kind, cx - 6, 6)
                T(c, _deg(d["max"]), cx, 20, gfx.ORANGE)
                T(c, _deg(d["min"]), cx, 26, gfx.LIGHTBLUE)
                if i < 2:
                    for yy in range(2, 30, 2):
                        c[cx + 10, yy] = gfx.DARKGREY

    # ---- indoor air (SCD-30)
    def _draw_air(self):
        a = self.air
        self._air_shown = a.co2
        if a.co2 is None:
            self.message(("CO2", "WARMING", "UP"), gfx.GREY)
            return
        c = self.canvas
        c.fill(0)
        T = gfx.draw_text_centered
        ppm = "%d" % a.co2
        temp = "%.1f°" % a.temp
        hum = "%d%%" % round(a.hum)
        if self.portrait:
            T(c, ppm, 16, 1, co2_color(a.co2), 2)
            T(c, "CO2 PPM", 16, 13, gfx.GREY)
            T(c, temp, 16, 21, gfx.WHITE)
            T(c, hum, 16, 27, gfx.LIGHTBLUE)
            self._graph(a.history, 35)
        else:
            x = gfx.draw_text(c, ppm, 1, 1, co2_color(a.co2), 2)
            gfx.draw_text(c, "PPM", x, 6, gfx.GREY)
            gfx.draw_text(c, temp, 64 - gfx.text_width(temp), 1, gfx.WHITE)
            gfx.draw_text(c, hum, 64 - gfx.text_width(hum), 7, gfx.LIGHTBLUE)
            self._graph(a.history, 15)

    def _graph(self, history, top):
        """Bars from `top` to the bottom edge: 400..2000 ppm, dotted lines at 800 and 1200."""
        c = self.canvas
        rows = self.h - top

        def height(ppm):
            return max(1, min(rows, (ppm - 400) * rows // 1600))

        for level in (800, 1200):
            y = self.h - height(level)
            for x in range(0, self.w, 3):
                c[x, y] = gfx.DARKGREY
        start = self.w - len(history)
        for i, v in enumerate(history):
            color = co2_color(v)
            for y in range(self.h - height(v), self.h):
                c[start + i, y] = color

    # ---- world clocks
    def _draw_world(self):
        now = self.net.now()
        if now is None:
            self.message(("CLOCK", "NOT", "SYNCED"), gfx.GREY)
            return
        self._last_min = now // 60
        c = self.canvas
        c.fill(0)
        home_day = self.local_now() // 86400
        for i, (name, std, rule) in enumerate(self.world_clocks[:4]):
            local = now + tz.utc_offset(now, std, rule)
            lt = time.localtime(local)
            clock = "%02d:%02d" % (lt.tm_hour, lt.tm_min)
            diff = local // 86400 - home_day
            day = "+1" if diff > 0 else "-1" if diff < 0 else ""
            sun = gfx.YELLOW if 7 <= lt.tm_hour < 19 else gfx.BLUE  # day or night over there
            if self.portrait:
                top = i * 16
                gfx.draw_text_centered(c, _fit(name, 32), 16, top + 1, gfx.GREY)
                gfx.fill_rect(c, 1, top + 9, 2, 3, sun)
                gfx.draw_text_centered(c, clock, 15, top + 8, gfx.WHITE)
                if day:
                    gfx.draw_text(c, day, 32 - gfx.text_width(day), top + 8, gfx.CYAN)
                if i < 3:
                    self._dots_h(top + 15)
            else:
                top = 1 + i * 8
                gfx.fill_rect(c, 0, top + 1, 2, 3, sun)
                gfx.draw_text(c, _fit(name, 30), 4, top, gfx.GREY)
                if day:
                    gfx.draw_text(c, day, 37, top, gfx.CYAN)
                gfx.draw_text(c, clock, 64 - gfx.text_width(clock), top, gfx.WHITE)

    def _dots_h(self, y):
        for x in range(1, self.w, 2):
            self.canvas[x, y] = gfx.DARKGREY
