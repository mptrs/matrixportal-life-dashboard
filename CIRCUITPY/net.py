# net.py - wifi via de ESP32-coprocessor, tijd (NTP) en weer (Open-Meteo, geen API-key nodig)
import os
import time
import board
import busio
from digitalio import DigitalInOut
from adafruit_esp32spi import adafruit_esp32spi
import adafruit_connection_manager
import adafruit_requests

WEATHER_EVERY = 15 * 60  # seconden
TIME_EVERY = 6 * 60 * 60
RETRY_AFTER = 60


def _secs():
    return time.monotonic_ns() // 1000000000


class Net:
    def __init__(self):
        spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
        self.esp = adafruit_esp32spi.ESP_SPIcontrol(
            spi, DigitalInOut(board.ESP_CS), DigitalInOut(board.ESP_BUSY),
            DigitalInOut(board.ESP_RESET))
        pool = adafruit_connection_manager.get_radio_socketpool(self.esp)
        ssl = adafruit_connection_manager.get_radio_ssl_context(self.esp)
        self.requests = adafruit_requests.Session(pool, ssl)
        self.ssid = os.getenv("CIRCUITPY_WIFI_SSID")
        self.password = os.getenv("CIRCUITPY_WIFI_PASSWORD")
        self.url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=%s&longitude=%s&timezone=%s&forecast_days=4"
            "&current=temperature_2m,weather_code,is_day"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,sunrise,sunset"
        ) % (os.getenv("LATITUDE", "52.37"), os.getenv("LONGITUDE", "4.89"),
              os.getenv("TIMEZONE", "Europe/Amsterdam").replace("/", "%2F"))
        self.weather = None
        self._weather_at = None
        self._unix = None
        self._unix_ns = 0
        self._time_at = None
        self._tried_at = None
        self._failures = 0

    # ---- tijd
    def now(self):
        """Unix-tijd (UTC) of None als de klok nog niet gesynct is."""
        if self._unix is None:
            return None
        return self._unix + (time.monotonic_ns() - self._unix_ns) // 1000000000

    # ---- verversen
    def stale(self):
        t = _secs()
        if self._tried_at is not None and t - self._tried_at < RETRY_AFTER:
            return False
        return (self._weather_at is None or t - self._weather_at > WEATHER_EVERY
                or self._time_at is None or t - self._time_at > TIME_EVERY)

    def update(self):
        self._tried_at = _secs()
        if not self._connect():
            return
        if self._time_at is None or _secs() - self._time_at > TIME_EVERY:
            self._sync_time()
        if self._weather_at is None or _secs() - self._weather_at > WEATHER_EVERY:
            self._fetch_weather()

    def _connect(self):
        try:
            if not self.esp.is_connected:
                print("Verbinden met", self.ssid)
                self.esp.connect_AP(self.ssid, self.password)
            return True
        except Exception as e:  # noqa - op een klok willen we nooit crashen
            print("Wifi mislukt:", e)
            self._failed()
            return False

    def _failed(self):
        self._failures += 1
        if self._failures >= 3:
            print("ESP32 resetten")
            self.esp.reset()
            self._failures = 0

    def _sync_time(self):
        for _ in range(8):
            try:
                t = self.esp.get_time()
                if isinstance(t, tuple):
                    t = t[0]
                if t > 1700000000:
                    self._unix = t
                    self._unix_ns = time.monotonic_ns()
                    self._time_at = _secs()
                    print("Tijd gesynct:", t)
                    return
            except Exception as e:  # noqa
                print("Tijd nog niet beschikbaar:", e)
            time.sleep(1)
        print("Tijd synchroniseren mislukt, straks opnieuw")

    def _fetch_weather(self):
        try:
            with self.requests.get(self.url, timeout=20) as r:
                data = r.json()
            cur, daily = data["current"], data["daily"]
            days = []
            for i, date in enumerate(daily["time"]):
                days.append({
                    "date": date,
                    "code": daily["weather_code"][i],
                    "max": daily["temperature_2m_max"][i],
                    "min": daily["temperature_2m_min"][i],
                    "rain": daily["precipitation_probability_max"][i],
                    "sunrise": daily["sunrise"][i][11:16],
                    "sunset": daily["sunset"][i][11:16],
                })
            self.weather = {
                "temp": cur["temperature_2m"],
                "code": cur["weather_code"],
                "is_day": cur.get("is_day", 1),
                "days": days,
            }
            self._weather_at = _secs()
            self._failures = 0
            print("Weer bijgewerkt:", self.weather["temp"], "graden")
        except Exception as e:  # noqa
            print("Weer ophalen mislukt:", e)
            self._failed()
