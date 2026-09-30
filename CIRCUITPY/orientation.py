# orientation.py - use the built-in accelerometer (LIS3DH) to see how the panel is hanging
import time
import board
import adafruit_ticks as ticks

# Direction of gravity -> screen rotation. Measured: portrait with the board at the bottom = +x (270).
# If an orientation is wrong, swap the numbers here.
GRAVITY_TO_ROTATION = {"+x": 270, "-x": 90, "+y": 0, "-y": 180}
CHECK_MS = 1000
RETRY_MS = 5000   # accelerometer not responding (e.g. right after power-up): try again
STABLE_CHECKS = 3  # see a new orientation this many times in a row before rotating


def _axis(x, y, z):
    """Which axis points down the most? None if the panel lies flat or the reading is bogus."""
    g2 = x * x + y * y + z * z
    if not 5 * 5 < g2 < 15 * 15:  # gravity is ~9.8 m/s2; 0,0,0 = no data yet
        return None
    if abs(z) > max(abs(x), abs(y)):
        return None
    if abs(x) >= abs(y):
        return "+x" if x > 0 else "-x"
    return "+y" if y > 0 else "-y"


class Orientation:
    def __init__(self):
        self.lis = None
        self.current = None
        self.pending = None
        self.count = 0
        self.next_at = ticks.ticks_ms()
        # Right after power-up the sensor may need a moment: try a few times
        for _ in range(10):
            if self._connect():
                self.current = self.rotation()
                if self.current is not None:
                    break
            time.sleep(0.1)

    def _connect(self):
        if self.lis is not None:
            return True
        try:
            import adafruit_lis3dh
            self.lis = adafruit_lis3dh.LIS3DH_I2C(board.I2C(), address=0x19)
            return True
        except Exception as e:  # noqa - keep the fixed orientation from code.py for now
            print("No accelerometer (yet):", e)
            return False

    def rotation(self):
        """Current rotation (0/90/180/270), or None if unknown or lying flat."""
        if self.lis is None:
            return None
        try:
            x, y, z = self.lis.acceleration
        except Exception:  # noqa
            return None
        axis = _axis(x, y, z)
        return None if axis is None else GRAVITY_TO_ROTATION[axis]

    def changed(self):
        """The new rotation once the panel has hung differently for a few seconds, else None."""
        now = ticks.ticks_ms()
        if ticks.ticks_less(now, self.next_at):
            return None
        if not self._connect():
            self.next_at = ticks.ticks_add(now, RETRY_MS)
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
