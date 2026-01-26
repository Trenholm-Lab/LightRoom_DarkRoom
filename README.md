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
- **Session Management**: 
  - User-defined session names
  - Automatic file naming: `{session_name}_camera_1.h264`, `{session_name}_camera_2.h264`
  - Comprehensive session data logging
- **File Protection**: Warns before overwriting existing recordings
- **Resizable Layout**: Adjustable GUI components

## Hardware Supported

The two cameras we have access to at the moment are the following:
1. the Camera Module 2.1 NoIR
2. the Camera Module 3 NoIR Wide

To operate, use modules from the *rpicam-apps* and *Picamera 2* libraries.

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

3. Run the application:
```bash
python3 main.py
```

## Usage

### Initial Setup
1. On first launch, select camera ports for LightRoom and DarkRoom cameras
2. The preview will start automatically

### Recording a Session

#### Basic Recording (Manual Mode)
1. Set the stop method to "Manual" in the Recording Controller
2. Click "Start Recording"
3. Choose a save directory
4. Enter a session name
5. Optional: Wait for countdown if recording delay is set
6. Click "Stop Recording" when finished

#### Timed Recording
1. Set the stop method to "Timer" in the Recording Controller
2. Set the timer duration (1-60 minutes, in 0.5-minute increments)
3. Click "Start Recording"
4. Choose save directory and session name
5. Recording will automatically stop when timer reaches zero, or click "Stop Recording" to end early

#### Recording Delay (Countdown)
- Set recording delay (0-120 seconds) in the Recording Controller
- After clicking "Start Recording" and selecting save location/name, a countdown will display
- Gives you time to prepare before recording starts
- Cancel button available during countdown

### Camera Configuration
1. Click the gear icon on any camera widget
2. Adjust settings in the configuration popup
3. Changes apply immediately to the preview
4. Save configurations as presets using the dropdown menu
5. Load saved presets from the dropdown

### Output Files

Each recording session produces:
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
Session Name: experiment_001
Save Path: /home/user/recordings

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
Video File: experiment_001_camera_1.h264
Start Time: 14:30:25
End Time: 14:35:40

Camera Configuration:
  FrameDurationLimits: (8333, 8333)
  ExposureTime: 8000
  Resolution: 1920 x 1080
  ...
```

## Application Structure

- **main.py**: Application entry point
- **gui_container.py**: Main window and layout
- **camera.py**: Camera control and recording logic
- **global_widgets.py**: Reusable widgets (recording controls, countdown, etc.)
- **data_manager.py**: Centralized data management and state
- **config.py**: Configuration management

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
