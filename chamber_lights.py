"""
White-light control for the LightRoom/DarkRoom chambers (analog current sink).

Hardware (see analog_dimming_simulation_check_new.pdf, DuoStrip version):

    Adafruit GP8403 DAC (I2C 0x58, 0-5 V range)
        channel 0 (OUT0) -> room 1     channel 1 (V1) -> room 2
    -> 3.9 k / 1 k divider (+10 uF, 20 Hz low-pass)
    -> OP295 current-sink loop -> existing gate resistor (R22/R20) -> IRLZ44N
    -> 2.0 ohm sense resistor to ground

The LED current is set by the DAC voltage and nothing else:

    I_LED = V_dac / 4.9 / 2.0 ohm        (5.00 V -> 510 mA)

so one DAC count (5 V / 4095) is ~0.125 mA. Lux is not exactly
proportional to current, so each room keeps a small calibration table of
(current, measured lux) points made with sweep() and a lux meter.

The DAC is driven directly through /dev/i2c-1 - no extra Python packages are
needed (I2C must be enabled with raspi-config). The register protocol is the
one used by Adafruit's adafruit_gp8403 library.

Command line (close the GUI first - only one program may drive the DAC):

    python3 chamber_lights.py info            # constants, calibration, DAC status
    python3 chamber_lights.py off             # both rooms dark
    python3 chamber_lights.py set 1 300       # room 1 at 300 mA
    python3 chamber_lights.py lux 2 10        # room 2 at 10 lux (calibrated)
    python3 chamber_lights.py sweep 1         # calibrate room 1 with a lux meter

or interactively:  python3 -i chamber_lights.py   then   set_current_mA(1, 30)

The DAC holds its last value after a program exits, so `set` leaves the
light on until `off` is run (or the GUI is started).
"""

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

try:
    import fcntl  # Linux only; absent on Windows -> simulation mode
except ImportError:
    fcntl = None


# ---------------------------------------------------------------------------
# Circuit constants - change these only if the hardware changes
# ---------------------------------------------------------------------------
DAC_I2C_BUS = 1
DAC_ADDRESS = 0x58            # A0-A2 jumpers open
# The board answers anywhere in this range depending on its address jumpers.
# The configured address is tried first, then the rest are probed.
DAC_ADDRESS_CANDIDATES = tuple(range(0x58, 0x60))
DAC_FULL_SCALE_V = 5.0        # GP8403 0-5 V range. NEVER use the 10 V range.
DAC_MAX_CODE = 4095           # 12-bit
DIVIDER_RATIO = (3.9 + 1.0) / 1.0   # 3.9 k over 1 k
SENSE_OHMS = 2.0              # per room, 2 W

ROOMS = (1, 2)
# room -> DAC channel. Swapped on 26 Oct 2026: commanding room 2 lit room 1,
# so the rooms are crossed somewhere between the DAC outputs and the strips.
# This is the one place that mapping lives - _push() honours it.
ROOM_CHANNEL = {1: 1, 2: 0}

MA_PER_CODE = DAC_FULL_SCALE_V / DAC_MAX_CODE / DIVIDER_RATIO / SENSE_OHMS * 1000.0
MAX_CURRENT_MA = DAC_MAX_CODE * MA_PER_CODE   # ~510 mA

CALIBRATION_FILE = Path(__file__).resolve().with_name("light_calibration.json")

# Starting estimates from the simulation document (320 / 32 / 3.2 mA for
# 1000 / 100 / 10 lux). Replace by running sweep() for each room.
DEFAULT_POINTS = [(0.0, 0.0), (3.2, 10.0), (32.0, 100.0), (320.0, 1000.0)]

# Currents visited by sweep(), in mA
SWEEP_CURRENTS_MA = [0, 1, 2, 3, 4, 5, 7, 10, 15, 20, 30, 40, 50,
                     75, 100, 150, 200, 300, 400, 500]

LOCK_FILE = "/tmp/chamber_lights.lock"

# Last codes pushed to the DAC. The GP8403 cannot be read back, so without this
# a fresh process has no idea what the lights are doing - `info` would report 0
# while the room is lit. Written on every successful push.
STATE_FILE = "/tmp/chamber_lights_state.json"

# GP8403 registers (from adafruit_gp8403)
_REG_RANGE = 0x01
_REG_CH0 = 0x02          # channel 1 follows at 0x04; auto-increment
_RANGE_5V_DATA = 0x00
_I2C_SLAVE = 0x0703      # ioctl request from <linux/i2c-dev.h>


