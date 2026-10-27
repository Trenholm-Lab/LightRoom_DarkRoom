#!/usr/bin/env python3
"""
Camera Control Verification

Checks that the controls the configuration dialog sends actually take effect on
the sensor and ISP, rather than being silently ignored.

Two kinds of check:

  Reported controls (ExposureTime, AnalogueGain, LensPosition, FrameDuration)
      are set, then read back from the camera's own frame metadata and compared.

  ISP controls (Brightness, Contrast, Saturation, Sharpness) are not echoed in
      metadata, so they are verified by measuring the image itself at a low and
      a high setting and checking the picture actually changed.

Focus gets a dedicated pair of tests, because LensPosition on the imx708 is only
honoured when AfMode is Manual. The application currently sets LensPosition
without touching AfMode, so the first test reproduces what the application does
and the second shows what it should do instead.

The ISP checks need light to measure, so Room 1's white light is switched on for
the duration unless --no-light is given.

Close the main application before running - it holds the cameras.

Usage:
    python3 verify_camera_settings.py              # both cameras
    python3 verify_camera_settings.py --camera 0   # just camera 0
    python3 verify_camera_settings.py --no-light   # leave the lights alone
"""
import argparse
import sys
import time

import numpy as np
from picamera2 import Picamera2

try:
    from libcamera import controls as libcontrols
    HAVE_AF_ENUM = hasattr(libcontrols, "AfModeEnum")
except Exception:
    libcontrols = None
    HAVE_AF_ENUM = False

# Frames to discard after a control change so the new value has been applied.
# Sensor controls take a few frames; the focus motor needs far longer to travel.
SETTLE_FRAMES = 15
LENS_SETTLE_FRAMES = 45

# White lights are driven by the GP8403 DAC current sink (chamber_lights.py).
# Each camera looks at its own room, so a focus sweep has to light the room
# that camera can see.
CAMERA_LIGHT_ROOM = {0: 1, 1: 2}  # camera index -> room
LIGHT_TEST_MA = 320.0             # ~63 % of full scale

# Auto algorithms are disabled in every request, otherwise AE/AWB overwrite the
# values being tested as soon as they are applied.
MANUAL_BASE = {"AeEnable": False, "AwbEnable": False}

# Exposure bounds used when metering a focus region. The scene is static, so a
# long exposure costs nothing but sweep time, and is always preferable to gain -
# gain adds noise, and noise looks like detail to a sharpness metric.
MAX_EXPOSURE_US = 60000
MAX_GAIN = 8.0
ROI_TARGET_MEAN = 110.0
ROI_MEAN_RANGE = (45.0, 170.0)


class Result:
    """One verification outcome, ready to print in the summary table."""

    def __init__(self, name, requested, actual, passed, note=""):
        self.name = name
        self.requested = requested
        self.actual = actual
        self.passed = passed
        self.note = note


class RoomLight:
    """A room's white light, held on so the image checks have something to see."""

    def __init__(self, enabled, room=1):
        self.enabled = enabled
        self.room = room
        self.lights = None

    def __enter__(self):
        if not self.enabled:
            print("Lighting: left untouched (--no-light)")
            return self
        try:
            from chamber_lights import ChamberLights
            lights = ChamberLights()
            if not lights.hardware_ok:
                raise RuntimeError(lights.error)
            self.lights = lights
            mA = lights.set_current_mA(self.room, LIGHT_TEST_MA)
            print(f"Lighting: Room {self.room} white light ON at {mA:.0f} mA")
            time.sleep(0.5)
        except Exception as e:
            self.lights = None
            print(f"Lighting: could not switch the white light on ({e})")
            print("          image checks need light - results may be unreliable")
        return self

    def __exit__(self, *exc):
        if self.lights is not None:
            try:
                self.lights.close()   # both rooms off, DAC released
                print("\nLighting: white light off")
            except Exception as e:
                print(f"\nLighting: error switching the light off: {e}")
        return False


def settle(picam, frames=SETTLE_FRAMES):
    """Wait for a control change to work through the pipeline."""
    for _ in range(frames):
        picam.capture_metadata()


