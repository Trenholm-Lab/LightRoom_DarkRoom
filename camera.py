"""
Camera control module for LightRoom DarkRoom dual camera recording system.

This module provides camera preview, recording, and configuration functionality
for Raspberry Pi cameras using Picamera2. Supports dual camera operation with
synchronized recording, live preview, and comprehensive configuration management.

Classes:
    Camera: Individual camera widget with preview and recording capabilities
    CameraControlWidget: Main controller for multiple cameras with recording management
"""

from PyQt5.QtCore import Qt, QTimer, QTime
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QImage, QPixmap
from picamera2 import Picamera2
from picamera2.previews.qt import QGlPicamera2
from picamera2.encoders import H264Encoder
from libcamera import Transform
from pathlib import Path
import numpy as np
from data_manager import *
from config import *
from global_widgets import RightColumnWidget

# Debug flag: set to True to enable verbose debug prints
DEBUG = False

def dprint(*args, **kwargs):
    """Print debug messages when DEBUG is enabled."""
    if DEBUG:
        print(*args, **kwargs)


class Camera(QWidget):
    """
    Individual camera widget with preview and recording capabilities.
    
    Manages a single Picamera2 instance, providing live preview using OpenGL
    or software rendering, and H.264 video recording with configuration capture.
    
    Args:
        data_manager: Global data manager instance
        CamDisp_num: Physical camera port number on Raspberry Pi
    """
    
    def __init__(self, data_manager, CamDisp_num, rotation=0):
        super().__init__()
        self.cam_layout = QVBoxLayout()
        # Remove margins and spacing for tight preview layout
        self.cam_layout.setContentsMargins(0, 0, 0, 0)
        self.cam_layout.setSpacing(0)
        self.data_manager = data_manager
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(
            int((self.data_manager.main_window_size['W']-30)/8), 
            int(self.data_manager.main_window_size['H']*3/18)
        )

        self.CamDisp_num = CamDisp_num
        self.rotation = rotation  # Store rotation (0, 90, 180, 270)
        self.preview_off_widget = QWidget()
        self.preview_off_widget.setStyleSheet("background-color: black;")

        self.picam = Picamera2(self.CamDisp_num)
        self.picam_preview_widget = None
        self.configuration_popup = ConfigPopup(self.data_manager, self)

        self.setLayout(self.cam_layout)
    
    def config_pop(self):
        """
        Show the camera configuration popup dialog.
        Refreshes values from current Picamera2 state before displaying.
        """
        if hasattr(self, 'configuration_popup') and self.configuration_popup is not None:
            try:
                # refresh popup from currently-applied Picamera2 state so it shows loaded values
                try:
                    if hasattr(self.configuration_popup, 'refresh_from_picam'):
                        self.configuration_popup.refresh_from_picam()
                except Exception:
                    pass
            except Exception:
                pass
            self.configuration_popup.exec_()

    def initialize_preview(self):
        """
        Configure and show the OpenGL preview using QGlPicamera2.
        
        Stops the camera, creates preview configuration, merges any current
        camera controls, and starts the preview widget. Removes any existing
        preview widgets to prevent duplicates.
        """
        print(f"[DEBUG] initialize_preview: enter for Camera {self.CamDisp_num}")
        dprint(f"[camera] initialize_preview: enter for Camera {self.CamDisp_num}")
        try:
            # stop camera before reconfiguring (safe if not running)
            try:
                if hasattr(self.picam, 'started') and self.picam.started:
                    self.picam.stop()
                    dprint(f"[camera] initialize_preview: picam.stop() called for {self.CamDisp_num}")
            except Exception as e:
                dprint(f"[camera] initialize_preview: picam.stop() failed: {e}")

            # Check if we already have a preview widget - if so, just reuse it
            has_existing_widget = hasattr(self, 'picam_preview_widget') and self.picam_preview_widget is not None
            if has_existing_widget:
                print(f"[DEBUG] initialize_preview: Reusing existing preview widget for Camera {self.CamDisp_num}")
                # Don't delete it, just restart the camera and the widget will continue working
                try:
                    # Make sure it's in the layout and visible
                    if self.picam_preview_widget.parent() != self:
                        self.cam_layout.addWidget(self.picam_preview_widget, 1)
                    self.picam_preview_widget.show()
                except Exception as e:
                    print(f"[DEBUG] initialize_preview: Error showing existing widget: {e}")
            else:
                # remove any existing preview widgets so layout doesn't shrink or duplicate
                try:
                    if hasattr(self, 'picam_preview_widget') and self.picam_preview_widget is not None:
                        try:
                            # Properly stop and cleanup the old preview widget
                            self.picam_preview_widget.hide()
                            self.cam_layout.removeWidget(self.picam_preview_widget)
                            self.picam_preview_widget.deleteLater()
                            dprint(f"[camera] initialize_preview: removed old picam_preview_widget for {self.CamDisp_num}")
                        except Exception as e:
                            dprint(f"[camera] initialize_preview: error removing old preview widget: {e}")
                        self.picam_preview_widget = None
                except Exception:
                    pass
            try:
                if hasattr(self, 'software_preview_label') and self.software_preview_label is not None:
                    try:
                        self.cam_layout.removeWidget(self.software_preview_label)
                        self.software_preview_label.deleteLater()
                    except Exception:
                        pass
                    self.software_preview_label = None
            except Exception:
                pass

            # create a standard preview configuration (no transform)
            # If a requested preview size was set by the UI, use it.
            # Otherwise, default to 640x360 (16:9 aspect ratio) to match typical recording resolution
            try:
                if hasattr(self, 'requested_preview_size') and getattr(self, 'requested_preview_size'):
                    req = getattr(self, 'requested_preview_size')
                    config = self.picam.create_preview_configuration(main={'size': req})
                    # consume the request so future calls use defaults unless changed again
                    try:
                        delattr(self, 'requested_preview_size')
                    except Exception:
                        try:
                            del self.requested_preview_size
                        except Exception:
                            pass
                else:
                    # Use 640x360 (16:9) instead of default 640x480 (4:3) to match recording aspect ratio
                    config = self.picam.create_preview_configuration(main={'size': (640, 360)})
            except Exception:
                config = self.picam.create_preview_configuration(main={'size': (640, 360)})
            try:
                # Diagnostic: print the preview configuration that will be used
                try:
                    dprint(f"[camera] initialize_preview: created preview config for {self.CamDisp_num}: {config}")
                except Exception:
                    pass

                # Merge any currently-set Picamera2 controls (from set_controls) into the
                # preview configuration so frame-duration and other settings are honored
                try:
                    picam_controls = None
                    # Prefer an explicit get_controls() call if available (returns dict-like)
                    if hasattr(self.picam, 'get_controls'):
                        try:
                            gc = self.picam.get_controls()
                            dprint(f"[camera] initialize_preview: picam.get_controls() -> {gc}")
                            if isinstance(gc, dict):
                                picam_controls = dict(gc)
                            else:
                                try:
                                    picam_controls = dict(gc)
                                except Exception:
                                    # try to iterate items()
                                    try:
                                        picam_controls = {k: v for k, v in gc.items()}
                                    except Exception:
                                        picam_controls = None
                        except Exception as e:
                            dprint(f"[camera] initialize_preview: picam.get_controls() failed: {e}")

                    # Fallback: inspect self.picam.controls attribute
                    if not picam_controls and hasattr(self.picam, 'controls') and self.picam.controls is not None:
                        try:
                            cobj = self.picam.controls
                            # dict-like?
                            if isinstance(cobj, dict):
                                picam_controls = dict(cobj)
                            elif hasattr(cobj, 'items'):
                                picam_controls = {k: v for k, v in cobj.items()}
                            else:
                                # last resort: str parsing (not ideal) - attempt to extract the braces content
                                s = str(cobj)
                                # look for first '{' and last '}' and evaluate safely using literal_eval
                                from ast import literal_eval
                                try:
                                    start = s.find('{')
                                    end = s.rfind('}')
                                    if start != -1 and end != -1 and end > start:
                                        inner = s[start:end+1]
                                        picam_controls = literal_eval(inner)
                                except Exception:
                                    picam_controls = None
                        except Exception as e:
                            dprint(f"[camera] initialize_preview: error reading picam.controls: {e}")

                    # If we have controls from the Picamera2 instance, inject them into config['controls']
                    if picam_controls:
                        if 'controls' not in config or config['controls'] is None:
                            config['controls'] = {}
                        # update config controls with any keys from picam_controls
                        try:
                            config['controls'].update(picam_controls)
                            dprint(f"[camera] initialize_preview: merged picam.controls into preview config for {self.CamDisp_num}: {picam_controls}")
                        except Exception as e:
                            dprint(f"[camera] initialize_preview: failed to merge picam.controls: {e}")
                except Exception as e:
                    dprint(f"[camera] initialize_preview: error while merging controls: {e}")

                self.picam.configure(config)
                dprint(f"[camera] initialize_preview: picam.configure() succeeded for {self.CamDisp_num}")
            except Exception as e:
                dprint(f"[camera] configure failed: {e}; attempting to continue")
            # Diagnostic: show camera_controls exposed by Picamera2 after configure
            try:
                dprint(f"[camera] initialize_preview: picam.camera_controls={getattr(self.picam, 'camera_controls', None)}")
            except Exception:
                pass

            # Create QGlPicamera2 widget with keep_ar=True to maintain aspect ratio (only if we don't have one already)
            # This prevents cropping of the captured image in the preview
            # Apply rotation transform if specified (180 degrees = hflip + vflip)
            if not has_existing_widget:
                print(f"[DEBUG] initialize_preview: Creating QGlPicamera2 widget for Camera {self.CamDisp_num}")
                transform = None
                if self.rotation == 180:
                    transform = Transform(hflip=1, vflip=1)
                elif self.rotation == 90:
                    transform = Transform(transpose=1, vflip=1)
                elif self.rotation == 270:
                    transform = Transform(transpose=1, hflip=1)
                
                self.picam_preview_widget = QGlPicamera2(
                    self.picam, 
                    parent=self, 
                    keep_ar=True,
                    transform=transform
                )
                print(f"[DEBUG] initialize_preview: QGlPicamera2 widget created successfully for Camera {self.CamDisp_num}")
            try:
                self.picam_preview_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            except Exception:
                pass
            # add with stretch so it takes available space
            try:
                self.cam_layout.addWidget(self.picam_preview_widget, 1)
                print(f"[DEBUG] initialize_preview: Widget added to layout for Camera {self.CamDisp_num}")
            except Exception as e:
                # fallback to add without stretch
                print(f"[DEBUG] initialize_preview: First add failed, trying fallback for Camera {self.CamDisp_num}: {e}")
                self.cam_layout.addWidget(self.picam_preview_widget, alignment=Qt.AlignCenter)
            dprint(f"[camera] initialize_preview: added picam_preview_widget for {self.CamDisp_num}")
            
            # Start the camera to begin preview streaming (only if not already started)
            try:
                if not (hasattr(self.picam, 'started') and self.picam.started):
                    self.picam.start()
                    dprint(f"[camera] initialize_preview: picam.start() called for {self.CamDisp_num}")
                else:
                    dprint(f"[camera] initialize_preview: camera {self.CamDisp_num} already started, skipping start()")
            except Exception as e:
                dprint(f"[camera] initialize_preview: Error starting camera {self.CamDisp_num}: {e}")
            
            # ensure software preview attributes cleared
            if hasattr(self, 'software_preview_timer'):
                try:
                    self.software_preview_timer.stop()
                except Exception:
                    pass
                self.software_preview_timer = None
            self.software_preview_label = None
            print(f"[DEBUG] initialize_preview: Completed successfully for Camera {self.CamDisp_num}")
        except Exception as e:
            print(f"[DEBUG] initialize_preview: ERROR for Camera {self.CamDisp_num}: {e}")
            import traceback
            traceback.print_exc()
            dprint(f"[camera] initialize_preview error: {e}")
        # ensure software preview attributes cleared
        if hasattr(self, 'software_preview_timer'):
            try:
                self.software_preview_timer.stop()
            except Exception:
                pass
            self.software_preview_timer = None
        self.software_preview_label = None

    def initialize_software_preview(self, rotation_deg=0):
        """
        Fallback preview using frame capture and QLabel display.
        
        Captures frames from Picamera2, applies rotation, and displays in QLabel.
        Used when OpenGL preview is unavailable or rotation is needed.
        
        Args:
            rotation_deg: Rotation angle in degrees (0, 90, 180, 270)
        """
        try:
            # Use 640x360 (16:9) to match recording aspect ratio
            config = self.picam.create_preview_configuration(main={'size': (640, 360)})
            self.picam.configure(config)
        except Exception:
            try:
                config = self.picam.create_preview_configuration(main={'size': (640, 360)})
                self.picam.configure(config)
            except Exception as e:
                print(f"[camera] Failed to configure camera for software preview: {e}")
                return

        # create a QLabel to show frames
        self.software_preview_label = QLabel(parent=self)
        self.software_preview_label.setAlignment(Qt.AlignCenter)
        self.software_preview_label.setStyleSheet("background-color: black;")
        self.cam_layout.addWidget(self.software_preview_label)

        # start camera and timer to poll frames
        try:
            self.picam.start()
        except Exception:
            pass

        self.software_rotation = int(rotation_deg) % 360
        # timer interval (ms) - 30 FPS default
        interval_ms = 33
        self.software_preview_timer = QTimer(self)
        self.software_preview_timer.timeout.connect(self._software_preview_update)
        self.software_preview_timer.start(interval_ms)

    def _software_preview_update(self):
        """
        Timer callback to capture and display rotated frames in software preview.
        """
        try:
            arr = self.picam.capture_array()  # capture from default stream (main)
            # arr expected shape (H, W, 3) RGB
            if arr is None:
                return
            # rotate using numpy
            k = 0
            if self.software_rotation == 90:
                k = 3  # clockwise 90
            elif self.software_rotation == 180:
                k = 2
            elif self.software_rotation == 270:
                k = 1
            if k != 0:
                arr = np.rot90(arr, k=k)

            h, w, ch = arr.shape
            bytes_per_line = ch * w
            # ensure RGB888
            img = QImage(arr.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pix = QPixmap.fromImage(img)
            self.software_preview_label.setPixmap(pix.scaled(self.software_preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            # On capture errors, silently ignore (camera may be busy)
            # print for debug
            print(f"[camera] software preview update error: {e}")
            return

    def start_recording(self, output_file_path):
        """
        Start recording video to the specified file path.
        Stops preview and starts H264 encoding.
        
        :param output_file_path: Full path to the output video file
        :return: Dictionary with 'success' (bool) and 'config' (dict) keys
        """
        try:
            dprint(f"[camera] start_recording: Starting recording for Camera {self.CamDisp_num} to {output_file_path}")
            
            # Stop any preview that's running
            try:
                self.picam.stop()
            except Exception as e:
                dprint(f"[camera] start_recording: Error stopping preview: {e}")
            
            # Hide preview widgets
            if hasattr(self, 'picam_preview_widget') and self.picam_preview_widget is not None:
                self.picam_preview_widget.hide()
            if hasattr(self, 'software_preview_label') and self.software_preview_label is not None:
                self.software_preview_label.hide()
            if hasattr(self, 'software_preview_timer') and self.software_preview_timer is not None:
                self.software_preview_timer.stop()
            
            # Show the "preview off" widget during recording
            if hasattr(self, 'preview_off_widget') and self.preview_off_widget is not None:
                try:
                    self.cam_layout.addWidget(self.preview_off_widget)
                    self.preview_off_widget.show()
                except Exception:
                    pass
            
            # Create video configuration for recording
            try:
                # 1. Start with lowest resolution (640x480) for best performance
                resolution = (640, 480)
                
                # 2. Check for requested size (legacy)
                if hasattr(self, 'requested_preview_size') and self.requested_preview_size:
                    resolution = self.requested_preview_size
                
                # 3. Check for applied_controls (from ConfigPopup live apply)
                elif hasattr(self, 'applied_controls') and self.applied_controls and 'Resolution' in self.applied_controls:
                    try:
                        resolution = tuple(self.applied_controls['Resolution'])
                    except Exception:
                        pass

                # 4. Check loaded or default config file
                else:
                    try:
                        import json
                        # Check for loaded config path, else default
                        cfg_path = None
                        if hasattr(self, 'loaded_config_path') and self.loaded_config_path:
                            p = Path(self.loaded_config_path)
                            if p.exists():
                                cfg_path = p
                        
                        if cfg_path is None:
                            # Use config in script directory
                            p = Path(__file__).parent / 'default_config.json'
                            if p.exists():
                                cfg_path = p
                        
                        if cfg_path:
                            data = json.loads(cfg_path.read_text())
                            cam_key = str(self.CamDisp_num)
                            if cam_key in data and 'Resolution' in data[cam_key]:
                                resolution = tuple(data[cam_key]['Resolution'])
                    except Exception as e:
                        dprint(f"[camera] start_recording: error reading config file for resolution: {e}")

                dprint(f"[camera] start_recording: Using resolution {resolution}")
                video_config = self.picam.create_video_configuration(main={'size': resolution})
                
                # Apply cropping to video configuration (crop 100 pixels from all sides)
                # Full sensor resolution is slightly larger than 1080p, but we'll base crop on relative coordinates if possible.
                # ScalerCrop format is [x, y, width, height] in sensor coordinates (0-aligned)
                # For imx708 sensor (4608 x 2592), reducing 100 pixels on each side:
                # x = 100, y = 100, w = sensor_w - 200, h = sensor_h - 200
                # Using 100 pixels crop on each side as requested
                # Note: This overrides default config crop. If precise sensor info isn't available, this might need tuning.
                
                # Create default crop
                sensor_w = 4608 # IMX708
                sensor_h = 2592
                crop_x = 100
                crop_y = 100
                crop_w = sensor_w - 200
                crop_h = sensor_h - 200
                
                # Store crop in controls_to_apply later to override defaults
                forced_crop = [crop_x, crop_y, crop_w, crop_h]
                
                # Merge controls from applied_controls or config if available
                # This ensures FPS/Framerate settings are respected during recording
                controls_to_apply = {}
                
                # Get controls from config file if we loaded resolution from there
                if hasattr(self, 'applied_controls') and self.applied_controls:
                    controls_to_apply.update(self.applied_controls)
                else:
                     try:
                        # Try to load other controls from file too
                        import json
                        cfg_path = Path(__file__).parent / 'default_config.json'
                        if cfg_path.exists():
                            data = json.loads(cfg_path.read_text())
                            cam_key = str(self.CamDisp_num)
                            if cam_key in data:
                                controls_to_apply.update(data[cam_key])
                     except:
                        pass

                # Apply our forced crop (100px from each side)
                controls_to_apply['ScalerCrop'] = forced_crop

                # Remove Resolution from controls as it's handled by video_config
                if 'Resolution' in controls_to_apply:
                    del controls_to_apply['Resolution']
                
                # If we have controls, put them into the video config
                if controls_to_apply:
                    if 'controls' not in video_config:
                        video_config['controls'] = {}
                    video_config['controls'].update(controls_to_apply)

            except Exception as e:
                dprint(f"[camera] start_recording: Error creating config, falling back: {e}")
                video_config = self.picam.create_video_configuration()
            
            # Apply the video configuration
            self.picam.configure(video_config)
            
            # Capture the actual configuration that will be used
            actual_config = {}
            try:
                # Get camera controls
                camera_controls = self.picam.camera_controls
                actual_config['FrameDurationLimits'] = camera_controls.get('FrameDurationLimits', 'N/A')
                actual_config['ExposureTime'] = camera_controls.get('ExposureTime', 'N/A')
                actual_config['AnalogueGain'] = camera_controls.get('AnalogueGain', 'N/A')
                actual_config['LensPosition'] = camera_controls.get('LensPosition', 'N/A')
                actual_config['Brightness'] = camera_controls.get('Brightness', 'N/A')
                actual_config['Saturation'] = camera_controls.get('Saturation', 'N/A')
                actual_config['Contrast'] = camera_controls.get('Contrast', 'N/A')
                actual_config['Sharpness'] = camera_controls.get('Sharpness', 'N/A')
                
                # Get video configuration
                actual_config['Resolution'] = video_config.get('main', {}).get('size', 'N/A')
                actual_config['Format'] = video_config.get('main', {}).get('format', 'N/A')
                
            except Exception as e:
                dprint(f"[camera] start_recording: Could not capture full config: {e}")
            
            # Create H264 encoder with bitrate limit for better performance
            # Lower bitrate = smaller files, better for long recordings
            # 3 Mbps is good quality for 640x480
            self.encoder = H264Encoder(bitrate=3000000)
            
            # Start recording
            self.picam.start_recording(self.encoder, output_file_path)
            dprint(f"[camera] start_recording: Recording started successfully for Camera {self.CamDisp_num}")
            
            return {'success': True, 'config': actual_config}
            
        except Exception as e:
            print(f"[camera] start_recording: ERROR starting recording for Camera {self.CamDisp_num}: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'config': {}}
    
    def stop_recording(self):
        """
        Stop the current recording and return to preview mode.
        
        :return: True if recording stopped successfully, False otherwise
        """
        try:
            dprint(f"[camera] stop_recording: Stopping recording for Camera {self.CamDisp_num}")
            
            # Stop the recording
            try:
                self.picam.stop_recording()
                dprint(f"[camera] stop_recording: Recording stopped for Camera {self.CamDisp_num}")
            except Exception as e:
                dprint(f"[camera] stop_recording: Error stopping recording: {e}")
            
            # Stop the camera
            try:
                self.picam.stop()
            except Exception as e:
                dprint(f"[camera] stop_recording: Error stopping camera: {e}")
            
            # Hide the "preview off" widget
            if hasattr(self, 'preview_off_widget') and self.preview_off_widget is not None:
                try:
                    self.cam_layout.removeWidget(self.preview_off_widget)
                    self.preview_off_widget.hide()
                except Exception:
                    pass
            
            # DON'T reinitialize preview here - let start_stop_preview handle it
            # This prevents double initialization which causes lag
            dprint(f"[camera] stop_recording: Recording stopped for Camera {self.CamDisp_num}")
            
            return True
            
        except Exception as e:
            print(f"[camera] stop_recording: ERROR stopping recording for Camera {self.CamDisp_num}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def closeEvent(self, event):
        print(f"Safely closing Camera {self.CamDisp_num}")
        try:
            # stop the camera if running
            if hasattr(self, 'picam') and self.picam is not None:
                self.picam.stop()
        except Exception:
            pass
        # close preview widget if it exists
        if hasattr(self, 'picam_preview_widget') and self.picam_preview_widget is not None:
            try:
                self.picam_preview_widget.close()
            except Exception:
                pass
        if hasattr(self, 'software_preview_timer') and self.software_preview_timer is not None:
            try:
                self.software_preview_timer.stop()
            except Exception:
                pass
        if hasattr(self, 'software_preview_label') and self.software_preview_label is not None:
            try:
                self.software_preview_label.clear()
            except Exception:
                pass
        event.accept()


class CameraControlWidget(QWidget):
    """
    Main controller widget for managing multiple cameras.
    
    Manages camera preview, recording sessions, countdown timers, and session
    data logging. Coordinates dual camera operation with synchronized start/stop.
    
    Args:
        data_manager: Global data manager instance with camera settings
    """
    
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        
        # Store camera widgets first
        self.camera_widgets = {}
        self.cameras_list = []  # Ordered list of cameras

        for i, room in enumerate(["LightRoom", "DarkRoom"]): 
            if self.data_manager.camera_settings[room]['disp_num'] is not None:
                # Rotate the second camera (DarkRoom) by 180 degrees
                rotation = 180 if i == 1 else 0
                cam = Camera(self.data_manager, self.data_manager.camera_settings[room]['disp_num'], rotation=rotation)
                self.camera_widgets[room] = cam
                self.cameras_list.append((room, cam))
        
        # Create ConfigSetupWidget
        self.global_setup = None
        try:
            cams = list(self.camera_widgets.values())
            if len(cams) >= 2:
                cam_a, cam_b = cams[0], cams[1]
                # define opener
                def open_combined():
                    try:
                        from config import CombinedConfigDialog
                        dlg = CombinedConfigDialog(self.data_manager, cam_a, cam_b, parent=self)
                        dlg.exec_()
                    except Exception:
                        try:
                            # fallback: open individual popups
                            cam_a.config_pop()
                            cam_b.config_pop()
                        except Exception:
                            pass

                # Create one global setup widget (pass first camera as reference)
                self.global_setup = ConfigSetupWidget(self.data_manager, cam_a, parent_widget=self)
                self.global_setup.set_modify_callback(open_combined)
                
                # Set all cameras for config loading
                self.global_setup.set_all_cameras([cam_a, cam_b])
                
                # Store reference so other code can update the UI
                try:
                    cam_a.setup_widget = self.global_setup
                    cam_b.setup_widget = self.global_setup
                except Exception:
                    pass
            elif len(cams) == 1:
                # Single camera: setup widget under that camera
                cam = cams[0]
                self.global_setup = ConfigSetupWidget(self.data_manager, cam, parent_widget=self)
                self.global_setup.set_all_cameras([cam])
                try:
                    cam.setup_widget = self.global_setup
                except Exception:
                    pass
        except Exception:
            pass
        
        # Temporary layout until control widgets are provided
        self._control_widgets_set = False
        # Don't set a layout yet - will be set when set_control_widgets is called

        # Light swapping timer
        self.swap_timer = QTimer(self)
        self.swap_timer.timeout.connect(self.swap_lighting_states)

        self.data_manager.start_stop_toggled_signal.connect(self.start_stop_recording)
    
    def set_control_widgets(self, save_path_widget, recording_control_widget):
        """Set control widgets and create the new layout.
        
        New layout:
        Row 1: Preview 1 | Save Path Widget + Config Setup Widget
        Row 2: Preview 2 | Recording Control Widget
        
        Args:
            save_path_widget: SavePathWidget instance
            recording_control_widget: RecordingControlerWidget instance
        """
        print(f"[DEBUG] set_control_widgets called, _control_widgets_set={self._control_widgets_set}")
        print(f"[DEBUG] Number of cameras: {len(self.cameras_list)}")
        
        if self._control_widgets_set:
            return
        
        print(f"[DEBUG] Creating grid layout...")
        
        # Create new grid layout: 2 rows x 2 columns
        main_grid = QGridLayout()
        # Remove margins and spacing for tight layout
        main_grid.setContentsMargins(0, 0, 0, 0)
        main_grid.setSpacing(0)
        
        if len(self.cameras_list) >= 2:
            print(f"[DEBUG] Setting up dual camera layout...")
            # Row 0: Camera 1 (left) | Control widgets 1 (right)
            room1, cam1 = self.cameras_list[0]
            cam1_widget = QWidget()
            cam1_container = QVBoxLayout()
            cam1_container.setContentsMargins(0, 0, 0, 0)
            cam1_container.setSpacing(0)
            self.room1_label = QLabel("Room 1 - Light Room")
            self.room1_label.setStyleSheet("font-weight: bold; color: blue; font-size: 18px;")
            self.room1_label.setAlignment(Qt.AlignCenter)
            cam1_container.addWidget(self.room1_label)
            cam1_container.addWidget(cam1, 1)
            cam1_widget.setLayout(cam1_container)
            
            # Right column Row 1: Config setup + Room 1 lighting controls
            controls1_widget = QWidget()
            controls1_container = QVBoxLayout()
            controls1_container.setSpacing(2)  # Reduce spacing between widgets
            controls1_container.setContentsMargins(5, 5, 5, 5)
            
            # Add stretch before config setup to center it
            controls1_container.addStretch()
            
            # Add config setup widget
            if self.global_setup:
                controls1_container.addWidget(self.global_setup, 0, Qt.AlignCenter)
            
            # Add stretch to push Room 1 lights to bottom of row
            controls1_container.addStretch()
            
            # Separator before Room 1 lights
            separator1 = QFrame()
            separator1.setFrameShape(QFrame.HLine)
            separator1.setFrameShadow(QFrame.Sunken)
            controls1_container.addWidget(separator1)
            
            # Add Room 1 lighting controls
            try:
                from global_widgets import RightColumnWidget
                # IR Lights 1
                ir1_layout = QHBoxLayout()
                ir1_layout.setSpacing(5)
                ir1_layout.setContentsMargins(5, 2, 5, 2)
                self.ir1_chk = QCheckBox("IR Lights 1")
                self.ir1_chk.setChecked(False)
                ir1_layout.addWidget(self.ir1_chk)
                controls1_container.addLayout(ir1_layout)
                
                # White Lights 1
                white1_layout = QHBoxLayout()
                white1_layout.setSpacing(5)
                white1_layout.setContentsMargins(5, 2, 5, 2)
                self.white1_chk = QCheckBox("White Lights 1")
                self.white1_chk.setChecked(True)
                white1_layout.addWidget(self.white1_chk)
                
                # Percentage label for White Lights 1
                self.white1_pct_label = QLabel("0%")
                self.white1_pct_label.setMinimumWidth(40)
                self.white1_pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                white1_layout.addWidget(self.white1_pct_label)
                
                self.white1_slider = QSlider(Qt.Horizontal)
                self.white1_slider.setRange(0, 1000)
                self.white1_slider.setValue(1000)  # Start at 100% for Room 1
                white1_layout.addWidget(self.white1_slider)
                controls1_container.addLayout(white1_layout)
                
                # Initialize GPIO for Room 1
                try:
                    from global_widgets import GPIO, HardwarePWM, PWM_PIN_ROOM1, IR_PIN_ROOM1, PWM_FREQ
                    GPIO.setwarnings(False)
                    GPIO.setmode(GPIO.BCM)
                    GPIO.setup(IR_PIN_ROOM1, GPIO.OUT)
                    
                    # Pin 12 (Room 1) = PWM chip 0, channel 0
                    self.pwm1 = HardwarePWM(pwm_channel=0, hz=PWM_FREQ, chip=0)
                    self.pwm1.start(0)
                    
                    # Connect signals
                    self.ir1_chk.stateChanged.connect(lambda state: GPIO.output(IR_PIN_ROOM1, GPIO.HIGH if state == Qt.Checked else GPIO.LOW))
                    
                    def white1_toggled(state):
                        enabled = (state == Qt.Checked)
                        if not enabled:
                            self.pwm1.change_duty_cycle(0)
                            self.white1_slider.setEnabled(False)
                        else:
                            self.white1_slider.setEnabled(True)
                            self.pwm1.change_duty_cycle(self.white1_slider.value() / 10.0)
                    
                    def white1_duty_changed(val):
                        duty = val / 10.0
                        self.white1_pct_label.setText(f"{duty:.1f}%")
                        if self.white1_chk.isChecked():
                            print(f"[DEBUG] Room 1 slider changed to {duty:.1f}%, calling change_duty_cycle({duty})")
                            self.pwm1.change_duty_cycle(duty)
                    
                    self.white1_chk.stateChanged.connect(white1_toggled)
                    self.white1_slider.valueChanged.connect(white1_duty_changed)
                    
                    print(f"[GPIO] Room 1 Hardware PWM initialized on pin {PWM_PIN_ROOM1}")
                    
                    # Set initial state: Room 1 White Light ON at 100%
                    white1_toggled(Qt.Checked)
                    self.white1_pct_label.setText("100.0%")
                except Exception as e:
                    print(f"[GPIO] GPIO setup failed for Room 1: {e}")
                
            except Exception as e:
                print(f"[DEBUG] Room 1 lights creation failed: {e}")
            
            # Don't add stretch - let it flow continuously
            controls1_widget.setLayout(controls1_container)
            
            # Row 2: Camera 2 (left) | Room 2 lighting + recording controls (right)
            room2, cam2 = self.cameras_list[1]
            cam2_widget = QWidget()
            cam2_container = QVBoxLayout()
            cam2_container.setContentsMargins(0, 0, 0, 0)
            cam2_container.setSpacing(0)
            cam2_container.addWidget(cam2, 1)
            self.room2_label = QLabel("Room 2 - Dark Room")
            self.room2_label.setStyleSheet("font-weight: bold; color: darkred; font-size: 18px;")
            self.room2_label.setAlignment(Qt.AlignCenter)
            cam2_container.addWidget(self.room2_label)
            cam2_widget.setLayout(cam2_container)
            
            controls2_widget = QWidget()
            controls2_container = QVBoxLayout()
            controls2_container.setSpacing(2)
            controls2_container.setContentsMargins(5, 5, 5, 5)
            
            # Add Room 2 lighting controls
            try:
                # Separator before Room 2 lights
                separator = QFrame()
                separator.setFrameShape(QFrame.HLine)
                separator.setFrameShadow(QFrame.Sunken)
                controls2_container.addWidget(separator)
                
                # IR Lights 2
                ir2_layout = QHBoxLayout()
                ir2_layout.setSpacing(5)
                ir2_layout.setContentsMargins(5, 2, 5, 2)
                self.ir2_chk = QCheckBox("IR Lights 2")
                self.ir2_chk.setChecked(True)  # Start with IR ON for Room 2
                ir2_layout.addWidget(self.ir2_chk)
                controls2_container.addLayout(ir2_layout)
                
                # White Lights 2
                white2_layout = QHBoxLayout()
                white2_layout.setSpacing(5)
                white2_layout.setContentsMargins(5, 2, 5, 2)
                self.white2_chk = QCheckBox("White Lights 2")
                self.white2_chk.setChecked(False)  # Start with White OFF for Room 2
                white2_layout.addWidget(self.white2_chk)
                
                # Percentage label for White Lights 2
                self.white2_pct_label = QLabel("0%")
                self.white2_pct_label.setMinimumWidth(40)
                self.white2_pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                white2_layout.addWidget(self.white2_pct_label)
                
                self.white2_slider = QSlider(Qt.Horizontal)
                self.white2_slider.setRange(0, 1000)
                self.white2_slider.setValue(0)
                self.white2_slider.setEnabled(False)  # Disable slider since White is OFF initially
                white2_layout.addWidget(self.white2_slider)
                controls2_container.addLayout(white2_layout)
                
                # Initialize GPIO for Room 2
                try:
                    from global_widgets import GPIO, HardwarePWM, PWM_PIN_ROOM2, IR_PIN_ROOM2, PWM_FREQ
                    GPIO.setup(IR_PIN_ROOM2, GPIO.OUT)
                    
                    # Pin 18 (Room 2) = PWM chip 0, channel 2
                    self.pwm2 = HardwarePWM(pwm_channel=2, hz=PWM_FREQ, chip=0)
                    self.pwm2.start(0)
                    
                    # Connect signals
                    self.ir2_chk.stateChanged.connect(lambda state: GPIO.output(IR_PIN_ROOM2, GPIO.HIGH if state == Qt.Checked else GPIO.LOW))
                    
                    def white2_toggled(state):
                        enabled = (state == Qt.Checked)
                        if not enabled:
                            self.pwm2.change_duty_cycle(0)
                            self.white2_slider.setEnabled(False)
                        else:
                            self.white2_slider.setEnabled(True)
                            self.pwm2.change_duty_cycle(self.white2_slider.value() / 10.0)
                    
                    def white2_duty_changed(val):
                        duty = val / 10.0
                        self.white2_pct_label.setText(f"{duty:.1f}%")
                        if self.white2_chk.isChecked():
                            print(f"[DEBUG] Room 2 slider changed to {duty:.1f}%, calling change_duty_cycle({duty})")
                            try:
                                self.pwm2.change_duty_cycle(duty)
                                print(f"[DEBUG] Room 2 PWM duty cycle changed successfully")
                            except Exception as e:
                                print(f"[DEBUG] Room 2 PWM change failed: {e}")
                    
                    self.white2_chk.stateChanged.connect(white2_toggled)
                    self.white2_slider.valueChanged.connect(white2_duty_changed)
                    
                    print(f"[GPIO] Room 2 Hardware PWM initialized on pin {PWM_PIN_ROOM2}")
                    
                    # Set initial state: Room 2 IR Light ON
                    GPIO.output(IR_PIN_ROOM2, GPIO.HIGH)
                except Exception as e:
                    print(f"[GPIO] GPIO setup failed for Room 2: {e}")
                
            except Exception as e:
                print(f"[DEBUG] Room 2 lights creation failed: {e}")
            
            # Separator after Room 2 lights
            separator2 = QFrame()
            separator2.setFrameShape(QFrame.HLine)
            separator2.setFrameShadow(QFrame.Sunken)
            controls2_container.addWidget(separator2)
            
            # Add stretch before recording controls to center them
            controls2_container.addStretch()
            
            # Add save path and recording controls below Room 2 lights
            if save_path_widget:
                controls2_container.addWidget(save_path_widget, 0, Qt.AlignCenter)
            controls2_container.addWidget(recording_control_widget, 0, Qt.AlignCenter)
            
            # Add stretch after to balance
            controls2_container.addStretch()
            controls2_widget.setLayout(controls2_container)
            
            # Add to grid: row, col, rowspan, colspan
            main_grid.addWidget(cam1_widget, 0, 0, 1, 1)
            main_grid.addWidget(controls1_widget, 0, 1, 1, 1)
            main_grid.addWidget(cam2_widget, 1, 0, 1, 1)
            main_grid.addWidget(controls2_widget, 1, 1, 1, 1)
            
            # Set column stretch: cameras take more space than controls
            main_grid.setColumnStretch(0, 3)  # Camera column
            main_grid.setColumnStretch(1, 1)  # Controls column
            
            print(f"[DEBUG] Added all widgets to grid")
            
        elif len(self.cameras_list) == 1:
            # Single camera layout
            room, cam = self.cameras_list[0]
            cam_widget = QWidget()
            cam_container = QVBoxLayout()
            cam_container.addWidget(QLabel(f"{room} Camera: port {self.data_manager.camera_settings[room]['disp_num']}"))
            cam_container.addWidget(cam, 1)
            cam_widget.setLayout(cam_container)
            
            controls_widget = QWidget()
            controls_container = QVBoxLayout()
            controls_container.addWidget(save_path_widget)
            if self.global_setup:
                controls_container.addWidget(self.global_setup)
            controls_container.addWidget(recording_control_widget)
            controls_container.addStretch()
            controls_widget.setLayout(controls_container)
            
            main_grid.addWidget(cam_widget, 0, 0, 1, 1)
            main_grid.addWidget(controls_widget, 0, 1, 1, 1)
            main_grid.setColumnStretch(0, 3)
            main_grid.setColumnStretch(1, 1)
        
        print(f"[DEBUG] Setting layout on CameraControlWidget...")
        self.setLayout(main_grid)
        self._control_widgets_set = True
        
        # Start preview after layout is set up
        print(f"[DEBUG] Starting preview...")
        self.start_stop_preview(True)
        print(f"[DEBUG] set_control_widgets complete")

    def resizeEvent(self, event):
        """Handle window resize events."""
        super().resizeEvent(event)
    
    def swap_room_labels(self):
        """Swap only the Light/Dark Room text while keeping Room numbers in place."""
        if hasattr(self, 'room1_label') and hasattr(self, 'room2_label'):
            # Get current styles
            room1_style = self.room1_label.styleSheet()
            room2_style = self.room2_label.styleSheet()
            
            # Determine which room currently has Light/Dark and swap accordingly
            if "Light Room" in self.room1_label.text():
                # Currently: Room 1 = Light, Room 2 = Dark
                # After swap: Room 1 = Dark, Room 2 = Light
                self.room1_label.setText("Room 1 - Dark Room")
                self.room1_label.setStyleSheet("font-weight: bold; color: darkred; font-size: 18px;")
                self.room2_label.setText("Room 2 - Light Room")
                self.room2_label.setStyleSheet("font-weight: bold; color: blue; font-size: 18px;")
            else:
                # Currently: Room 1 = Dark, Room 2 = Light
                # After swap: Room 1 = Light, Room 2 = Dark
                self.room1_label.setText("Room 1 - Light Room")
                self.room1_label.setStyleSheet("font-weight: bold; color: blue; font-size: 18px;")
                self.room2_label.setText("Room 2 - Dark Room")
                self.room2_label.setStyleSheet("font-weight: bold; color: darkred; font-size: 18px;")
    
    def swap_lighting_states(self):
        """Swap the lighting states between Room 1 and Room 2."""
        # Check if both rooms have lighting controls
        has_room1_lights = hasattr(self, 'ir1_chk') and hasattr(self, 'white1_chk') and hasattr(self, 'white1_slider')
        has_room2_lights = hasattr(self, 'ir2_chk') and hasattr(self, 'white2_chk') and hasattr(self, 'white2_slider')
        
        if not has_room1_lights or not has_room2_lights:
            print("[DEBUG] Cannot swap lights - not all lighting controls available")
            return
        
        # Save current states
        room1_ir_state = self.ir1_chk.isChecked()
        room1_white_enabled = self.white1_chk.isChecked()
        room1_white_value = self.white1_slider.value()
        
        room2_ir_state = self.ir2_chk.isChecked()
        room2_white_enabled = self.white2_chk.isChecked()
        room2_white_value = self.white2_slider.value()
        
        print(f"[DEBUG] Swapping lights - Room 1: IR={room1_ir_state}, White={room1_white_enabled}({room1_white_value}%)")
        print(f"[DEBUG] Swapping lights - Room 2: IR={room2_ir_state}, White={room2_white_enabled}({room2_white_value}%)")
        
        # Apply Room 2's state to Room 1
        self.ir1_chk.setChecked(room2_ir_state)
        self.white1_chk.setChecked(room2_white_enabled)
        self.white1_slider.setValue(room2_white_value)
        
        # Apply Room 1's state to Room 2
        self.ir2_chk.setChecked(room1_ir_state)
        self.white2_chk.setChecked(room1_white_enabled)
        self.white2_slider.setValue(room1_white_value)
        
        print("[DEBUG] Lighting states swapped successfully")
    
    def start_stop_recording(self):
        """
        Toggle recording state for all cameras.
        
        If recording, stops all recordings. If not recording, shows session
        dialog and starts recording with optional countdown.
        """
        is_any_running = any(self.data_manager.is_running[room] for room in self.camera_widgets.keys())
        
        if is_any_running:
            self._stop_all_recordings()
        else:
            self._start_all_recordings()
    
    def _start_all_recordings(self):
        """
        Start recording on all cameras with session dialog and countdown.
        
        Gets session name and save path, checks for file overwrites, optionally
        shows countdown window, then starts recording on all cameras.
        """
        session_name, save_path = self._get_session_info()
        
        if not session_name or not save_path:
            return
        
        self.data_manager.set_session_name(session_name)
        self.data_manager.set_save_path(save_path)
        
        # Check for existing files and warn user
        existing_files = []
        camera_num = 1
        for room in self.camera_widgets.keys():
            output_file = self.data_manager.get_session_file_path(f"camera_{camera_num}")
            if Path(output_file).exists():
                existing_files.append(Path(output_file).name)
            camera_num += 1
        
        session_data_file = Path(save_path) / f"{session_name}_data.txt"
        if session_data_file.exists():
            existing_files.append(f"{session_name}_data.txt")
        
        if existing_files:
            file_list = "\n".join(existing_files)
            reply = QMessageBox.question(
                self,
                "Overwrite Files?",
                f"The following file(s) already exist and will be overwritten:\n\n{file_list}\n\nAre you sure you want to continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                return
        
        self.start_stop_preview(False)
        
        # Show countdown if delay is set
        if self.data_manager.recording_delay > 0:
            from global_widgets import CountdownWindow
            countdown_window = CountdownWindow(self.data_manager.recording_delay, parent=self)
            countdown_window.countdown_cancelled.connect(self._on_countdown_cancelled)
            
            result = countdown_window.exec_()
            
            if result == QDialog.Rejected:
                # User cancelled countdown, return to preview
                self.start_stop_preview(True)
                return
        
        # Record the actual start datetime
        from PyQt5.QtCore import QDateTime
        self.data_manager.set_start_datetime(QDateTime.currentDateTime())
        
        # Start recording for each camera
        camera_num = 1
        for room, cam in self.camera_widgets.items():
            # Get the output file path
            output_file = self.data_manager.get_session_file_path(f"camera_{camera_num}")
            
            # Start recording and get config
            result = cam.start_recording(output_file)
            
            if result['success']:
                self.data_manager.set_is_running(room, True)
                self.data_manager.set_start_time(room, QTime.currentTime())
                self.data_manager.set_recording_config(room, result['config'])
                print(f"Started {room} camera recording to {output_file}")
            else:
                print(f"Failed to start {room} camera recording")
                # If any camera fails, stop all and return to preview
                self._stop_all_recordings()
                return
            
            camera_num += 1
        
        # Start light swapping timer if enabled
        if self.data_manager.swap_lights_enabled:
            interval_ms = self.data_manager.swap_interval * 1000  # Convert to milliseconds
            self.swap_timer.start(interval_ms)
            print(f"[SWAP] Light swapping enabled - interval: {self.data_manager.swap_interval}s")
        
        # Show the recording window
        self._show_recording_window()
    
    def _on_countdown_cancelled(self):
        """
        Handle countdown cancellation.
        """
        print("Recording countdown cancelled by user")
    
    def _stop_all_recordings(self):
        """
        Stop recording on all cameras and return to preview.
        """
        print("[DEBUG] _stop_all_recordings called")
        
        # Stop light swapping timer if running
        if self.swap_timer.isActive():
            self.swap_timer.stop()
            print("[SWAP] Light swapping timer stopped")
        
        recorded_files = []
        
        for room, cam in self.camera_widgets.items():
            if self.data_manager.is_running[room]:
                print(f"[DEBUG] Stopping recording for {room}")
                # We need to know the output file name before stopping, usually managed in cam
                # But cam.stop_recording() doesn't return filename. 
                # We can retrieve it from data_manager if we stored it properly or reconstruct it
                # For now, let's look at DataManager logic or assume standard naming
                
                # Check data manager method to get file path
                camera_num = 1 if room == "LightRoom" else 2 # Assuming order
                output_file = self.data_manager.get_session_file_path(f"camera_{camera_num}")
                recorded_files.append(output_file)
                
                cam.stop_recording()
                self.data_manager.set_is_running(room, False)
                print(f"Stopped {room} camera recording")
        
        # Return to preview
        print("[DEBUG] Calling start_stop_preview(True) to restore previews")
        self.start_stop_preview(True)
        
        # Run conversion script on the newly created files
        if recorded_files:
            try:
                import sys
                import subprocess
                from pathlib import Path
                
                print("[CONVERT] Starting conversion of recorded files...")
                # Use the directory where this script is located to find the converter
                script_dir = Path(__file__).parent
                converter_script = script_dir / "convert_h264_to_mp4.py"
                print(f"[CONVERT] Looking for converter at: {converter_script}")
                
                if converter_script.exists():
                    for videofile in recorded_files:
                        if Path(videofile).exists():
                            # Construct output filename (replace .h264 with .mp4)
                            outfile = str(videofile).replace('.h264', '.mp4')
                            print(f"[CONVERT] Converting {videofile} -> {outfile}")
                            
                            # Run conversion in background or blocking? Blocking might freeze UI.
                            # Using Popen to run in background so UI doesn't freeze
                            try:
                                subprocess.Popen([sys.executable, str(converter_script), str(videofile), str(outfile)])
                            except Exception as e:
                                print(f"[CONVERT] Failed to launch converter: {e}")
                else:
                    print(f"[CONVERT] Converter script not found at {converter_script}")
                    
            except Exception as e:
                print(f"[CONVERT] Error during conversion process: {e}")
    
    def _get_session_info(self):
        """
        Show dialog to get session name. Uses the save location already set in data_manager.
        Returns (session_name, save_path) or (None, None) if cancelled.
        """
        # Check if save path is set
        if not self.data_manager.save_path:
            QMessageBox.warning(
                self,
                "No Save Location",
                "Please select a save location using the Browse button before starting recording."
            )
            return None, None
        
        # Get the session name
        session_name, ok = QInputDialog.getText(
            self,
            "Session Name",
            "Enter session name:",
            QLineEdit.Normal,
            ""
        )
        
        if not ok or not session_name:
            return None, None
        
        return session_name, str(self.data_manager.save_path)
    
    def _show_recording_window(self):
        """
        Show the recording window with timer based on the stop method.
        """
        from global_widgets import RecordingWindow
        
        if self.data_manager.stop_method == "Manual":
            # Manual mode - elapsed timer
            self.recording_window = RecordingWindow(mode="Manual", parent=self)
        else:
            # Timer mode - countdown
            self.recording_window = RecordingWindow(
                mode="Timer",
                duration_minutes=self.data_manager.timer_duration,
                parent=self
            )
        
        # Connect stop signal
        self.recording_window.stop_recording_signal.connect(self._on_recording_stopped)
        
        # Show the window (modal)
        self.recording_window.exec_()
    
    def _on_recording_stopped(self):
        """
        Handle recording stop from RecordingWindow.
        Save comprehensive session data to {session_name}_data.txt.
        """
        # Record the end datetime
        from PyQt5.QtCore import QDateTime
        self.data_manager.set_end_datetime(QDateTime.currentDateTime())
        
        # Record end times for each camera
        for room in self.camera_widgets.keys():
            self.data_manager.set_end_time(room, QTime.currentTime())
        
        # Get elapsed time from recording window
        elapsed_seconds = self.recording_window.get_elapsed_time()
        
        # Stop all recordings
        self._stop_all_recordings()
        
        # Save comprehensive session data
        self._save_session_data_file(elapsed_seconds)
    
    def _save_session_data_file(self, elapsed_seconds):
        """
        Save comprehensive recording session data to {session_name}_data.txt in the save directory.
        Includes: session name, dates/times, duration, stop method, camera configurations, file paths, etc.
        """
        if not self.data_manager.save_path or not self.data_manager.session_name:
            return
        
        from pathlib import Path
        session_data_file = Path(self.data_manager.save_path) / f"{self.data_manager.session_name}_data.txt"
        
        try:
            # Convert seconds to hours:minutes:seconds
            hours = elapsed_seconds // 3600
            minutes = (elapsed_seconds % 3600) // 60
            seconds = elapsed_seconds % 60
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            with open(session_data_file, 'w') as f:
                # Header
                f.write("="*60 + "\n")
                f.write("RECORDING SESSION DATA\n")
                f.write("="*60 + "\n\n")
                
                # Session Information
                f.write("SESSION INFORMATION\n")
                f.write("-"*60 + "\n")
                f.write(f"Session Name: {self.data_manager.session_name}\n")
                f.write(f"Save Path: {self.data_manager.save_path}\n\n")
                
                # Timing Information
                f.write("TIMING INFORMATION\n")
                f.write("-"*60 + "\n")
                if self.data_manager.start_datetime:
                    f.write(f"Start Date/Time: {self.data_manager.start_datetime.toString('yyyy-MM-dd hh:mm:ss')}\n")
                if self.data_manager.end_datetime:
                    f.write(f"End Date/Time: {self.data_manager.end_datetime.toString('yyyy-MM-dd hh:mm:ss')}\n")
                f.write(f"Total Duration: {time_str}\n")
                f.write(f"Elapsed Seconds: {elapsed_seconds}\n\n")
                
                # Recording Parameters
                f.write("RECORDING PARAMETERS\n")
                f.write("-"*60 + "\n")
                f.write(f"Stop Method: {self.data_manager.stop_method}\n")
                if self.data_manager.stop_method == "Timer" and self.data_manager.timer_duration:
                    f.write(f"Timer Duration: {self.data_manager.timer_duration} minutes\n")
                f.write(f"Recording Delay (Countdown): {self.data_manager.recording_delay} seconds\n\n")
                
                # Camera Information
                camera_num = 1
                for room in self.camera_widgets.keys():
                    f.write(f"CAMERA {camera_num} ({room})\n")
                    f.write("-"*60 + "\n")
                    
                    # File path
                    output_file = self.data_manager.get_session_file_path(f"camera_{camera_num}")
                    f.write(f"Video File: {Path(output_file).name}\n")
                    
                    # Start/End times
                    if self.data_manager.start_time[room]:
                        f.write(f"Start Time: {self.data_manager.start_time[room].toString('hh:mm:ss')}\n")
                    if self.data_manager.end_time[room]:
                        f.write(f"End Time: {self.data_manager.end_time[room].toString('hh:mm:ss')}\n")
                    
                    # Camera configuration at recording time
                    if self.data_manager.recording_configs[room]:
                        f.write(f"\nCamera Configuration:\n")
                        config = self.data_manager.recording_configs[room]
                        for key, value in config.items():
                            # Format the value nicely
                            if isinstance(value, tuple):
                                value_str = f"{value[0]} x {value[1]}" if len(value) == 2 else str(value)
                            else:
                                value_str = str(value)
                            f.write(f"  {key}: {value_str}\n")
                    
                    # Camera settings from data manager
                    if room in self.data_manager.camera_settings:
                        settings = self.data_manager.camera_settings[room]
                        if any(settings.values()):
                            f.write(f"\nCamera Settings:\n")
                            if settings.get('disp_num') is not None:
                                f.write(f"  Display Number: {settings['disp_num']}\n")
                            if settings.get('status') is not None:
                                f.write(f"  Status: {settings['status']}\n")
                            if settings.get('focus') is not None:
                                f.write(f"  Focus: {settings['focus']}\n")
                            if settings.get('frame_rate') is not None:
                                f.write(f"  Frame Rate: {settings['frame_rate']}\n")
                            if settings.get('exposure') is not None:
                                f.write(f"  Exposure: {settings['exposure']}\n")
                            if settings.get('zoom') is not None:
                                f.write(f"  Zoom: {settings['zoom']}\n")
                    
                    f.write("\n")
                    camera_num += 1
                
                # Footer
                f.write("="*60 + "\n")
                f.write("End of session data\n")
                f.write("="*60 + "\n")
            
            print(f"Saved comprehensive session data to {session_data_file}")
        except Exception as e:
            print(f"Error saving session data file: {e}")
            import traceback
            traceback.print_exc()

    def start_stop_preview(self, start_preview):
        """
        Start or stop the camera preview.
        :param start_preview: Boolean indicating whether to start or stop the preview
        """
        if start_preview:
            print(f"[DEBUG] start_stop_preview(True) called - restarting previews")
            for room, cam in self.camera_widgets.items():
                print(f"[DEBUG] Processing camera {cam.CamDisp_num} for {room}")
                # Check if camera is stopped (e.g., after recording) and needs reinitialization
                needs_init = False
                try:
                    has_started = hasattr(cam.picam, 'started') and cam.picam.started
                    has_widget = hasattr(cam, 'picam_preview_widget') and cam.picam_preview_widget is not None
                    print(f"[DEBUG] Camera {cam.CamDisp_num}: has_started={has_started}, has_widget={has_widget}")
                    
                    if not hasattr(cam.picam, 'started') or not cam.picam.started:
                        # Camera is stopped, need to reinitialize
                        needs_init = True
                        print(f"[DEBUG] Camera {cam.CamDisp_num}: needs_init=True (camera stopped)")
                    elif not hasattr(cam, 'picam_preview_widget') or cam.picam_preview_widget is None:
                        # No preview widget exists
                        needs_init = True
                        print(f"[DEBUG] Camera {cam.CamDisp_num}: needs_init=True (no widget)")
                    else:
                        # Widget exists and camera is started, check if widget is hidden
                        if cam.picam_preview_widget.isHidden():
                            needs_init = True
                            print(f"[DEBUG] Camera {cam.CamDisp_num}: needs_init=True (widget hidden)")
                except Exception as e:
                    needs_init = True
                    print(f"[DEBUG] Camera {cam.CamDisp_num}: needs_init=True (exception: {e})")
                
                if needs_init:
                    print(f"[DEBUG] Camera {cam.CamDisp_num}: Calling initialize_preview()")
                    cam.initialize_preview()
                
                try:
                    if not cam.picam.started:
                        print(f"[DEBUG] Camera {cam.CamDisp_num}: Starting camera")
                        cam.picam.start()
                    else:
                        print(f"[DEBUG] Camera {cam.CamDisp_num}: Camera already started")
                except Exception as e:
                    print(f"[DEBUG] Camera {cam.CamDisp_num}: Error starting camera: {e}")
                    dprint(f"[camera] start_stop_preview: Error starting camera {cam.CamDisp_num}: {e}")
                
                # prefer the GL preview widget, otherwise the software preview label
                has_gl = hasattr(cam, 'picam_preview_widget') and cam.picam_preview_widget is not None
                has_sw = hasattr(cam, 'software_preview_label') and cam.software_preview_label is not None
                print(f"[DEBUG] Camera {cam.CamDisp_num}: has_gl_widget={has_gl}, has_sw_widget={has_sw}")
                
                if hasattr(cam, 'picam_preview_widget') and cam.picam_preview_widget is not None:
                    try:
                        # Only add if not already in layout
                        if cam.picam_preview_widget.parent() != cam:
                            print(f"[DEBUG] Camera {cam.CamDisp_num}: Adding GL preview widget to layout")
                            cam.cam_layout.addWidget(cam.picam_preview_widget)
                        print(f"[DEBUG] Camera {cam.CamDisp_num}: Showing GL preview widget")
                        cam.picam_preview_widget.show()
                    except Exception as e:
                        print(f"[DEBUG] Camera {cam.CamDisp_num}: Error showing GL preview: {e}")
                        dprint(f"[camera] start_stop_preview: Error showing preview widget: {e}")
                elif hasattr(cam, 'software_preview_label') and cam.software_preview_label is not None:
                    print(f"[DEBUG] Camera {cam.CamDisp_num}: Using software preview")
                    cam.cam_layout.addWidget(cam.software_preview_label)
                    cam.software_preview_label.show()
                else:
                    print(f"[DEBUG] Camera {cam.CamDisp_num}: No preview widget, showing 'preview off' widget")
                    cam.cam_layout.addWidget(cam.preview_off_widget)
                    cam.preview_off_widget.show()
        else:
            for room, cam in self.camera_widgets.items():
                try:
                    cam.picam.stop()
                except Exception:
                    pass
                # Hide preview widgets but don't delete them (reuse for faster restart)
                if hasattr(cam, 'picam_preview_widget') and cam.picam_preview_widget is not None:
                    try:
                        cam.picam_preview_widget.hide()
                    except Exception:
                        pass
                # stop software preview if present
                if hasattr(cam, 'software_preview_timer') and cam.software_preview_timer is not None:
                    try:
                        cam.software_preview_timer.stop()
                    except Exception:
                        pass
                if hasattr(cam, 'software_preview_label') and cam.software_preview_label is not None:
                    try:
                        cam.software_preview_label.hide()
                    except Exception:
                        pass
                # Show the black "preview off" widget
                try:
                    if cam.preview_off_widget.parent() != cam:
                        cam.cam_layout.addWidget(cam.preview_off_widget)
                    cam.preview_off_widget.show()
                except Exception:
                    pass

    def cleanup_gpio(self):
        """Clean up GPIO pins - turn off all lights and stop PWM."""
        try:
            from global_widgets import GPIO
            print("[GPIO] Cleaning up GPIO pins...")
            
            # Turn off Hardware PWM and IR lights for Room 1
            if hasattr(self, 'pwm1'):
                try:
                    self.pwm1.change_duty_cycle(0)
                    self.pwm1.stop()
                    print("[GPIO] Room 1 Hardware PWM stopped")
                except Exception as e:
                    print(f"[GPIO] Error stopping Room 1 PWM: {e}")
            
            if hasattr(self, 'ir1_chk'):
                try:
                    from global_widgets import IR_PIN_ROOM1
                    GPIO.setmode(GPIO.BCM)
                    GPIO.output(IR_PIN_ROOM1, GPIO.LOW)
                    print("[GPIO] Room 1 IR lights turned off")
                except:
                    pass  # Already cleaned up or not set up
            
            # Turn off Hardware PWM and IR lights for Room 2
            if hasattr(self, 'pwm2'):
                try:
                    self.pwm2.change_duty_cycle(0)
                    self.pwm2.stop()
                    print("[GPIO] Room 2 Hardware PWM stopped")
                except Exception as e:
                    print(f"[GPIO] Error stopping Room 2 PWM: {e}")
            
            if hasattr(self, 'ir2_chk'):
                try:
                    from global_widgets import IR_PIN_ROOM2
                    GPIO.setmode(GPIO.BCM)
                    GPIO.output(IR_PIN_ROOM2, GPIO.LOW)
                    print("[GPIO] Room 2 IR lights turned off")
                except:
                    pass  # Already cleaned up or not set up
            
            # Clean up GPIO
            try:
                GPIO.cleanup()
                print("[GPIO] GPIO cleanup completed")
            except Exception as e:
                print(f"[GPIO] Error during GPIO.cleanup(): {e}")
                
        except Exception as e:
            print(f"[GPIO] Error during GPIO cleanup: {e}")
    
    def closeEvent(self, event):
        print("Closing CameraControlWidget...")
        # Clean up GPIO before closing
        self.cleanup_gpio()
        
        for room, cam in self.camera_widgets.items():
            cam.close()
        event.accept() 

    
    
