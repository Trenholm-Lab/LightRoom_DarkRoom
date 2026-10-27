# LightRoom DarkRoom - Dual Camera Recording System

A PyQt5-based dual camera recording application for Raspberry Pi using Picamera2. This application provides synchronized control of two cameras with live preview, configurable recording parameters, and comprehensive session data logging.

[Official Pi Camera Documentation](https://www.raspberrypi.com/documentation/accessories/camera.html)

## Features

- **Dual Camera Control**: Simultaneous control of two cameras (LightRoom and DarkRoom)
- **Live Preview**: Real-time camera preview with on/off toggle
- **Recording Modes**:
  - **Manual Mode**: User-controlled recording with elapsed timer
  - **Timer Mode**: Automatic stop after preset duration (1-60 minutes)
- **Pre-Recording Countdown**: Optional countdown delay (0-120 seconds) before recording starts
- **Camera Configuration**: Live configuration of camera settings with preview updates
  - Exposure time
  - Focus/lens position
  - Brightness, saturation, contrast, sharpness
  - Resolution and zoom/crop
  - Frame rate
- **Configuration Presets**: Save and load camera configurations (JSON files)
- **Session Info Tab**: Subject and trial metadata (Mouse ID, genotype, sex, date of birth,
  trial #, lux per room) entered once and carried over between trials
- **Session Management**: 
  - Automatic file naming from the session metadata - no name is typed
  - Files are named `{mouse_id}_{date}_trial{N}_camera_1.mp4` and `..._camera_2.mp4`
  - Comprehensive session data logging
- **Room Lighting**: IR on/off per room, and white light set in **percent** per room through an
  analog current sink (GP8403 DAC + OP295) - no PWM, no flicker, silent
- **Automatic Light Swapping**: Optionally swap the two rooms' lighting at a fixed interval during recording
- **File Protection**: Warns before overwriting existing recordings
- **Resizable Layout**: Adjustable GUI components

## Hardware Supported

The two cameras we have access to at the moment are the following:
1. the Camera Module 2.1 NoIR
2. the Camera Module 3 NoIR Wide

To operate, use modules from the *rpicam-apps* and *Picamera 2* libraries.

Lighting (per room): an IR bank switched by GPIO, and white DuoStrip LEDs driven by an
analog current sink - Adafruit GP8403 DAC (product 6516, I2C 0x58) -> 3.9 k/1 k divider ->
OP295 op-amp -> the existing gate resistor (R22 room 1 / R20 room 2, any value up to
2.2 k is fine as-is) -> IRLZ44N -> 2.0 ohm sense resistor. The gate resistor does not enter
the current equation.

Per room the MOSFET source leaves the ground net and goes to a WAGO with the 2.0 ohm sense
resistor and a sense wire back to the op-amp feedback. **Both rooms' sense resistors, the
breadboard ground rail and the wire to the global ground must meet in one WAGO** - a star.
Daisy-chaining them puts one room's return current through the other's feedback: 15 milliohms
of shared ground was enough to make an idle room glow when the other ran at full scale.

Expected values, for checking against a meter:

| Point | Value |
|---|---|
| Sense voltage | current x 2.0 ohm (300 mA -> 600 mV, 30 mA -> 60 mV) |
| MOSFET Vds | ~3.8 V at 306 mA |
| MOSFET dissipation | ~1.2 W at 306 mA - it is a *linear* sink, so this is continuous |
| Heatsink | <=10 C/W bolt-on, or a 70 x 70 x 3 mm aluminium plate mounted vertically |

Two checks worth repeating after any rewiring: **off is off** (both rooms dark, ~0 mV across
each sense resistor, including after a power cycle before any script runs), and **current
tracks the command** (`set 1 300` -> 600 mV). A room that goes to full brightness and ignores
the command has a loose or missing sense wire - the one wiring fault this circuit fails
loudly on. A room that stays dark has lost its gate drive or its current path.

The MOSFET tab is the drain, several volts above ground: heatsinks must not touch each other,
the chassis or any ground wiring.

| Function | Pi pin(s) | Notes |
|---|---|---|
| DAC (STEMMA QT cable) | 1 (3.3 V), 3 (SDA), 5 (SCL), 6 (GND) | I2C bus 1 |
| Op-amp supply | 2 (5 V) | OP295 pin 8 |
| IR room 1 / room 2 | GPIO 27 / GPIO 22 | unchanged |
| (old white PWM) | GPIO 12 / GPIO 18 | no longer used |

## Installation

### Requirements
- Raspberry Pi with Raspberry Pi OS Bookworm or later
- Two compatible Raspberry Pi cameras
- Python 3.7+
- PyQt5
- Picamera2

### Setup
1. Install required packages:
```bash
pip install -r requirements.txt
```

2. Ensure Picamera2 is available (comes with Raspberry Pi OS):
```bash
python3 -c "import picamera2"
```

3. Enable I2C for the white-light DAC (once): `sudo raspi-config` -> Interface Options -> I2C,
   then reboot. `i2cdetect -y 1` should show the DAC at `58`. No extra Python package is
   needed - `chamber_lights.py` talks to `/dev/i2c-1` directly.

4. Run the application:
```bash
python3 main.py
```

## Usage

### Initial Setup
1. On first launch, select camera ports for LightRoom and DarkRoom cameras
2. The preview will start automatically

### Session Info (Subject & Trial Metadata)

The window has two tabs: **Recording** (live previews and controls) and **Session Info**.

The Session Info tab collects the metadata stored with every recording:

| Field | Notes |
|-------|-------|
| Mouse ID | Also used to pre-fill the suggested session name |
| Genotype | Free text |
| Sex | Male / Female / Unknown |
| Date of Birth | Date picker; the subject's age in days is recorded automatically |
| Trial | Free text - `3`, `2b` and `retest` are all valid. Set manually for each trial |
| Lux in Room 1 | Measured light level (0 is a valid value) |
| Lux in Room 2 | Measured light level (0 is a valid value) |
| Comment | Optional. Appended to the end of the file name, e.g. `_habituation` |

- **Every field must be filled in before the first trial.** "Start Recording" is blocked
  until then, and the missing fields are listed for you.
- **Between trials you only edit what changed.** Everything else is carried over, including
  across application restarts (stored in `last_session_metadata.json`).
- The trial number is yours to set. It carries over like every other field, so remember to
  change it before each new trial or the next recording will overwrite the previous one
  (the overwrite warning will tell you first).
- **These fields name your files.** Recordings are saved as
  `{mouse_id}_{date}_trial{trial}`, with the comment appended when there is one, e.g.
  `M123_2026-09-21_trial4_camera_1.mp4` or `M123_2026-09-21_trial2b_habituation_camera_1.mp4`.
  You are never prompted for a file name. Characters that are illegal in file names
  (spaces, `/ \ : * ? " < > |`) become underscores.
- "New Mouse" clears the subject fields and resets the trial number to 1.

### Recording a Session

#### Basic Recording (Manual Mode)
1. Fill in the Session Info tab (first trial only - later trials just need the changes)
2. Choose a save directory with the Browse button
3. Set the stop method to "Manual" in the Recording Controller
4. Click "Start Recording" - files are named automatically from the session metadata
5. Optional: Wait for countdown if recording delay is set
6. Click "Stop Recording" when finished

#### Timed Recording
1. Set the stop method to "Timer" in the Recording Controller
2. Set the timer duration (1-60 minutes, in 0.5-minute increments)
3. Click "Start Recording"
4. Recording will automatically stop when timer reaches zero, or click "Stop Recording" to end early

#### Recording Delay (Countdown)
- Set recording delay (0-120 seconds) in the Recording Controller
- After clicking "Start Recording", a countdown will display
- Gives you time to prepare before recording starts
- Cancel button available during countdown

### Camera Configuration
1. Click the gear icon on any camera widget
2. Adjust settings in the configuration popup
3. Changes apply immediately to the preview
4. Save configurations as presets using the dropdown menu
5. Load saved presets from the dropdown

### Output Files

Each recording session produces, with `{session_name}` built automatically as
`{mouse_id}_{date}_trial{trial}` plus the optional comment (e.g.
`M123_2026-09-21_trial4` or `M123_2026-09-21_trial2b_habituation`):
- `{session_name}_camera_1.mp4` - Converted Video from camera 1
- `{session_name}_camera_2.mp4` - Converted Video from camera 2
- `{session_name}_data.txt` - Comprehensive session metadata
- *(Note: Raw `.h264` files are generated initially but automatically converted to `.mp4` and deleted)*

### Post-Processing & Optimization

- **Automatic Conversion**: The system automatically converts raw H.264 streams to MP4 format after recording stops.
- **Auto-Cleanup**: Original H.264 files are deleted after successful conversion to save disk space.
- **Hardcoded Conversion Settings**:
  - The converter script (`convert_h264_to_mp4.py`) currently forces a **30 FPS** frame rate during conversion to match the default camera configuration.
  - If you change the camera's frame rate in the configuration, you may need to manually update the frame rate flag (`-r 30`) in `convert_h264_to_mp4.py` to match, otherwise video playback speed may be incorrect.
- **Resolution & Crop**: 
  - Default recording resolution is set to **640x480** for stability.
  - A 100-pixel crop is applied to all sides of the video.
  - Bitrate is capped at **3 Mbps** to prevent dropped frames.

### Session Data File

The `{session_name}_data.txt` file contains:
- **Session Information**: Name and save path
- **Subject Information**: Mouse ID, genotype, sex, date of birth, age at recording
- **Trial Information**: Trial, lux in room 1 and room 2, comment
- **Timing Information**: Start/end timestamps, duration, elapsed seconds
- **Recording Parameters**: Stop method, timer duration, countdown delay
- **Per-Camera Data**:
  - Video filename
  - Start/end times
  - Camera configuration (resolution, exposure, focus, brightness, etc.)
  - Applied camera settings

Example format:
```
============================================================
RECORDING SESSION DATA
============================================================

SESSION INFORMATION
------------------------------------------------------------
Session Name: M123_trial3
Save Path: /home/user/recordings

SUBJECT INFORMATION
------------------------------------------------------------
Mouse ID: M123
Genotype: C57BL/6J
Sex: Female
Date of Birth: 2025-03-01
Age at Recording: 244 days

TRIAL INFORMATION
------------------------------------------------------------
Trial: 3
Lux in Room 1: 320.5
Lux in Room 2: 0.0
Comment: habituation

TIMING INFORMATION
------------------------------------------------------------
Start Date/Time: 2025-10-30 14:30:25
End Date/Time: 2025-10-30 14:35:40
Total Duration: 00:05:15
Elapsed Seconds: 315

RECORDING PARAMETERS
------------------------------------------------------------
Stop Method: Manual
Recording Delay (Countdown): 20 seconds

CAMERA 1 (LightRoom)
------------------------------------------------------------
Video File: M123_trial3_camera_1.h264
Start Time: 14:30:25
End Time: 14:35:40

Camera Configuration:
  FrameDurationLimits: (8333, 8333)
  ExposureTime: 8000
  Resolution: 1920 x 1080
  ...
```

## White Lights (analog current sink)

The white lights are set as a **percent of full-scale LED current**. No lux meter and no
calibration are involved - percent maps straight to current, and current to a DAC code:

    LED current = DAC volts / 4.9 / 2.0 ohm      (0.125 mA per DAC count, 510 mA at full scale)

    100 % = 510 mA      50 % = 255 mA      10 % = 51 mA      1 % = 5.1 mA

In the GUI each room has an **IR** checkbox and a **White** checkbox with a percent box and a
linear slider (0.1 % resolution). Under it is the LED current, DAC code and expected sense
voltage actually being sent, so a meter reading can be checked against it at any time. On
start-up room 1 is white at 60 % (~306 mA) and room 2 is IR only; on exit everything is
switched off. The light settings at the start of each recording, and the number of light
swaps, are written to the session data file under **LIGHTING**.

Note that the **Lux in Room 1 / Room 2** fields on the Session Info tab are something
different: they record a light level you measured with a meter, for the session metadata.
They are not connected to the brightness control.

If the DAC can't be opened (I2C off, cable loose, or `chamber_lights.py` running in a
terminal) the program warns once and keeps running with the white lights simulated.

### Command line (`chamber_lights.py`)

Close the GUI first - only one program can drive the DAC at a time.

```bash
python3 chamber_lights.py info        # DAC status, mA per count, live output, percent scale
python3 chamber_lights.py off         # both rooms dark
python3 chamber_lights.py set 1 300   # room 1 at 300 mA  -> 0.60 V across its 2.0 ohm
python3 chamber_lights.py set 1 30    # room 1 at 30 mA   -> 60 mV
python3 chamber_lights.py pct 2 25    # room 2 at 25 % of full scale (~128 mA)
```

The DAC keeps its value after the command exits, so `set` and `pct` leave the light on until
`off` is run or the GUI is started. `info` is read-only and will not disturb a lit room.
Interactive use also works: `python3 -i chamber_lights.py`, then `off()`,
`set_current_mA(1, 300)`, `set_percent(1, 25)`.

### Bench checks after wiring (from the simulation document)

1. `off` -> LEDs dark, ~0 mV across each 2.0 ohm. Power-cycle: still dark before any script runs.
2. `set 1 300` -> 0.60 V (+-3 %) across room 1's 2.0 ohm; `set 1 30` -> 60 mV. Same for room 2.
   If a room goes to full brightness and ignores the command, check its sense wire first.

## Application Structure

- **main.py**: Application entry point
- **gui_container.py**: Main window and layout
- **camera.py**: Camera control and recording logic
- **global_widgets.py**: Reusable widgets (recording controls, session info form, countdown, etc.)
  and the IR GPIO pin definitions
- **chamber_lights.py**: White-light driver for the GP8403 DAC current sink: percent/current
  conversion and the command-line tool
- **light_widgets.py**: The per-room lighting panel (IR, white percent box/slider, readout)
- **data_manager.py**: Centralized data management and state, including subject/trial metadata
- **config.py**: Configuration management
- **verify_camera_settings.py**: Standalone check that camera controls actually take
  effect on the sensor and ISP (run with the main application closed)

## Camera Hardware
*as listed on the official Pi documentation website*
** Both cameras use a rolling shutter as opposed to the global shutter. 

||Camera Module V2| Camera Module 3 Wide| 
|---------|-----------| --------- | 
|Still resolution|8 megapixels|11.9 megapixels|
|Video modes|1080p47, 1640 × 1232p41 and 640 × 480p206| 2304 × 1296p56, 2304 × 1296p30 HDR, 1536 × 864p120|
|Sensor|Sony IMX219|Sony IMX708|
|Sensor resolution|3280 × 2464 pixels|4608 × 2592 pixels|
|Pixel size|1.12 µm × 1.12 µm|1.4 µm × 1.4 µm|
|Optical size|1/4"|1/2.43"|
|Focus|Adjustable|Motorized|
|Depth of field|Approx 10 cm to ∞|Approx 5 cm to ∞|
|Focal length|3.04 mm|2.75 mm|
|Horizontal FoV|62.2 degrees|102 degrees|
|Vertical FoV|48.8 degrees|67 degrees|
|Focal ratio F-Stop|F2.0|F2.2|
|Maximum exposure time (sec.)|11.76|112|

*Both the HQ Camera and the Global Shutter Camera, have support for synchronous captures. Making use of the XVS pin (Vertical Sync) allows one camera to pulse when a frame capture is initiated. The other camera can then listen for this sync pulse, and capture a frame at the same time as the other camera.*

***
## Technical Notes

### Camera Software Stack

libcamera is an open-source camera stack for Linux systems, providing low-level control of cameras on various hardware, including Raspberry Pi.
The Raspberry Pi team customized libcamera for their hardware and initially provided applications like libcamera-still, libcamera-vid, and others.
With Raspberry Pi OS Bookworm, these camera applications have been renamed to rpicam-* (e.g., rpicam-still, rpicam-vid), reflecting the Pi-specific optimizations.

- **Picamera2** is a Python library built on libcamera, providing programmatic control of the Raspberry Pi camera. It's ideal for Python projects that require image processing, video capture, or custom camera configurations.
- **Rpicam** consists of command-line applications (rpicam-still, rpicam-vid, etc.) built on libcamera, designed for quick image or video capture and automation via terminal commands or scripts.

*Use Picamera2 for Python development and Rpicam for simple or script-driven tasks. Both leverage the same underlying camera stack for optimized performance on Raspberry Pi hardware.*

### Performance Considerations

- **Preview During Recording**: The application disables preview during recording to optimize performance. This saves CPU/GPU resources, reduces memory bandwidth usage, and improves encoder performance.
- **H.264 Encoding**: Videos are encoded using H.264Encoder for efficient compression
- **Simultaneous Recording**: Both cameras record simultaneously but run in the same process

### Using Multiple Cameras

"libcamera does not yet provide stereoscopic camera support. When running two cameras simultaneously, they must be run in separate processes. This means there is no way to synchronize sensor framing or 3A operation between them. As a workaround, you could synchronize the cameras through an external sync signal for the HQ (IMX477) camera, and switch the 3A to manual mode if necessary."

*Note: This application runs both cameras in the same process for GUI coordination. For frame-level synchronization, external hardware sync would be required.*

### Camera Synchronization

*Both the HQ Camera and the Global Shutter Camera, have support for synchronous captures. Making use of the XVS pin (Vertical Sync) allows one camera to pulse when a frame capture is initiated. The other camera can then listen for this sync pulse, and capture a frame at the same time as the other camera.*

***
## Configurable Camera Control Options

The application supports configuration of the following camera parameters:

- **sharpness**: Image sharpness adjustment
- **contrast**: Contrast level
- **brightness**: Brightness level
- **saturation**: Color saturation
- **exposure/shutter**: Exposure time in microseconds
- **gain**: Analog and digital gain
- **lens-position**: Moves lens to fixed focal distance in dioptres (for motorized focus cameras)
- **Resolution**: Video capture resolution
- **ScalerCrop**: Zoom/crop region

Additional parameters available through libcamera:
- ev (exposure value)
- metering (sets metering mode of AEC/AGC algo)
- awb (Auto White Balance)
- awbgains
- denoise
- tuning-file (way to set all of these things at once)
- autofocus-mode
- autofocus-range
- autofocus-speed
- autofocus-window

***
## Video Recording Details

### Output Format
- Codec: H.264
- Container: Raw H.264 stream (.h264 files)
- Can be converted to MP4 or other containers using ffmpeg:
  ```bash
  ffmpeg -i session_name_camera_1.h264 -c copy session_name_camera_1.mp4
  ```

### Video Options
- **codec**: H.264 encoder used for video output
- **framerate**: Records at the specified framerate from camera configuration
- **resolution**: Configurable through camera settings

### libcamera Pipeline
"RaspberryPi provides a custom pipeline handler which libcamera uses to drive the sensor and image signal processor (ISP) on the Raspberry Pi. libcamera contains a collection of image-processing algorithms (IPAs) including auto exposure/gain control (AEC/AGC), auto white balance (AWB), and auto lens-shading correction (ALSC)."

***
## Development Notes

### Using Picamera2 with Qt
- rpicam-apps includes an option to use Qt for a camera preview window
- This application integrates Picamera2 directly with PyQt5
- Make sure to run code using Picamera2 from a venv that has access to global packages

### Tuning Files
Use libcamera tuning files to customize camera behavior for specific cameras or lighting conditions.

***
## Troubleshooting

### Camera Not Detected
- Check camera connections
- Verify cameras are enabled in `raspi-config`
- Check camera ports match the configuration

### Preview Issues
- If preview is black, check camera permissions
- Ensure only one application is accessing cameras at a time
- Try toggling preview off and on

### Recording Issues
- Ensure sufficient disk space for recordings
- Check write permissions for save directory
- H.264 files can be large; monitor storage space

### White Lights
- "White lights not available" at start-up: check `i2cdetect -y 1` shows `58`, that I2C is
  enabled, and that `chamber_lights.py` isn't running in another terminal
- A room is at full brightness whatever the setting: its sense wire (WAGO S -> breadboard) is
  loose or missing
- A room stays dark: check the op-amp has 5 V on pin 8, and the gate wire / gate resistor
- The MOSFETs run warm: they are linear current sinks, so they dissipate
  (24 V - LED string voltage) x current continuously. They need their heatsinks fitted

### Performance
- Disable preview during recording for best performance
- Lower resolution if experiencing dropped frames
- Close other applications to free resources

***
## References

- [Official Pi Camera Documentation](https://www.raspberrypi.com/documentation/accessories/camera.html)
- [Picamera2 Library Documentation](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)
- [libcamera Documentation](https://libcamera.org/)
- [rpicam-apps Documentation](https://www.raspberrypi.com/documentation/computers/camera_software.html)
## Camera Control Options
- sharpness
- contrast
- brightness
- saturation
- ev (exposure value)
- shutter (specify the exposure time in microseconds)
- gain
- metering (sets metering mode of AEC/AGC algo
- exposure
- awb (Auto White Balance)
- awbgains
- denoise
- tuning-file (way to set all of these things at once)
- autofocus-mode
- autofocus-range
- autofocus-speed
- autofocus-window
- lens-position (moves lens to fixed focal distance in dioptres)

## Output options
- wrap (sets max value for counter used by output. Counter resets to zero after reaching this value
- flush (flushes output files to disk as soon as a frame finished writing instead of waiting for the system to handle it)

## Video options
To pass one of the following options to an application, prefix with --
- codec (sets the encoder to use for video output
- save-pts (only for pi4 and lower). for pi5 use libav to automatically generate timestamps for container formats
- signal
- initial (specifies whether to start the application with video output enabled or disabled) 
- split (writes video output from separate recording sessions into separate files)
- inline (writes sequence header in every intra frame which can help decode the video sequence from any point in the video (only works with H.264 format)
- framerate (records exactly the specified framerate)

rpicam-vid: 
- configures the encoder with a callback that handles the buffer containing the encoded image data. rpicam-vid can't recycle buffer data until the event loop, preview window, AND encoder all discard their references.

***
## Using libcamera with Qt
rpicam-apps includes an option to use Qt for a camera preview window

But Qt has errors with libcamera files. 


***
## Picamera2
Python interface to work with libcamera 
- read included PDF for detailed information
- make sure to run code using Picamera2 from a venv that has access to global packages