def check_reported(picam, label, controls_to_set, read_key, expect, tolerance,
                   settle_frames=SETTLE_FRAMES):
    """
    Apply controls and read the resulting value back from frame metadata.

    Args:
        picam: Picamera2 instance, already started
        label: Name for the results table
        controls_to_set: Controls to send (auto algorithms are disabled as well)
        read_key: Metadata key holding the applied value
        expect: Value the metadata should report
        tolerance: Allowed fractional difference (0.15 = 15%)
        settle_frames: Frames to wait before reading back

    Returns:
        Result: with the requested and actually applied values
    """
    payload = dict(MANUAL_BASE)
    payload.update(controls_to_set)

    try:
        picam.set_controls(payload)
    except Exception as e:
        return Result(label, expect, None, False, f"set_controls raised: {e}")

    settle(picam, settle_frames)
    metadata = picam.capture_metadata()

    if read_key not in metadata:
        return Result(label, expect, None, False,
                      f"{read_key} not reported in frame metadata")

    actual = metadata[read_key]
    spread = abs(actual - expect) / max(abs(expect), 1e-9)
    passed = spread <= tolerance

    return Result(label, expect, round(actual, 3) if isinstance(actual, float) else actual,
                  passed, f"off by {spread*100:.1f}%")


def crop_to_roi(frame, roi):
    """
    Cut a frame down to a region of interest.

    Args:
        frame: Image array
        roi: (x, y, w, h) as fractions of the frame, or None for the whole frame

    Returns:
        The cropped array
    """
    if roi is None:
        return frame

    height, width = frame.shape[:2]
    x, y, w, h = roi
    x0, y0 = int(x * width), int(y * height)
    x1, y1 = int((x + w) * width), int((y + h) * height)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, max(x1, x0 + 2)), min(height, max(y1, y0 + 2))
    return frame[y0:y1, x0:x1]


def image_stats(picam, roi=None):
    """
    Measure the current image.

    Args:
        picam: Picamera2 instance, already started
        roi: Optional (x, y, w, h) fractional region to measure instead of the
             whole frame - a focus sweep should only look where it matters,
             otherwise background texture decides the answer

    Returns:
        dict: mean brightness, contrast (std), colour saturation and a
              high-frequency energy figure that tracks sharpening
    """
    frame = crop_to_roi(picam.capture_array("main").astype(np.float32), roi)

    if frame.ndim == 3 and frame.shape[2] >= 3:
        rgb = frame[:, :, :3]
        grey = rgb.mean(axis=2)
        # Distance between the channels: grey has none, vivid colour has lots
        saturation = float(np.mean(rgb.max(axis=2) - rgb.min(axis=2)))
    else:
        grey = frame if frame.ndim == 2 else frame[:, :, 0]
        saturation = 0.0

    # Difference between neighbouring pixels rises as the image is sharpened
    high_freq = float(np.mean(np.abs(np.diff(grey, axis=0))) +
                      np.mean(np.abs(np.diff(grey, axis=1))))

    mean = float(grey.mean())

    return {
        "mean": mean,
        "std": float(grey.std()),
        "saturation": saturation,
        "high_freq": high_freq,
        # Dividing by brightness makes this a contrast measure rather than an
        # intensity one, so a drifting light source does not masquerade as a
        # change in focus.
        "sharpness": high_freq / max(mean, 1.0),
    }


def check_isp(picam, name, low, high, metric, min_change):
    """
    Verify an ISP control by measuring the picture at two settings.

    Args:
        picam: Picamera2 instance, already started
        name: Control name, e.g. "Brightness"
        low, high: The two values to compare
        metric: Key from image_stats() this control should move
        min_change: Smallest change in that metric that counts as working

    Returns:
        Result: carrying both measurements
    """
    try:
        picam.set_controls({name: low})
        settle(picam)
        stats_low = image_stats(picam)

        picam.set_controls({name: high})
        settle(picam)
        stats_high = image_stats(picam)
    except Exception as e:
        return Result(name, f"{low} -> {high}", None, False, f"raised: {e}")

    change = stats_high[metric] - stats_low[metric]
    passed = change >= min_change

    note = f"{metric} {stats_low[metric]:.2f} -> {stats_high[metric]:.2f}"
    if not passed:
        if max(stats_low["mean"], stats_high["mean"]) < 10.0:
            note += "  (image is nearly black - too dark to measure)"
        else:
            note += f"  (needed +{min_change})"

    return Result(name, f"{low} -> {high}", f"change {change:+.2f}", passed, note)


