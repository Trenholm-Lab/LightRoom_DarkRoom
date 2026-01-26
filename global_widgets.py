"""
Global UI widgets for LightRoom DarkRoom application.

Provides reusable widget components for recording control, countdown timers,
camera setup dialogs, and save path selection. These widgets are shared
across the application interface.
"""

from PyQt5.QtCore import Qt, QTime, QTimer, QElapsedTimer, pyqtSignal
from PyQt5.QtWidgets import *
import sys

"""
GPIO handling: Use hardware PWM via rpi-hardware-pwm for PWM pins (12, 18)
and RPi.GPIO for digital IO. Falls back to mock for non-RPi systems.
"""
_HAVE_HW_PWM = False
_HAVE_RPI_GPIO = False

# Try to import hardware PWM
try:
    from rpi_hardware_pwm import HardwarePWM
    _HAVE_HW_PWM = True
    print("[GPIO] rpi-hardware-pwm imported successfully - using hardware PWM")
except Exception as e:
    print(f"[GPIO] rpi-hardware-pwm not available: {e}")
    _HAVE_HW_PWM = False

# Try to import RPi.GPIO for digital IO
try:
    import RPi.GPIO as GPIO
    _HAVE_RPI_GPIO = True
    print("[GPIO] RPi.GPIO imported successfully - using for digital IO")
except Exception as e:
    print(f"[GPIO] RPi.GPIO not available: {e}")
    _HAVE_RPI_GPIO = False

# Create mock classes if needed
if not _HAVE_RPI_GPIO:
    print("[GPIO] Falling back to MOCK GPIO")
    
    class _MockGPIO:
        BCM = 'BCM'
        OUT = 'OUT'
        HIGH = 1
        LOW = 0

        def __init__(self):
            self._pin_state = {}

        def setwarnings(self, flag):
            pass

        def setmode(self, mode):
            print(f"[MockGPIO] setmode({mode})")

        def setup(self, pin, mode):
            self._pin_state[pin] = self.LOW
            print(f"[MockGPIO] setup pin {pin} as {mode}")

        def output(self, pin, value):
            self._pin_state[pin] = value
            print(f"[MockGPIO] output pin {pin} -> {value}")

        def cleanup(self):
            print("[MockGPIO] cleanup")

    GPIO = _MockGPIO()

if not _HAVE_HW_PWM:
    print("[GPIO] Falling back to MOCK Hardware PWM")
    
    class HardwarePWM:
        def __init__(self, pwm_channel, hz, chip=0):
            self.pwm_channel = pwm_channel
            self.hz = hz
            self.chip = chip
            self._duty = 0
            print(f"[MockPWM] Created HardwarePWM(channel={pwm_channel}, freq={hz}Hz, chip={chip})")

        def start(self, duty_cycle):
            self._duty = duty_cycle
            print(f"[MockPWM] start duty={duty_cycle}%")

        def change_duty_cycle(self, duty_cycle):
            self._duty = duty_cycle
            print(f"[MockPWM] duty -> {duty_cycle}%")

        def change_frequency(self, hz):
            self.hz = hz
            print(f"[MockPWM] freq -> {hz}Hz")

        def stop(self):
            print(f"[MockPWM] stopped")
from data_manager import *
from picamera2 import Picamera2
from pathlib import Path

# Define GPIO pins used for lighting
PWM_PIN_ROOM1 = 12
IR_PIN_ROOM1 = 23
PWM_PIN_ROOM2 = 18
IR_PIN_ROOM2 = 24
PWM_FREQ = 5000


class SavePathWidget(QWidget):
    """
    Widget for selecting and displaying video save directory.
    
    Provides a file dialog to browse for save location and displays
    the selected path in a read-only text field.
    """
    
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.dialog = QFileDialog()
        
        self.dialog.setFileMode(QFileDialog.Directory)
        self.dialog.setOption(QFileDialog.ShowDirsOnly, True)

        self.directory_edit = QLineEdit()
        self.directory_edit.setEnabled(False)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.open_file_dialog)
        
        layout = QHBoxLayout()
        save_path_label = QLabel("Save Path:")

        layout.addWidget(save_path_label)
        layout.addWidget(self.directory_edit)
        layout.addWidget(self.browse_btn)

        self.setLayout(layout)

    def open_file_dialog(self):
        """Open directory selection dialog and update save path."""
        directory = self.dialog.getExistingDirectory(self, "Select Save Directory")
        if directory:
            self.path = Path(directory)
            self.directory_edit.setText(str(self.path))
            self.data_manager.set_save_path(self.path)


