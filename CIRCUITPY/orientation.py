# orientation.py - bepaal met de ingebouwde accelerometer (LIS3DH) hoe het paneel hangt
import board
import adafruit_ticks as ticks

# Richting van de zwaartekracht -> schermrotatie. Gemeten: staand met het bordje onderaan = +x (270);
# klopt een stand niet, wissel dan hier de getallen om.
GRAVITY_TO_ROTATION = {"+x": 270, "-x": 90, "+y": 0, "-y": 180}
CHECK_MS = 1000
STABLE_CHECKS = 3  # zo vaak achter elkaar een nieuwe stand zien voordat we draaien


def _axis(x, y, z):
    """Welke as wijst het meest naar beneden? None als het paneel plat ligt."""
    if abs(z) > max(abs(x), abs(y)):
        return None
    if abs(x) >= abs(y):
        return "+x" if x > 0 else "-x"
    return "+y" if y > 0 else "-y"


class Orientation:
    def __init__(self):
        try:
            import adafruit_lis3dh
            self.lis = adafruit_lis3dh.LIS3DH_I2C(board.I2C(), address=0x19)
        except Exception as e:  # noqa - zonder accelerometer: vaste stand uit code.py
            print("Geen accelerometer:", e)
            self.lis = None
        self.current = self.rotation()
        self.pending = None
        self.count = 0
        self.next_at = ticks.ticks_ms()

    def rotation(self):
        """Huidige rotatie (0/90/180/270), of None als onbekend of plat."""
        if self.lis is None:
            return None
        try:
            x, y, z = self.lis.acceleration
        except Exception:  # noqa
            return None
        axis = _axis(x, y, z)
        return None if axis is None else GRAVITY_TO_ROTATION[axis]

    def changed(self):
        """De nieuwe rotatie als het paneel een paar seconden anders hangt, anders None."""
        now = ticks.ticks_ms()
        if self.lis is None or ticks.ticks_less(now, self.next_at):
            return None
        self.next_at = ticks.ticks_add(now, CHECK_MS)
        r = self.rotation()
        if r is None or r == self.current:
            self.pending, self.count = None, 0
            return None
        if r == self.pending:
            self.count += 1
        else:
            self.pending, self.count = r, 1
        if self.count < STABLE_CHECKS:
            return None
        self.current, self.pending, self.count = r, None, 0
        return r