def check_focus(picam, lens_range):
    """
    Test LensPosition the way the application does it, then the way it should.

    Args:
        picam: Picamera2 instance, already started
        lens_range: The camera's advertised (min, max) LensPosition

    Returns:
        list[Result]: one for the application's current approach, one with
                      AfMode set to Manual first
    """
    low, high = lens_range
    # A position clearly away from wherever autofocus would settle
    target = round(low + 0.75 * (high - low), 2)

    results = []

    # 1. What the application does today: LensPosition alone, with autofocus
    #    left in whatever mode it powered up in.
    if HAVE_AF_ENUM:
        try:
            picam.set_controls({"AfMode": libcontrols.AfModeEnum.Continuous})
            settle(picam, LENS_SETTLE_FRAMES)
        except Exception:
            pass

    results.append(check_reported(
        picam, "LensPosition (AfMode untouched)",
        {"LensPosition": target}, "LensPosition", target,
        tolerance=0.10, settle_frames=LENS_SETTLE_FRAMES,
    ))

    # 2. The correct sequence: switch to manual focus in the same request.
    if HAVE_AF_ENUM:
        results.append(check_reported(
            picam, "LensPosition (AfMode=Manual)",
            {"AfMode": libcontrols.AfModeEnum.Manual, "LensPosition": target},
            "LensPosition", target,
            tolerance=0.10, settle_frames=LENS_SETTLE_FRAMES,
        ))

        # And prove it tracks a second, different position
        second = round(low + 0.25 * (high - low), 2)
        results.append(check_reported(
            picam, "LensPosition (Manual, 2nd value)",
            {"AfMode": libcontrols.AfModeEnum.Manual, "LensPosition": second},
            "LensPosition", second,
            tolerance=0.10, settle_frames=LENS_SETTLE_FRAMES,
        ))
    else:
        results.append(Result("LensPosition (AfMode=Manual)", target, None, False,
                              "libcamera AfModeEnum unavailable"))

    return results


def lock_exposure(picam, roi=None):
    """
    Freeze exposure and gain at whatever auto-exposure settled on.

    A focus sweep compares image sharpness between frames, so the brightness has
    to stay put while the lens moves.

    Returns:
        tuple: (exposure_us, gain) that were locked in
    """
    picam.set_controls({"AeEnable": True, "AwbEnable": True})
    settle(picam, 40)
    metadata = picam.capture_metadata()

    exposure = metadata.get("ExposureTime", 20000)
    gain = metadata.get("AnalogueGain", 1.0)

    picam.set_controls({
        "AeEnable": False,
        "AwbEnable": False,
        "ExposureTime": int(exposure),
        "AnalogueGain": float(gain),
    })
    settle(picam)

    # Drive the region of interest towards mid-grey. A blown-out target has no
    # contrast left to focus on, and a near-black one is mostly sensor noise -
    # both make the sharpness reading meaningless. Exposure is adjusted first,
    # and gain only once exposure has run out of room.
    low_target, high_target = ROI_MEAN_RANGE
    for _ in range(6):
        roi_mean = image_stats(picam, roi)["mean"]
        if low_target <= roi_mean <= high_target:
            break

        scale = min(max(ROI_TARGET_MEAN / max(roi_mean, 1.0), 0.2), 5.0)
        new_exposure = int(min(max(200, exposure * scale), MAX_EXPOSURE_US))

        if new_exposure != int(exposure):
            exposure = new_exposure
            picam.set_controls({"ExposureTime": int(exposure)})
            settle(picam)
            continue

        # Exposure is pinned at a limit; lift the gain if it is still too dark
        if roi_mean < low_target and gain < MAX_GAIN:
            gain = min(MAX_GAIN, gain * 2.0)
            picam.set_controls({"AnalogueGain": float(gain)})
            settle(picam)
            continue
        break

    final_mean = image_stats(picam, roi)["mean"]
    if final_mean < low_target:
        print(f"WARNING: the measured region is still dark (mean {final_mean:.0f})"
              " - add light or pick a brighter region")
    elif final_mean > high_target:
        print(f"WARNING: the measured region is close to saturation "
              f"(mean {final_mean:.0f}) - detail may be clipped away")

    return exposure, gain


def measure_sharpness(picam, position, roi=None, samples=3):
    """
    Move the lens to a position and measure how sharp the image is.

    Args:
        picam: Picamera2 instance, already started
        position: LensPosition to test
        roi: Fractional region to measure, or None for the whole frame
        samples: Frames to average, to ride out sensor noise

    Returns:
        float: Normalised high-frequency energy - higher is sharper
    """
    controls = {"LensPosition": position}
    if HAVE_AF_ENUM:
        controls["AfMode"] = libcontrols.AfModeEnum.Manual
    picam.set_controls(controls)
    settle(picam, LENS_SETTLE_FRAMES)

    return sum(image_stats(picam, roi)["sharpness"] for _ in range(samples)) / samples


