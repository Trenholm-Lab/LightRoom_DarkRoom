# Pi bring-up note: white lights converted from PWM to an analog current sink

**Status:** code complete, **never executed on the Pi.** Everything below was written and
checked on a Windows dev machine with no I2C, no GPIO and no cameras, so the DAC path ran
only in simulation. The wiring in the chambers has already been changed. Nothing has been
measured yet.

**Read first:** `analog_dimming_simulation_check_new.pdf` (in this repo) - sections 6, 8 and 9
are the DuoStrip variant that was actually built. Sections 2 and 5 and the Bridgelux notes in
section 10 describe the *other* design, with a **3.0 ohm** sense resistor; those numbers do
not apply to this rig. If you cannot render the PDF, `pip install pypdf` and extract the text
- the figures are vector drawings and the text extracts cleanly.

---

## 1. What changed, in hardware

The white LEDs used to be PWM-dimmed by the Pi driving the IRLZ44N gates directly
(GPIO 12 = room 1, GPIO 18 = room 2). They are now a constant-current sink: a GP8403 DAC
sets a voltage, an OP295 holds that voltage across a sense resistor, and the LED current
follows. No switching, so no flicker and no audible whine.

Per room the change was two wires (PDF section 9):

- **gate wire moved**: off its Pi GPIO pin, onto the OP295 output (pin 1 for room 1,
  pin 7 for room 2). The existing gate resistor R22 / R20 stayed in place.
- **source wire lifted**: out of the ground net, into a new WAGO together with a 2.0 ohm
  sense resistor and a new sense wire back to the op-amp feedback.

Unchanged: the +24 V feed, the LED strips, the drain wiring, the fuse, the supply, and both
IR banks (Q1 / Q4 on **GPIO 27** and **GPIO 22**).

GPIO 12 and GPIO 18 are now unused by the lights. No code configures them any more.

## 2. What changed, in software

| File | Change |
|---|---|
| `chamber_lights.py` | **new.** GP8403 driver over `/dev/i2c-1`, lux/current conversion, per-room calibration, CLI |
| `light_widgets.py` | **new.** Per-room panel: IR checkbox, white checkbox, lux box, log slider, mA/code readout |
| `global_widgets.py` | hardware-PWM import, mock and `PWM_PIN_*` / `PWM_FREQ` removed; only the IR pins remain |
| `camera.py` | builds `ChamberLights`, warns once if the DAC is missing, writes a LIGHTING block to the session file, swaps both rooms in one I2C write |
| `verify_camera_settings.py` | lights the room under test through the DAC at 320 mA instead of 100 % PWM |
| `requirements.txt` | `rpi-hardware-pwm` dropped; `RPi.GPIO` still needed for IR |

The code's electrical constants were checked line by line against the PDF, and the raw I2C
register protocol against Adafruit's `adafruit_gp8403` source (range register `0x01` = `0x00`
for the 0-5 V range, both channels written as `<HH` at `0x02`, 12-bit value shifted left 4).
Those all agree. What has *not* been confirmed is that any of it does the right thing to real
silicon.

## 3. Numbers to check your meter against

    I_LED = V_dac / 4.9 / 2.0 ohm        full scale 5.00 V -> 510 mA
    one DAC count = 0.1246 mA            12 bit, 0-4095

| Setting | LED current | DAC code | V at DAC out | mV across the 2.0 ohm |
|---|---|---|---|---|
| `set 1 30` | 30.0 mA | 241 | 0.294 V | **60 mV** |
| `set 1 300` | 300.0 mA | 2408 | 2.940 V | **600 mV** |
| 10 lux (uncalibrated estimate) | 3.2 mA | 26 | 0.032 V | 6.4 mV |
| 100 lux (estimate) | 32.0 mA | 257 | 0.314 V | 64 mV |
| 1000 lux (estimate) | 320.0 mA | 2568 | 3.136 V | 640 mV |

The simulation predicts 3.05 / 30.6 / 306 mA for 10 / 100 / 1000 lux in a DuoStrip room; the
code ships 3.2 / 32 / 320 mA as the starting estimate, which is the rounded figure from the
PDF's parts list. Both are placeholders until `sweep()` is run.

## 4. Before touching anything

1. `sudo raspi-config` -> Interface Options -> I2C -> enable, then reboot.
2. `i2cdetect -y 1` must show the DAC. **Expect `58`.** The PDF says the board can sit
   anywhere in `0x58`-`0x5F` depending on its address jumpers; the code hardcodes `0x58`
   (`chamber_lights.py:56`). If yours answers elsewhere, that constant has to change - see
   gap 3 below.
3. Only one process may drive the DAC at a time; `chamber_lights.py` takes an `flock` on
   `/tmp/chamber_lights.lock`. Close the GUI before using the CLI and vice versa, or you get
   "another program ... is already controlling the lights".
4. `python3 chamber_lights.py info` prints the constants, the DAC status and the calibration.
   Note that it also **zeroes both channels** as a side effect - see gap 1.

**Hazards.** Do not run `gpio_full_test.py` with the DAC connected: it toggles GPIO 2 and 3,
which are now the I2C bus. The MOSFET tab is the drain and sits several volts above ground,
so the new heatsinks must not touch each other, the chassis or any ground wiring.