class RecordingControlerWidget(QWidget):
    """
    Widget for controlling video recording start/stop and parameters.
    
    Provides controls for:
    - Save location browser and display
    - Recording stop method (Manual or Timer)
    - Timer duration (when using Timer mode)
    - Recording delay countdown
    - Start/Stop recording button
    """
    
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.start_time = None
        
        self.stop_method_combo = QComboBox()
        self.stop_method_combo.addItems(["Manual", "Timer"])
        self.stop_method_combo.setCurrentText(self.data_manager.stop_method)
        self.stop_method_combo.currentTextChanged.connect(self.update_stop_method)
        stop_method_label = QLabel("Recording stop method:")
        stop_method_layout = QHBoxLayout()
        stop_method_layout.addWidget(stop_method_label)
        stop_method_layout.addWidget(self.stop_method_combo)

        self.start_time_label = QLabel(f"Recording start time: ")
        self.data_manager.start_time_updated.connect(lambda Qstart_time_dict: self.update_start_label(Qstart_time_dict)) 

        self.start_stop_btn = QPushButton("Start Recording")
        self.start_stop_btn.setObjectName("start_stop_btn")
        self.start_stop_btn.setStyleSheet("#start_stop_btn {background-color: #90EE90; color: black; padding: 5px;}")
        self.start_stop_btn.clicked.connect(self.start_stop_toggled)

        self.timer_widget = QDoubleSpinBox(parent=self)
        self.timer_widget.setRange(1.0, 60.0)
        self.timer_widget.setValue(5.0)
        self.timer_widget.setSingleStep(5.0)
        self.timer_widget.setDecimals(1)
        self.timer_widget.valueChanged.connect(lambda value: self.data_manager.set_timer_duration(value))
        self.timer_label = QLabel("Set recording time (min):", parent=self)
        self.timer_layout = QHBoxLayout()
        self.timer_layout.addWidget(self.timer_label)
        self.timer_layout.addWidget(self.timer_widget)
        self.timer_label.hide()
        self.timer_widget.hide()

        self.delay_widget = QSpinBox(parent=self)
        self.delay_widget.setRange(0, 120)
        self.delay_widget.setValue(0)
        self.delay_widget.setSingleStep(5)
        self.delay_widget.setSuffix(" sec")
        self.delay_widget.valueChanged.connect(lambda value: self.data_manager.set_recording_delay(value))
        self.delay_label = QLabel("Recording delay:", parent=self)
        self.delay_layout = QHBoxLayout()
        self.delay_layout.addWidget(self.delay_label)
        self.delay_layout.addWidget(self.delay_widget)

        # Light swapping controls
        self.swap_lights_chk = QCheckBox("Swapping Lights During Recording", parent=self)
        self.swap_lights_chk.setChecked(False)
        self.swap_lights_chk.stateChanged.connect(self.toggle_swap_lights)
        
        self.swap_interval_widget = QSpinBox(parent=self)
        self.swap_interval_widget.setRange(5, 600)
        self.swap_interval_widget.setValue(30)
        self.swap_interval_widget.setSingleStep(5)
        self.swap_interval_widget.setSuffix(" sec")
        self.swap_interval_widget.valueChanged.connect(lambda value: self.data_manager.set_swap_interval(value))
        self.swap_interval_label = QLabel("Swap interval:", parent=self)
        self.swap_interval_layout = QHBoxLayout()
        self.swap_interval_layout.addWidget(self.swap_interval_label)
        self.swap_interval_layout.addWidget(self.swap_interval_widget)
        self.swap_interval_label.hide()
        self.swap_interval_widget.hide()

        layout = QGridLayout()
        layout.addLayout(stop_method_layout, 0, 0, 1, 2)
        layout.addLayout(self.timer_layout, 1, 0, 1, 1)
        layout.addWidget(self.start_time_label, 1, 1, 1, 1)
        layout.addLayout(self.delay_layout, 2, 0, 1, 2)
        layout.addWidget(self.swap_lights_chk, 3, 0, 1, 2)
        layout.addLayout(self.swap_interval_layout, 4, 0, 1, 2)
        layout.addWidget(self.start_stop_btn, 5, 0, 1, 2)

        self.setLayout(layout)

    def update_start_label(self, Qtime_dict):
        """Update the start time display label for each camera."""
        text = "Recording start time: "
        for room, qtime in Qtime_dict.items():
            if qtime != None:
                text += f"{room}: {qtime.toString('HH:mm:ss')} "
        self.start_time_label.setText(text)

    def start_stop_toggled(self):
        """Emit signal to trigger recording start."""
        self.data_manager.start_stop_toggled_signal.emit()  

    def update_stop_method(self, method):
        """Show/hide timer controls based on selected stop method."""
        if method == "Manual":
            self.timer_widget.hide()
            self.timer_label.hide()
            self.data_manager.set_timer_duration(None)
        else:
            self.timer_widget.show()
            self.timer_label.show()
            self.data_manager.set_timer_duration(self.timer_widget.value())

        self.data_manager.set_stop_method(method)
    
    def toggle_swap_lights(self, state):
        """Show/hide swap interval controls based on checkbox state."""
        enabled = (state == Qt.Checked)
        self.data_manager.set_swap_lights_enabled(enabled)
        
        if enabled:
            self.swap_interval_widget.show()
            self.swap_interval_label.show()
            self.data_manager.set_swap_interval(self.swap_interval_widget.value())
        else:
            self.swap_interval_widget.hide()
            self.swap_interval_label.hide()