def focus_sweep(index, roi=None):
    """
    Find the sharpest LensPosition for one camera, with its room lit.

    Sweeps coarsely across the whole range, then finely around the peak, and
    prints the value to store in default_config.json.

    Args:
        index: Camera index (0 or 1)
    """
    print("=" * 74)
    print(f"FOCUS SWEEP - CAMERA {index}")
    print("=" * 74)

    picam = Picamera2(index)
    try:
        picam.configure(picam.create_preview_configuration(
            main={"size": (1280, 720), "format": "RGB888"}))
        picam.start()
        time.sleep(1.5)

        if "LensPosition" not in picam.camera_controls:
            print("This sensor has no focus motor - nothing to sweep.\n")
            return None

        low, high = picam.camera_controls["LensPosition"][:2]
        exposure, gain = lock_exposure(picam, roi)
        print(f"Exposure locked at {int(exposure)} us, gain {gain:.2f}"
              + ("  (gain raised - expect a noisier reading)" if gain > 2.0 else ""))
        if roi:
            print(f"Measuring region x={roi[0]:.2f} y={roi[1]:.2f} "
                  f"w={roi[2]:.2f} h={roi[3]:.2f} of the frame")
        else:
            print("Measuring the whole frame")

        mean = image_stats(picam, roi)["mean"]
        print(f"Scene brightness: mean pixel {mean:.1f}")
        if mean < 15:
            print("WARNING: the scene is very dark - sharpness readings will be noise")
        print()

        # Coarse pass across the full range
        print(f"{'LensPosition':<14} {'sharpness':<12} (dioptres -> focus distance)")
        print("-" * 60)
        coarse = {}
        position = low
        while position <= high:
            sharpness = measure_sharpness(picam, position, roi)
            coarse[position] = sharpness
            distance = "infinity" if position <= 0.01 else f"{100/position:.0f} cm"
            bar = "#" * int(sharpness * 3)
            print(f"{position:<14.2f} {sharpness:<12.3f} {distance:<10} {bar}")
            position += 1.0

        best_coarse = max(coarse, key=coarse.get)

        # Fine pass around the peak
        print(f"\nRefining around {best_coarse:.2f}...")
        fine = {}
        position = max(low, best_coarse - 1.0)
        stop = min(high, best_coarse + 1.0)
        while position <= stop + 1e-9:
            sharpness = measure_sharpness(picam, position, roi)
            fine[position] = sharpness
            print(f"{position:<14.2f} {sharpness:<12.3f}")
            position += 0.25

        best = max(fine, key=fine.get)
        distance = "infinity" if best <= 0.01 else f"{100/best:.0f} cm"

        # Measure the same position twice more to see how much of the spread
        # above is real. If repeat noise is comparable to the focus signal, the
        # scene has too little detail for this to mean anything.
        repeats = [measure_sharpness(picam, best, roi) for _ in range(2)]
        spread = max(repeats + [fine[best]]) - min(repeats + [fine[best]])
        signal = max(coarse.values()) - min(coarse.values())

        print()
        print(f"Sharpest LensPosition: {best:.2f}  (~{distance})")
        print(f"  sharpness there:  {fine[best]:.4f}")
        print(f"  repeat measurements at the same position: "
              f"{', '.join(f'{r:.4f}' for r in repeats)}")
        print(f"  repeat noise {spread:.4f} vs focus signal {signal:.4f} "
              f"across the full range")

        if spread > 0.4 * signal:
            print()
            print("  UNRELIABLE: the noise between identical measurements is a")
            print("  large fraction of the difference focus makes. The scene")
            print("  probably has too little fine detail to focus on - put a")
            print("  printed target (text or a checkerboard) on the floor of the")
            print("  box, where the mouse would be, and run this again.")
            return None

        return best

    finally:
        try:
            picam.stop()
            picam.close()
        except Exception:
            pass