## 5. The six bench checks (PDF section 9) - none have been run

The PDF says to pass all six on room 1 before trusting room 2. Checks 3 to 6 are the ones
that matter for strips rather than modules, and they are the reason the DuoStrip variant was
in doubt until the 13 Oct bench test.

1. **Off is off.** `python3 chamber_lights.py off` -> LEDs dark, ~0 mV across each 2.0 ohm.
   Power-cycle everything: still dark before any script runs.
2. **Current tracks the command.** `set 1 300` -> 600 mV across the 2.0 ohm (+-3 %).
   `set 1 30` -> 60 mV. Repeat for room 2. *If a room goes to full brightness and ignores the
   command, its sense wire is loose or missing* - that is the one wiring mistake this circuit
   fails loudly on.
3. **Corners match at the dim end.** Lux at all four floor corners and the centre, at the
   1000 lux and the 10 lux setting. The corner-to-centre ratios should be similar at both.
   If a corner is more than ~1.5x off at 10 lux but fine at 1000 lux, the strips are not
   sharing current evenly when starved - stop and report it. (Section 5 predicts 2.6x
   brightest-to-dimmest between strings at 10 lux typical, 6.4x if the two reels are 150 mV
   apart. Total floor lux is unaffected either way; only the spatial pattern is.)
4. **Silent.** Ear close to the ceiling and to the breadboard at 1000, 100 and 10 lux.
5. **No flicker.** Pi camera at the ceiling, 100 us exposure, at each level: uniform frames,
   no bands, no frame-to-frame wobble.
6. **Heat and stability.** One hour at 1000 lux: heatsink warm, not too hot to touch. Lux
   within a few % at start and end. Same three levels again the next day at the same numbers.

If room 2 has not been converted yet, note that the staged "leave room 2 on PWM" path in the
PDF is no longer available - the PWM code is gone, so room 2's white light cannot be driven
at all until its two wires are moved.

## 6. Then calibrate

Lux is currently a linear guess (`DEFAULT_POINTS`, `chamber_lights.py:72`) and every readout
says "lux not calibrated (estimate)" until that is fixed.

    python3 chamber_lights.py sweep 1     # GUI closed; lux meter at the usual floor spot
    python3 chamber_lights.py sweep 2

It steps 0 to 500 mA (`SWEEP_CURRENTS_MA`, including 1-7 mA so the dim end is covered -
important, because at 10 lux the set-point is only 6.4 mV and the OP295's 300 uV worst-case
offset is ~5 % of it). Type each reading, Enter skips a step, `q` finishes. Saves to
`light_calibration.json`, which is **not** in `.gitignore` - decide whether per-rig
calibration belongs in the repo or should be ignored.

Restart the GUI afterwards. `reload_calibration()` exists but has no caller, and the lux
box/slider range is captured when the panel is built, so a live reload would not take effect.

## 7. Known code gaps - decide these with the hardware in front of you

1. **`info` turns the lights off.** `ChamberLights.__init__` ends with `self.off()`
   (`chamber_lights.py:277`) and `main()` constructs it for every subcommand
   (`chamber_lights.py:495`), so `info` zeroes both channels. The README promises that `set`
   and `lux` persist until `off` is run or the GUI starts. It also breaks check 6: you cannot
   query state during the one-hour soak without ending it.
2. **The readout can lie if an I2C write fails.** `set_codes` (`chamber_lights.py:283-288`)
   updates `self._codes` before `_push()`, so if the write raises mid-session the GUI - and
   `describe()`, whose mA / code / mV figures go **into the session data file** - report a
   current that was never delivered. Push first, or roll back on failure.
3. **I2C address hardcoded** at `0x58` (`chamber_lights.py:56`) although the PDF allows
   `0x58`-`0x5F`. A mismatch falls back silently to simulation with a misleading error.
   Probing the range would be a few lines.
4. **Docs say "1 k gate resistor"** (README and the `chamber_lights.py` docstring). The PDF
   reuses the existing R22 / R20 and says any value up to 2.2 kohm is fine as-is, swap only
   if it reads 4.7 kohm or more. Harmless electrically - the gate resistor does not enter the
   current equation - but please read the colour bands and correct the docs to match the rig.

## 8. Other things worth knowing

- The GUI starts room 1 white at 1000 lux and room 2 IR-only, and turns everything off on
  exit. First launch after the rewire will therefore drive ~320 mA into room 1 immediately.
- The slider reaches ~1594 lux (510 mA), above the 306 mA the simulation characterised.
  Electrically fine - the sense voltage at 510 mA into 2.0 ohm is 1.02 V, the same figure the
  PDF simulated at full scale into 3.0 ohm, and 0.52 W in a 2 W resistor - but the lux
  numbers up there are extrapolation.
- A level change is filtered at 20 Hz (796 ohm x 10 uF), so it settles in ~40 ms. `sweep()`
  waits 0.5 s before asking for a reading.
- Room swaps send both channels in one I2C transaction so the two rooms change together.
- If the DAC cannot be opened the GUI warns once and keeps running with the white lights
  simulated; the per-room readout turns red and says so.
