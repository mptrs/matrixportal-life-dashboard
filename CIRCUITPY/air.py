# air.py - SCD-30 CO2-sensor via de STEMMA QT-aansluiting (I2C)
import board
import adafruit_ticks as ticks

READ_MS = 2000  # de SCD-30 meet standaard elke 2 seconden


class Air:
    def __init__(self, graph_minutes=120, width=64):
        self.co2 = self.temp = self.hum = None
        self.history = []  # één waarde per grafiekkolom, nieuwste achteraan
        self.graph_minutes = graph_minutes
        self.set_width(width)
        try:
            import adafruit_scd30
            self.sensor = adafruit_scd30.SCD30(board.I2C())
            print("SCD-30 gevonden")
        except Exception as e:  # noqa - geen sensor: het scherm valt gewoon weg
            print("Geen SCD-30:", e)
            self.sensor = None
        self.next_read = self.next_sample = ticks.ticks_ms()

    def set_width(self, width):
        """Aantal grafiekkolommen (schermbreedte); bij draaien blijft de recentste data staan."""
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
                if co2 > 0:  # direct na opstarten geeft hij soms 0
                    self.co2 = round(co2)
                    self.temp = self.sensor.temperature
                    self.hum = self.sensor.relative_humidity
        except Exception as e:  # noqa
            print("SCD-30 leesfout:", e)
            return
        if self.co2 is not None and not ticks.ticks_less(now, self.next_sample):
            self.next_sample = ticks.ticks_add(now, self.sample_ms)
            self.history.append(self.co2)
            if len(self.history) > self.width:
                self.history.pop(0)