def sharpness_map(index):
    """
    Measure sharpness across a 3x3 grid of the frame.

    Defocus softens a frame fairly evenly and always responds to LensPosition.
    Something on the glass - a smudge, a droplet, a protective film - degrades
    the area behind it regardless of focus, so comparing regions separates the
    two. A centre that is worse than its own corners is not a focus problem.

    Args:
        index: Camera index (0 or 1)
    """
    print("=" * 74)
    print(f"SHARPNESS MAP - CAMERA {index}")
    print("=" * 74)

    picam = Picamera2(index)
    try:
        picam.configure(picam.create_still_configuration(main={"size": (2304, 1296)}))
        picam.start()
        time.sleep(2.0)

        metadata = picam.capture_metadata()
        controls = {"AeEnable": False, "AwbEnable": False,
                    "ExposureTime": int(metadata.get("ExposureTime", 10000)),
                    "AnalogueGain": float(metadata.get("AnalogueGain", 1.0))}
        if HAVE_AF_ENUM:
            controls["AfMode"] = libcontrols.AfModeEnum.Manual
        controls["LensPosition"] = 0.0
        picam.set_controls(controls)
        settle(picam, LENS_SETTLE_FRAMES)

        # Does the centre respond to focus at all?
        centre = (0.4, 0.3, 0.2, 0.15)
        response = {}
        for position in (0.0, 0.5, 1.0, 2.0):
            response[position] = measure_sharpness(picam, position, centre, samples=2)

        spread = max(response.values()) / max(min(response.values()), 1e-9)
        print("Centre sharpness vs LensPosition: " +
              "  ".join(f"{k:g} -> {v:.4f}" for k, v in response.items()))
        print(f"  focus changes the centre by {spread:.1f}x")
        if spread < 1.5:
            print("  the centre barely responds to focus - the blur is not defocus")
        print()

        frame = picam.capture_array("main")
        height, width = frame.shape[:2]
        print("Sharpness across the frame (brightness in brackets):")
        cells = []
        for row in range(3):
            line = []
            for col in range(3):
                block = frame[int(height*row/3):int(height*(row+1)/3),
                              int(width*col/3):int(width*(col+1)/3)]
                grey = block[:, :, :3].mean(axis=2).astype(np.float32)
                hf = (np.mean(np.abs(np.diff(grey, axis=0))) +
                      np.mean(np.abs(np.diff(grey, axis=1))))
                value = hf / max(grey.mean(), 1.0)
                cells.append(value)
                line.append(f"{value:.4f} (m{grey.mean():3.0f})")
            print("   " + "  ".join(line))

        middle = cells[4]
        corners = [cells[0], cells[2], cells[6], cells[8]]
        print()
        print(f"Centre {middle:.4f} vs corner average {sum(corners)/4:.4f}")
        if middle < 0.7 * (sum(corners) / 4):
            print("  The centre is markedly worse than the corners. That points to")
            print("  something on the glass - a smudge, droplet, condensation or a")
            print("  protective film - rather than a focus or sensor problem.")

    finally:
        try:
            picam.stop()
            picam.close()
        except Exception:
            pass


def verify_camera(index):
    """
    Run the full verification against one camera.

    Args:
        index: Camera index (0 or 1)

    Returns:
        list[Result]: every check performed
    """
    print("=" * 74)
    print(f"CAMERA {index}")
    print("=" * 74)

    picam = Picamera2(index)
    results = []

    try:
        config = picam.create_preview_configuration(
            main={"size": (640, 480), "format": "RGB888"}
        )
        picam.configure(config)
        picam.start()
        time.sleep(1.5)  # let the auto algorithms converge before overriding them

        available = picam.camera_controls
        model = picam.camera_properties.get("Model", "unknown")
        print(f"Model: {model}")
        print(f"Controls advertised: {len(available)}")

        lens_range = None
        if "LensPosition" in available:
            lens_range = available["LensPosition"][:2]
            print(f"LensPosition range: {lens_range[0]} to {lens_range[1]}")
        else:
            print("LensPosition: NOT SUPPORTED (no focus motor on this sensor)")
        print()

        # Sensor controls, reported back in metadata
        results.append(check_reported(
            picam, "ExposureTime (20000)", {"ExposureTime": 20000},
            "ExposureTime", 20000, tolerance=0.15))
        results.append(check_reported(
            picam, "ExposureTime (8000)", {"ExposureTime": 8000},
            "ExposureTime", 8000, tolerance=0.15))
        results.append(check_reported(
            picam, "AnalogueGain (4.0)", {"AnalogueGain": 4.0},
            "AnalogueGain", 4.0, tolerance=0.15))

        # FrameDuration is reported, but it is FrameDurationLimits that is set
        results.append(check_reported(
            picam, "FrameDurationLimits (30fps)",
            {"FrameDurationLimits": (33333, 33333)},
            "FrameDuration", 33333, tolerance=0.15))

        # Focus
        if lens_range:
            results.extend(check_focus(picam, lens_range))
        else:
            results.append(Result("LensPosition", "-", None, False,
                                  "sensor has no focus motor"))

        # ISP controls, verified by measuring the image
        results.append(check_isp(picam, "Brightness", -0.6, 0.6, "mean", 5.0))
        results.append(check_isp(picam, "Contrast", 0.2, 2.0, "std", 1.0))
        results.append(check_isp(picam, "Saturation", 0.0, 2.0, "saturation", 1.0))
        results.append(check_isp(picam, "Sharpness", 0.0, 8.0, "high_freq", 0.3))

    finally:
        try:
            picam.stop()
            picam.close()
        except Exception:
            pass

    return results