# ---------------------------------------------------------------------------
# DAC drivers
# ---------------------------------------------------------------------------
class GP8403:
    """Minimal GP8403 driver over /dev/i2c-N. Raises OSError if absent."""

    def __init__(self, bus=DAC_I2C_BUS, address=DAC_ADDRESS, reset=True):
        """
        Args:
            bus: /dev/i2c-N number
            address: Tried first; the rest of DAC_ADDRESS_CANDIDATES is probed
                     if it does not answer, since the jumpers decide this
            reset: Zero the outputs and select the 0-5 V range, as Adafruit's
                   driver does. Pass False to query without disturbing a room
                   that is already lit.
        """
        if fcntl is None:
            raise OSError("fcntl not available (not running on Linux)")
        self._lock_fd = None
        self._fd = None
        self.address = address
        self._acquire_lock()
        try:
            self._fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
            self.address = self._find_device(address)
            if reset:
                # Same order as Adafruit: outputs to 0, then select 0-5 V range.
                self.set_codes(0, 0)
                self._write(_REG_RANGE, bytes([_RANGE_5V_DATA]))
        except Exception:
            self.close()
            raise

    def _find_device(self, preferred):
        """
        Select the address the DAC actually answers on.

        Probes with a one byte read, which is what i2cdetect uses across this
        address range. Returns the working address, or raises OSError naming
        every address tried.

        Args:
            preferred: Address to try first

        Returns:
            int: The address that responded
        """
        tried = []
        candidates = [preferred] + [a for a in DAC_ADDRESS_CANDIDATES if a != preferred]
        for address in candidates:
            tried.append(f"0x{address:02X}")
            try:
                fcntl.ioctl(self._fd, _I2C_SLAVE, address)
                os.read(self._fd, 1)
            except OSError:
                continue
            if address != preferred:
                print(f"[Lights] DAC found at 0x{address:02X}, not the configured "
                      f"0x{preferred:02X}. Set DAC_ADDRESS in chamber_lights.py "
                      f"to make this permanent.")
            return address

        raise OSError(
            "no GP8403 responded at " + ", ".join(tried) +
            ". Check `i2cdetect -y 1`; if the board answers outside this range, "
            "set DAC_ADDRESS in chamber_lights.py."
        )

    def _acquire_lock(self):
        self._lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o666)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._lock_fd)
            self._lock_fd = None
            raise OSError("another program (probably the LightRoom-DarkRoom GUI) "
                          "is already controlling the lights - close it first")

    def _write(self, register, payload):
        os.write(self._fd, bytes([register]) + bytes(payload))

    def set_codes(self, code0, code1):
        """Set both channels in one I2C transaction (12-bit codes)."""
        data = bytearray()
        for code in (code0, code1):
            word = (int(code) & 0x0FFF) << 4
            data += word.to_bytes(2, "little")
        self._write(_REG_CH0, data)

    def close(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None


class SimulatedDAC:
    """Stand-in used when the DAC can't be opened; just prints."""

    address = None

    def set_codes(self, code0, code1):
        print(f"[Lights-SIM] DAC codes -> ch0={code0}, ch1={code1}")

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Calibration (current <-> lux) per room
# ---------------------------------------------------------------------------
def _interp(x, xs, ys):
    """Piecewise-linear interpolation; proportional extrapolation above."""
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    # Above the last point: scale through the origin from the last point
    return ys[-1] * x / xs[-1] if xs[-1] > 0 else ys[-1]


def clean_points(points):
    """Sort by current and keep only points whose lux strictly increases."""
    pts = sorted((float(m), float(l)) for m, l in points)
    if not pts or pts[0][0] > 0:
        pts.insert(0, (0.0, 0.0))
    kept = [pts[0]]
    for m, l in pts[1:]:
        if m > kept[-1][0] and l > kept[-1][1]:
            kept.append((m, l))
    return kept


class RoomCalibration:
    def __init__(self, points=None, calibrated=False, date=None):
        self.points = clean_points(points or DEFAULT_POINTS)
        self.calibrated = calibrated
        self.date = date
        if len(self.points) < 2:
            self.points = clean_points(DEFAULT_POINTS)
            self.calibrated = False

    def lux_to_mA(self, lux):
        if lux <= 0:
            return 0.0
        m = [p[0] for p in self.points]
        l = [p[1] for p in self.points]
        return _interp(lux, l, m)

    def mA_to_lux(self, mA):
        if mA <= 0:
            return 0.0
        m = [p[0] for p in self.points]
        l = [p[1] for p in self.points]
        return _interp(mA, m, l)

    def to_dict(self):
        return {"points_mA_lux": [list(p) for p in self.points],
                "calibrated": self.calibrated, "date": self.date}


def load_calibration(path=CALIBRATION_FILE):
    cal = {room: RoomCalibration() for room in ROOMS}
    try:
        with open(path) as f:
            data = json.load(f)
        for room in ROOMS:
            entry = data.get(f"room_{room}")
            if entry:
                cal[room] = RoomCalibration(entry.get("points_mA_lux"),
                                            bool(entry.get("calibrated")),
                                            entry.get("date"))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[Lights] Could not read {path} ({e}); using estimates")
    return cal


def save_calibration(cal, path=CALIBRATION_FILE):
    data = {f"room_{room}": cal[room].to_dict() for room in ROOMS}
    data["_note"] = ("Measured (current mA, floor lux) pairs per room, made with "
                     "chamber_lights.py sweep. Edit by re-running the sweep.")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Main interface
# ---------------------------------------------------------------------------
def mA_to_code(mA):
    mA = min(max(float(mA), 0.0), MAX_CURRENT_MA)
    return int(round(mA / MA_PER_CODE))


def code_to_mA(code):
    return code * MA_PER_CODE


class ChamberLights:
    """
    Both rooms' white lights.

    hardware_ok is False (and `error` says why) when the DAC could not be
    opened; the object then simulates so the GUI still runs.
    """

    def __init__(self, simulate=False, calibration_file=CALIBRATION_FILE,
                 reset=True):
        """
        Args:
            simulate: Skip the hardware and pretend, for development
            calibration_file: Where the per-room lux calibration lives
            reset: Turn both rooms off on construction. Pass False to inspect
                   the lights without changing them - a read-only query must
                   not end a soak test or black out a running session.
        """
        self.calibration_file = Path(calibration_file)
        self.calibration = load_calibration(self.calibration_file)
        self._codes = {room: 0 for room in ROOMS}
        self.error = None
        if simulate:
            self.dac = SimulatedDAC()
            self.error = "simulation requested"
        else:
            try:
                self.dac = GP8403(reset=reset)
                print(f"[Lights] GP8403 DAC ready at 0x{self.dac.address:02X} "
                      f"(0-5 V range)")
            except Exception as e:
                self.dac = SimulatedDAC()
                self.error = str(e)
                print(f"[Lights] DAC NOT available ({e}) - white lights are simulated")
        self.hardware_ok = not isinstance(self.dac, SimulatedDAC)

        if reset:
            self.off()
        else:
            # Nothing was written, so report whatever the last process pushed
            self.state_known = self._load_state()

    # -- low level ---------------------------------------------------------
    def _push(self):
        by_channel = {ROOM_CHANNEL[room]: code for room, code in self._codes.items()}
        self.dac.set_codes(by_channel[0], by_channel[1])

    def set_codes(self, codes):
        """
        Set per-room DAC codes.

        The stored codes are only updated once the I2C write has gone through.
        They are what the GUI shows and what `describe()` writes into the
        session data file, so a failed write must not leave a current recorded
        that was never delivered.

        Args:
            codes: {room: 12-bit code}. Rooms not listed keep their value.
        """
        previous = dict(self._codes)
        for room, code in codes.items():
            self._check_room(room)
            self._codes[room] = max(0, min(DAC_MAX_CODE, int(code)))
        try:
            self._push()
        except Exception:
            self._codes = previous
            raise
        self._save_state()

    def _save_state(self):
        """Record what was last pushed, so another process can report it."""
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({"codes": {str(r): c for r, c in self._codes.items()},
                           "hardware_ok": self.hardware_ok}, f)
        except Exception:
            pass  # a stale or missing state file only affects reporting

    def _load_state(self):
        """Adopt the codes last pushed by whichever process set them."""
        try:
            with open(STATE_FILE) as f:
                stored = json.load(f).get("codes", {})
            for room in ROOMS:
                value = stored.get(str(room))
                if value is not None:
                    self._codes[room] = max(0, min(DAC_MAX_CODE, int(value)))
            return True
        except Exception:
            return False

    @staticmethod
    def _check_room(room):
        if room not in ROOMS:
            raise ValueError(f"room must be 1 or 2, not {room!r}")

    # -- current -----------------------------------------------------------
    def set_current_mA(self, room, mA):
        """Set a room's LED current. Returns the current actually set (mA)."""
        self.set_codes({room: mA_to_code(mA)})
        return self.current_mA(room)

    def set_currents_mA(self, currents):
        """Set several rooms at once, e.g. {1: 320, 2: 0} (one I2C write)."""
        self.set_codes({room: mA_to_code(mA) for room, mA in currents.items()})

    def current_mA(self, room):
        self._check_room(room)
        return code_to_mA(self._codes[room])

    def code(self, room):
        self._check_room(room)
        return self._codes[room]

    # -- lux ---------------------------------------------------------------
    def lux_to_mA(self, room, lux):
        self._check_room(room)
        return self.calibration[room].lux_to_mA(lux)

    def mA_to_lux(self, room, mA):
        self._check_room(room)
        return self.calibration[room].mA_to_lux(mA)

    def max_lux(self, room):
        return self.mA_to_lux(room, MAX_CURRENT_MA)

    def is_calibrated(self, room):
        self._check_room(room)
        return self.calibration[room].calibrated

    def set_lux(self, room, lux):
        """Set a room by lux through its calibration. Returns mA set."""
        return self.set_current_mA(room, self.lux_to_mA(room, lux))

    def set_luxes(self, luxes):
        """Set several rooms by lux at once, e.g. {1: 1000, 2: 0}."""
        self.set_currents_mA({room: self.lux_to_mA(room, lux) for room, lux in luxes.items()})

    # -- off / close -------------------------------------------------------
    def off(self, room=None):
        """Turn one room (or both, if room is None) completely dark."""
        rooms = ROOMS if room is None else (room,)
        self.set_codes({r: 0 for r in rooms})

    def close(self):
        try:
            self.off()
        finally:
            self.dac.close()

    def reload_calibration(self):
        self.calibration = load_calibration(self.calibration_file)

    # -- calibration -------------------------------------------------------
    def sweep(self, room, currents=SWEEP_CURRENTS_MA):
        """
        Interactive lux calibration for one room.

        Steps through `currents`; at each one type the lux meter reading
        (Enter skips a step, q finishes early). The other room is turned off.
        """
        self._check_room(room)
        other = 2 if room == 1 else 1
        print(f"\nCalibrating room {room}. Put the lux meter at the usual "
              f"measuring spot on the floor and close the chamber.")
        print(f"Room {other}'s white light is switched off for the sweep.")
        print("At each step type the reading in lux, Enter to skip, q to finish.\n")
        self.off()
        measured = []
        try:
            for mA in currents:
                actual = self.set_current_mA(room, mA)
                time.sleep(0.5)
                while True:
                    text = input(f"  {actual:7.2f} mA (code {self.code(room):4d})  lux = ").strip()
                    if text.lower() == "q" or text == "":
                        break
                    try:
                        lux = float(text)
                        if lux < 0:
                            raise ValueError
                        measured.append((actual, lux))
                        break
                    except ValueError:
                        print("    Type a number, Enter to skip, or q to finish.")
                if text.lower() == "q":
                    break
        finally:
            self.off(room)

        points = clean_points(measured)
        dropped = len(measured) + (0 if any(m == 0 for m, _ in measured) else 1) - len(points)
        if len(points) < 3:
            print("\nNot enough readings (need at least two above 0 mA). Nothing saved.")
            return None
        if dropped > 0:
            print(f"\nNote: {dropped} reading(s) did not increase with current and were ignored.")
        new = RoomCalibration(points, calibrated=True,
                              date=datetime.datetime.now().isoformat(timespec="minutes"))
        print("\n   mA        lux")
        for m, l in points:
            print(f"  {m:7.2f}  {l:9.2f}")
        print("\nWith this calibration:")
        for lux in (10, 100, 1000):
            mA = new.lux_to_mA(lux)
            note = "  (above max current!)" if mA > MAX_CURRENT_MA else ""
            print(f"  {lux:5d} lux -> {mA:7.2f} mA (code {mA_to_code(mA)}){note}")
        answer = input(f"\nSave this as room {room}'s calibration? [y/N] ").strip().lower()
        if answer == "y":
            self.calibration[room] = new
            save_calibration(self.calibration, self.calibration_file)
            print(f"Saved to {self.calibration_file}")
            return new
        print("Not saved.")
        return None

    def info(self):
        address = self.dac.address if self.hardware_ok else DAC_ADDRESS
        lines = [
            f"DAC: {'GP8403 at 0x%02X, 0-5 V range' % address if self.hardware_ok else 'NOT available - ' + str(self.error)}",
            f"Divider {DIVIDER_RATIO:.2f}:1, sense {SENSE_OHMS} ohm -> "
            f"{MA_PER_CODE:.4f} mA per DAC count, {MAX_CURRENT_MA:.1f} mA full scale",
            f"Calibration file: {self.calibration_file}",
        ]

        # What the lights are doing right now. The GP8403 cannot be read back,
        # so this comes from whatever process last pushed a value.
        if getattr(self, "state_known", None) is False:
            lines.append("Current output: unknown (no process has set the lights "
                         "since boot, or the state file was cleared)")
        else:
            states = []
            for room in ROOMS:
                mA = self.current_mA(room)
                states.append(f"room {room}: {mA:6.2f} mA (code {self.code(room)}, "
                              f"{mA * SENSE_OHMS:.1f} mV)")
            lines.append("Current output: " + ";  ".join(states))

        for room in ROOMS:
            cal = self.calibration[room]
            status = f"calibrated {cal.date}" if cal.calibrated else "NOT calibrated (simulation estimates)"
            lines.append(f"Room {room}: {status}; max ~{self.max_lux(room):.0f} lux")
            for lux in (10, 100, 1000):
                mA = cal.lux_to_mA(lux)
                if mA > MAX_CURRENT_MA:
                    lines.append(f"    {lux:5d} lux -> needs {mA:.0f} mA, above the "
                                 f"{MAX_CURRENT_MA:.0f} mA maximum (will be capped)")
                    continue
                lines.append(f"    {lux:5d} lux -> {mA:7.2f} mA, code {mA_to_code(mA)}, "
                             f"{mA * SENSE_OHMS:.1f} mV across the sense resistor")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level helpers for interactive use (python3 -i chamber_lights.py)
# ---------------------------------------------------------------------------
_lights = None


def get_lights(reset=True):
    """
    Shared ChamberLights instance.

    Args:
        reset: False for read-only use, so querying does not turn the lights off
    """
    global _lights
    if _lights is None:
        _lights = ChamberLights(reset=reset)
    return _lights


def off(room=None):
    get_lights().off(room)


def set_current_mA(room, mA):
    actual = get_lights().set_current_mA(room, mA)
    print(f"Room {room}: {actual:.2f} mA (code {get_lights().code(room)}), "
          f"expect {actual * SENSE_OHMS:.1f} mV across the 2.0 ohm")
    return actual


def set_lux(room, lux):
    actual = get_lights().set_lux(room, lux)
    print(f"Room {room}: {lux} lux -> {actual:.2f} mA (code {get_lights().code(room)})")
    return actual


def sweep(room):
    return get_lights().sweep(room)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Chamber white-light control (GP8403 current sink)")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("info", help="show constants, calibration and DAC status")
    p_off = sub.add_parser("off", help="turn white lights off")
    p_off.add_argument("room", nargs="?", type=int, choices=ROOMS)
    p_set = sub.add_parser("set", help="set a room's current in mA")
    p_set.add_argument("room", type=int, choices=ROOMS)
    p_set.add_argument("mA", type=float)
    p_lux = sub.add_parser("lux", help="set a room by lux (uses calibration)")
    p_lux.add_argument("room", type=int, choices=ROOMS)
    p_lux.add_argument("lux", type=float)
    p_sweep = sub.add_parser("sweep", help="calibrate a room with a lux meter")
    p_sweep.add_argument("room", type=int, choices=ROOMS)
    args = parser.parse_args(argv)

    if args.cmd is None:
        if sys.flags.interactive:
            print(get_lights().info())
            print("\nFunctions: off(), set_current_mA(room, mA), set_lux(room, lux), sweep(room)")
            return 0
        parser.print_help()
        return 0

    # `info` must not disturb a lit room - it has to be usable during a soak
    lights = get_lights(reset=args.cmd != "info")
    if not lights.hardware_ok and args.cmd != "info":
        print(f"ERROR: DAC not available: {lights.error}")
        return 1
    if args.cmd == "info":
        print(lights.info())
    elif args.cmd == "off":
        off(args.room)
        print("Off." if args.room is None else f"Room {args.room} off.")
    elif args.cmd == "set":
        set_current_mA(args.room, args.mA)
        print("(stays on after exit - run `off` to turn it off)")
    elif args.cmd == "lux":
        set_lux(args.room, args.lux)
        print("(stays on after exit - run `off` to turn it off)")
    elif args.cmd == "sweep":
        lights.sweep(args.room)
    # Release the lock but leave the DAC at its last value on purpose
    lights.dac.close()
    return 0


if __name__ == "__main__":
    code = main()
    if not sys.flags.interactive:
        sys.exit(code)
