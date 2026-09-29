# air.py - SCD-30 CO2 sensor on the STEMMA QT connector (I2C)
import board
import adafruit_ticks as ticks

READ_MS = 2000  # the SCD-30 measures every 2 seconds by default


class Air:
    def __init__(self, graph_minutes=120, width=64):
        self.co2 = self.temp = self.hum = None
        self.history = []  # one value per graph column, newest last
        self.graph_minutes = graph_minutes
        self.set_width(width)
        try:
            import adafruit_scd30
            self.sensor = adafruit_scd30.SCD30(board.I2C())
            print("SCD-30 found")
        except Exception as e:  # noqa - no sensor: the screen is simply skipped
            print("No SCD-30:", e)
            self.sensor = None
        self.next_read = self.next_sample = ticks.ticks_ms()

    def set_width(self, width):
        """Number of graph columns (screen width); on rotation the most recent data is kept."""
        self.width = width
        self.sample_ms = self.graph_minutes * 60000 // width
        self.history = self.history[-width:]

    def tick(self):
        if self.sensor is None:
            return
        now = ticks.ticks_ms()
        if ticks.ticks_less(now, self.next_read):
            return
        self.next_read = ticks.ticks_add(now, READ_MS)
        try:
            if self.sensor.data_available:
                co2 = self.sensor.CO2
                if co2 > 0:  # right after power-up it sometimes reports 0
                    self.co2 = round(co2)
                    self.temp = self.sensor.temperature
                    self.hum = self.sensor.relative_humidity
        except Exception as e:  # noqa
            print("SCD-30 read error:", e)
            return
        if self.co2 is not None and not ticks.ticks_less(now, self.next_sample):
            self.next_sample = ticks.ticks_add(now, self.sample_ms)
            self.history.append(self.co2)
            if len(self.history) > self.width:
                self.history.pop(0)