def print_results(results):
    """Print one camera's results as a table."""
    print(f"{'CONTROL':<34} {'REQUESTED':<14} {'ACTUAL':<16} RESULT")
    print("-" * 74)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        actual = "none" if r.actual is None else str(r.actual)
        print(f"{r.name:<34} {str(r.requested):<14} {actual:<16} {status}")
        if r.note:
            print(f"{'':<34} {r.note}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Verify that camera control changes actually take effect."
    )
    parser.add_argument("--camera", default="both",
                        help="Camera to test: 0, 1, or both (default: both)")
    parser.add_argument("--no-light", action="store_true",
                        help="Do not switch the white light on for the test")
    parser.add_argument("--roi", default="0.3,0.3,0.4,0.4",
                        help="Region the focus sweep measures, as fractions of "
                             "the frame: x,y,w,h (default: 0.3,0.3,0.4,0.4, the "
                             "central 40%%). Use 'full' for the whole frame.")
    parser.add_argument("--sharpness-map", action="store_true",
                        help="Measure sharpness across the frame, to tell blur "
                             "on the glass apart from a focus error")
    parser.add_argument("--focus-sweep", action="store_true",
                        help="Find the sharpest LensPosition for each camera "
                             "instead of running the verification")
    args = parser.parse_args()

    if args.camera == "both":
        indices = [0, 1]
    elif args.camera in ("0", "1"):
        indices = [int(args.camera)]
    else:
        parser.error("--camera must be 0, 1, or both")

    if args.sharpness_map:
        for index in indices:
            with RoomLight(enabled=not args.no_light,
                           room=CAMERA_LIGHT_ROOM.get(index, 1)):
                print()
                sharpness_map(index)
        return 0

    if args.focus_sweep:
        if args.roi.lower() == "full":
            roi = None
        else:
            try:
                roi = tuple(float(v) for v in args.roi.split(","))
                if len(roi) != 4 or not all(0 <= v <= 1 for v in roi):
                    raise ValueError
            except ValueError:
                parser.error("--roi must be four fractions x,y,w,h or 'full'")

        best = {}
        for index in indices:
            # Light the room this camera is actually looking at
            with RoomLight(enabled=not args.no_light,
                           room=CAMERA_LIGHT_ROOM.get(index, 1)):
                print()
                best[index] = focus_sweep(index, roi)
        print("\n" + "=" * 74)
        print("SUGGESTED default_config.json VALUES")
        print("=" * 74)
        for index, position in best.items():
            if position is not None:
                print(f'  camera "{index}": "LensPosition": {position:.2f}')
        return 0

    all_results = {}
    with RoomLight(enabled=not args.no_light,
                   room=CAMERA_LIGHT_ROOM.get(indices[0], 1)):
        print()
        for index in indices:
            try:
                all_results[index] = verify_camera(index)
                print_results(all_results[index])
            except Exception as e:
                print(f"Camera {index}: verification could not run: {e}")
                print("Is the main application still running? It holds the cameras.\n")

    print("=" * 74)
    print("SUMMARY")
    print("=" * 74)
    failures = 0
    for index, results in all_results.items():
        failed = [r for r in results if not r.passed]
        failures += len(failed)
        print(f"Camera {index}: {len(results) - len(failed)}/{len(results)} passed")
        for r in failed:
            print(f"    FAILED: {r.name} - {r.note or 'no value applied'}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