class RightColumnWidget(QWidget):
    """Right column container widget.

    Composes the existing ConfigSetupWidget (load/modify/swap) together with
    lighting controls for Room 1 and Room 2, and the recording/save widgets.
    Handles GPIO (or mock) setup for the requested pins and cleans up on exit.
    """

    def __init__(self, data_manager, config_setup_widget, save_path_widget, recording_widget, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.config_setup_widget = config_setup_widget
        self.save_path_widget = save_path_widget
        self.recording_widget = recording_widget

        # Initialize GPIO pins
        try:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
        except Exception:
            pass

        # Setup digital pins (IR lights)
        try:
            GPIO.setup(IR_PIN_ROOM1, GPIO.OUT)
            GPIO.setup(IR_PIN_ROOM2, GPIO.OUT)
            print(f"[GPIO] Digital pins initialized for IR lights")
        except Exception as e:
            print(f"[GPIO] Error setting up digital pins: {e}")

        # Create Hardware PWM objects
        # Pin 12 (Room 1) = PWM chip 0, channel 0
        # Pin 18 (Room 2) = PWM chip 0, channel 2
        try:
            self.pwm1 = HardwarePWM(pwm_channel=0, hz=PWM_FREQ, chip=0)
            self.pwm1.start(0)
            print(f"[GPIO] Room 1 Hardware PWM initialized on pin {PWM_PIN_ROOM1} (chip0/ch0) at {PWM_FREQ}Hz")
        except Exception as e:
            print(f"[GPIO] Error setting up Room 1 Hardware PWM: {e}")
            self.pwm1 = None

        try:
            self.pwm2 = HardwarePWM(pwm_channel=2, hz=PWM_FREQ, chip=0)
            self.pwm2.start(0)
            print(f"[GPIO] Room 2 Hardware PWM initialized on pin {PWM_PIN_ROOM2} (chip0/ch2) at {PWM_FREQ}Hz")
        except Exception as e:
            print(f"[GPIO] GPIO setup failed for Room 2: {e}")
            self.pwm2 = None

        # Layout
        layout = QVBoxLayout()

        # Insert the existing ConfigSetupWidget at the top
        if self.config_setup_widget:
            # Prevent the config widget from expanding to consume the whole column
            try:
                self.config_setup_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self.config_setup_widget.setMaximumHeight(int(self.data_manager.main_window_size['H'] * 0.12))
            except Exception:
                pass
            layout.addWidget(self.config_setup_widget)

        # Room 1 lighting group
        room1_grp = QGroupBox("Room 1 Lights")
        r1_layout = QGridLayout()

        self.ir1_chk = QCheckBox("IR Lights 1")
        self.ir1_chk.setChecked(False)
        self.ir1_chk.stateChanged.connect(self._ir1_toggled)
        r1_layout.addWidget(self.ir1_chk, 0, 0)

        self.white1_chk = QCheckBox("White Lights 1 (enable PWM)")
        self.white1_chk.setChecked(True)
        self.white1_chk.stateChanged.connect(self._white1_toggled)
        r1_layout.addWidget(self.white1_chk, 1, 0)

        self.white1_slider = QSlider(Qt.Horizontal)
        self.white1_slider.setRange(0, 100)
        self.white1_slider.setValue(100)  # Start at 100% for Room 1
        self.white1_slider.valueChanged.connect(self._white1_duty_changed)
        r1_layout.addWidget(self.white1_slider, 1, 1)

        room1_grp.setLayout(r1_layout)
        try:
            room1_grp.setMinimumHeight(80)
        except Exception:
            pass
        layout.addWidget(room1_grp)

        # Room 2 lighting group
        room2_grp = QGroupBox("Room 2 Lights")
        r2_layout = QGridLayout()

        self.ir2_chk = QCheckBox("IR Lights 2")
        self.ir2_chk.setChecked(True)  # Start with IR ON for Room 2
        self.ir2_chk.stateChanged.connect(self._ir2_toggled)
        r2_layout.addWidget(self.ir2_chk, 0, 0)

        self.white2_chk = QCheckBox("White Lights 2 (enable PWM)")
        self.white2_chk.setChecked(False)  # Start with White OFF for Room 2
        self.white2_chk.stateChanged.connect(self._white2_toggled)
        r2_layout.addWidget(self.white2_chk, 1, 0)

        self.white2_slider = QSlider(Qt.Horizontal)
        self.white2_slider.setRange(0, 100)
        self.white2_slider.setValue(0)
        self.white2_slider.setEnabled(False)  # Disable slider since White is OFF initially
        self.white2_slider.valueChanged.connect(self._white2_duty_changed)
        r2_layout.addWidget(self.white2_slider, 1, 1)

        room2_grp.setLayout(r2_layout)
        try:
            room2_grp.setMinimumHeight(80)
        except Exception:
            pass
        layout.addWidget(room2_grp)

        # Save path widget and recording controls
        if self.save_path_widget:
            layout.addWidget(self.save_path_widget)

        if self.recording_widget:
            layout.addWidget(self.recording_widget)

        layout.addStretch()
        self.setLayout(layout)

        # Connect to app quit to ensure cleanup
        try:
            app = QApplication.instance()
            if app:
                app.aboutToQuit.connect(self._cleanup_gpio)
        except Exception as e:
            print(f"[GPIO] Error connecting cleanup: {e}")

        # Set initial lighting states
        # Room 1: White Light ON at 100%
        self._white1_toggled(Qt.Checked)
        # Room 2: IR Light ON
        self._ir2_toggled(Qt.Checked)

    # GPIO control callbacks
    def _ir1_toggled(self, state):
        try:
            value = GPIO.HIGH if state == Qt.Checked else GPIO.LOW
            GPIO.output(IR_PIN_ROOM1, value)
        except Exception as e:
            print(f"[GPIO] Error toggling Room 1 IR: {e}")

    def _white1_toggled(self, state):
        enabled = (state == Qt.Checked)
        try:
            if not enabled and self.pwm1:
                self.pwm1.change_duty_cycle(0)
                self.white1_slider.setEnabled(False)
            else:
                self.white1_slider.setEnabled(True)
                if self.pwm1:
                    duty = self.white1_slider.value()
                    self.pwm1.change_duty_cycle(duty)
        except Exception as e:
            print(f"[GPIO] Error toggling Room 1 White: {e}")

    def _white1_duty_changed(self, val):
        try:
            if self.white1_chk.isChecked() and self.pwm1:
                self.pwm1.change_duty_cycle(val)
        except Exception:
            pass

    def _ir2_toggled(self, state):
        try:
            value = GPIO.HIGH if state == Qt.Checked else GPIO.LOW
            GPIO.output(IR_PIN_ROOM2, value)
        except Exception as e:
            print(f"[GPIO] Error toggling Room 2 IR: {e}")

    def _white2_toggled(self, state):
        enabled = (state == Qt.Checked)
        try:
            if not enabled and self.pwm2:
                self.pwm2.change_duty_cycle(0)
                self.white2_slider.setEnabled(False)
            else:
                self.white2_slider.setEnabled(True)
                if self.pwm2:
                    duty = self.white2_slider.value()
                    self.pwm2.change_duty_cycle(duty)
        except Exception as e:
            print(f"[GPIO] Error toggling Room 2 White: {e}")

    def _white2_duty_changed(self, val):
        try:
            if self.white2_chk.isChecked() and self.pwm2:
                self.pwm2.change_duty_cycle(val)
        except Exception:
            pass

    def _cleanup_gpio(self):
        """Clean up GPIO pins - turn off all lights and stop PWM."""
        try:
            print("[GPIO] Cleaning up GPIO pins...")
            # Stop hardware PWM
            if hasattr(self, 'pwm1') and self.pwm1:
                try:
                    self.pwm1.change_duty_cycle(0)
                    self.pwm1.stop()
                    print("[GPIO] Room 1 Hardware PWM stopped")
                except Exception as e:
                    print(f"[GPIO] Error stopping Room 1 PWM: {e}")
            if hasattr(self, 'pwm2') and self.pwm2:
                try:
                    self.pwm2.change_duty_cycle(0)
                    self.pwm2.stop()
                    print("[GPIO] Room 2 Hardware PWM stopped")
                except Exception as e:
                    print(f"[GPIO] Error stopping Room 2 PWM: {e}")
            # Turn off IR lights manually before cleanup
            try:
                GPIO.setmode(GPIO.BCM)
                try:
                    GPIO.output(IR_PIN_ROOM1, GPIO.LOW)
                    print("[GPIO] Room 1 IR lights turned off")
                except:
                    pass  # Already cleaned up
                try:
                    GPIO.output(IR_PIN_ROOM2, GPIO.LOW)
                    print("[GPIO] Room 2 IR lights turned off")
                except:
                    pass  # Already cleaned up
            except Exception as e:
                print(f"[GPIO] Error turning off IR lights: {e}")
            # Clean up digital GPIO
            try:
                GPIO.cleanup()
                print("[GPIO] GPIO cleanup completed")
            except Exception as e:
                print(f"[GPIO] Error during GPIO cleanup: {e}")
        except Exception as e:
            print(f"[GPIO] Error during GPIO cleanup: {e}")

    def closeEvent(self, event):
        self._cleanup_gpio()
        event.accept()


class CountdownWindow(QDialog):
    """
    Modal dialog showing countdown before recording starts.
    
    Displays large countdown timer and allows user to cancel.
    Automatically closes when countdown reaches zero.
    
    Signals:
        countdown_finished: Emitted when countdown completes
        countdown_cancelled: Emitted when user cancels countdown
    """
    countdown_finished = pyqtSignal()
    countdown_cancelled = pyqtSignal()
    
    def __init__(self, delay_seconds, parent=None):
        super().__init__(parent)
        self.delay_seconds = delay_seconds
        self.remaining_seconds = delay_seconds
        
        self.setWindowTitle("Recording Starts In...")
        self.setModal(True)
        self.resize(400, 250)
        
        layout = QVBoxLayout()
        
        info_label = QLabel("Recording will start in:")
        info_label.setAlignment(Qt.AlignCenter)
        info_font = info_label.font()
        info_font.setPointSize(14)
        info_label.setFont(info_font)
        layout.addWidget(info_label)
        
        self.countdown_label = QLabel()
        self.countdown_label.setAlignment(Qt.AlignCenter)
        font = self.countdown_label.font()
        font.setPointSize(72)
        font.setBold(True)
        self.countdown_label.setFont(font)
        self.countdown_label.setStyleSheet("color: orange;")
        self._update_display()
        layout.addWidget(self.countdown_label)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet("background-color: #FFB6C1; color: black; font-size: 14px; padding: 10px;")
        self.cancel_btn.clicked.connect(self.cancel_countdown)
        layout.addWidget(self.cancel_btn)
        
        self.setLayout(layout)
        
        self.countdown_timer = QTimer()
        self.countdown_timer.timeout.connect(self.update_countdown)
        self.countdown_timer.start(1000)
        
    def _update_display(self):
        """Update countdown display with color based on time remaining."""
        self.countdown_label.setText(f"{self.remaining_seconds}")
        
        if self.remaining_seconds <= 3:
            self.countdown_label.setStyleSheet("color: red;")
        elif self.remaining_seconds <= 5:
            self.countdown_label.setStyleSheet("color: orange;")
        else:
            self.countdown_label.setStyleSheet("color: green;")
    
    def update_countdown(self):
        """Decrement countdown and check if finished."""
        self.remaining_seconds -= 1
        
        if self.remaining_seconds <= 0:
            self.countdown_timer.stop()
            self.countdown_finished.emit()
            self.accept()
        else:
            self._update_display()
    
    def cancel_countdown(self):
        """Handle countdown cancellation."""
        self.countdown_timer.stop()
        self.countdown_cancelled.emit()
        self.reject()
    
    def closeEvent(self, event):
        """Clean up timer on window close."""
        self.countdown_timer.stop()
        self.countdown_cancelled.emit()
        event.accept()


class OnsetCameraSetupDialog(QDialog):
    """
    Initial camera setup dialog shown on application startup.
    
    Allows user to select which cameras to use and specify their
    port indices. Validates that selected cameras are available.
    """
    
    def __init__(self, parent, data_manager):
        super().__init__(parent)
        self.data_manager = data_manager
        self.default_LR_index = 0
        self.default_DR_index = 1
        self.setWindowTitle("Camera Setup")

        self.LR_label = QLabel("LightRoom camera port index:")
        self.LR_edit = QLineEdit()
        self.LR_edit.setText(str(self.default_LR_index))
        self.LR_check = QCheckBox("Use LightRoom cam")
        self.LR_check.setChecked(True)
        self.LR_check.stateChanged.connect(lambda state: self.toggle_room_cam("LightRoom", state))  

        self.DR_label = QLabel("DarkRoom camera port index:")
        self.DR_edit = QLineEdit()
        self.DR_edit.setText(str(self.default_DR_index))
        self.DR_check = QCheckBox("Use DarkRoom cam")
        self.DR_check.setChecked(True) 
        self.DR_check.stateChanged.connect(lambda state: self.toggle_room_cam("DarkRoom", state))

        self.set_button = QPushButton("Set")
        self.set_button.clicked.connect(self.set_data)

        layout = QGridLayout()
        layout.addWidget(self.LR_check, 0, 0)
        layout.addWidget(self.LR_label, 0, 1)
        layout.addWidget(self.LR_edit, 0, 2)
        layout.addWidget(self.DR_label, 1, 1)
        layout.addWidget(self.DR_edit, 1, 2)
        layout.addWidget(self.DR_check, 1, 0)
        layout.addWidget(self.set_button, 2, 0, 1, 3)

        self.setLayout(layout)

    def toggle_room_cam(self, room, state):
        """Enable/disable camera input field based on checkbox state."""
        if room == "LightRoom":
            input_data = self.LR_edit
            default = self.default_LR_index
        elif room == "DarkRoom":
            input_data = self.DR_edit
            default = self.default_DR_index

        if state == Qt.Checked:
            input_data.setEnabled(True)
            input_data.setText(str(default))
        else:
            input_data.setText("")
            input_data.setEnabled(False)

    def set_data(self):
        """Validate camera selections and update data manager."""
        valid_inputs = {"LightRoom": False, "DarkRoom": False} 
        visible_cam_indices = [cam['Num'] for cam in Picamera2.global_camera_info()]
        
        if [self.LR_edit.text(), self.DR_edit.text()] == ["", ""]:
            QMessageBox.warning(self, "At least one camera must be selected", "Please select at least one camera to proceed.")
        
        else:
            for room, input_cam_i in zip(["LightRoom", "DarkRoom"], [self.LR_edit.text(), self.DR_edit.text()]):
                if input_cam_i != "":
                    if int(input_cam_i) in visible_cam_indices:
                        self.data_manager.camera_settings[room]['disp_num'] = int(input_cam_i)
                        self.data_manager.is_running[room] = False
                        valid_inputs[room] = True
                    else:
                        QMessageBox.warning(self, "Camera Setup", f"No valid PiCam found at index {input_cam_i} for {room} camera.")
                        valid_inputs[room] = False
                else:
                    valid_inputs[room] = None
        
        if False not in valid_inputs.values():
            self.accept()


class RecordingWindow(QDialog):
    """
    Modal dialog displayed during active recording.
    
    Shows recording timer (elapsed or countdown) and stop button.
    Supports two modes:
    - Manual: Counts up from 00:00:00
    - Timer: Counts down from specified duration
    
    Signals:
        stop_recording_signal: Emitted when recording should stop
    """
    stop_recording_signal = pyqtSignal()
    
    def __init__(self, mode="Manual", duration_minutes=None, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.duration_minutes = duration_minutes
        self.elapsed_timer = QElapsedTimer()
        self.elapsed_timer.start()
        
        self.setWindowTitle("Recording in Progress")
        self.setModal(True)
        self.resize(400, 200)
        
        layout = QVBoxLayout()
        
        self.timer_label = QLabel()
        self.timer_label.setAlignment(Qt.AlignCenter)
        font = self.timer_label.font()
        font.setPointSize(48)
        font.setBold(True)
        self.timer_label.setFont(font)
        
        if self.mode == "Manual":
            self.timer_label.setText("00:00:00")
            self.timer_label.setStyleSheet("color: green;")
        else:
            total_seconds = int(self.duration_minutes * 60)
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            self.timer_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
            self.timer_label.setStyleSheet("color: orange;")
        
        layout.addWidget(self.timer_label)
        
        if self.mode == "Manual":
            status_text = "Recording - Elapsed Time"
        else:
            status_text = f"Recording - Time Remaining"
        
        self.status_label = QLabel(status_text)
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        self.stop_btn = QPushButton("Stop Recording")
        self.stop_btn.setStyleSheet("#stop_btn {background-color: #FFB6C1; color: black; font-size: 16px; padding: 10px;}")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.clicked.connect(self.stop_recording)
        layout.addWidget(self.stop_btn)
        
        self.setLayout(layout)
        
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(100) # Update more frequently for smoother UI
        
    def update_display(self):
        """Update timer display."""
        elapsed_ms = self.elapsed_timer.elapsed()
        current_elapsed_seconds = elapsed_ms // 1000
        
        if self.mode == "Manual":
            hours = current_elapsed_seconds // 3600
            minutes = (current_elapsed_seconds % 3600) // 60
            seconds = current_elapsed_seconds % 60
            self.timer_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            total_seconds = int(self.duration_minutes * 60)
            remaining_seconds = total_seconds - current_elapsed_seconds
            
            if remaining_seconds <= 0:
                self.timer_label.setText("00:00:00")
                self.timer_label.setStyleSheet("color: red;")
                self.update_timer.stop()
                self.stop_recording()
            else:
                hours = remaining_seconds // 3600
                minutes = (remaining_seconds % 3600) // 60
                seconds = remaining_seconds % 60
                self.timer_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
                
                if remaining_seconds <= 10:
                    self.timer_label.setStyleSheet("color: red;")
    
    def stop_recording(self):
        """Stop recording and close window."""
        self.update_timer.stop()
        self.stop_recording_signal.emit()
        self.accept()
    
    def get_elapsed_time(self):
        """Return elapsed recording time in seconds."""
        return self.elapsed_timer.elapsed() // 1000
    
    def closeEvent(self, event):
        """Clean up timer on window close."""
        self.update_timer.stop()
        self.stop_recording_signal.emit()
        event.accept()