"""
Global UI widgets for LightRoom DarkRoom application.

Provides reusable widget components for recording control, countdown timers,
camera setup dialogs, and save path selection. These widgets are shared
across the application interface.
"""

from PyQt5.QtCore import Qt, QDate, QTime, QTimer, QElapsedTimer, pyqtSignal
from PyQt5.QtWidgets import *
import sys

"""
GPIO handling: RPi.GPIO for the IR light pins (digital on/off). Falls back to
a mock on non-RPi systems. The white lights are no longer on GPIO/PWM - they
are driven by the GP8403 DAC current sink (see chamber_lights.py).
"""
_HAVE_RPI_GPIO = False

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

from data_manager import *
from picamera2 import Picamera2
from pathlib import Path

# GPIO pins (BCM) for the IR light banks (Q1 / Q4, unchanged).
# The white lights used to be PWM on GPIO 12 (room 1) and GPIO 18 (room 2);
# those pins are no longer used - the gate wires now come from the op-amp.
IR_PIN_ROOM1 = 27
IR_PIN_ROOM2 = 22


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


class SessionMetadataWidget(QWidget):
    """
    Form for the subject/trial metadata attached to every recording.

    Collects Mouse ID, Genotype, Sex, Date of Birth, Trial #, and the lux level
    measured in each room. Values are pushed into the data manager as they are
    edited and persist between trials, so only the fields that actually changed
    need to be touched before the next recording. The first trial has to have
    every field filled in - recording is blocked until then.

    Args:
        data_manager: Global data manager instance
    """

    NOT_SET_TEXT = "-- not set --"
    SEX_OPTIONS = ["Male", "Female", "Unknown"]
    FORM_WIDTH = 620  # keeps the fields a sensible size on a wide window

    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self._loading = False  # guards against feedback loops while repopulating

        # Edits are applied live but only written to disk once typing settles.
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(1000)
        self._persist_timer.timeout.connect(self.data_manager.save_session_metadata)

        title = QLabel("Session Info")
        title.setStyleSheet("font-weight: bold; font-size: 18px;")

        subtitle = QLabel(
            "Entered once, then carried over between trials. Edit only what "
            "changed before starting the next recording - every field must be "
            "filled in before the first trial."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: gray;")
        subtitle.setMaximumWidth(self.FORM_WIDTH)

        # --- Subject fields ---
        self.mouse_id_edit = QLineEdit()
        self.mouse_id_edit.setPlaceholderText("e.g. M123")

        self.genotype_edit = QLineEdit()
        self.genotype_edit.setPlaceholderText("e.g. C57BL/6J")

        self.sex_combo = QComboBox()
        self.sex_combo.addItem(self.NOT_SET_TEXT)
        self.sex_combo.addItems(self.SEX_OPTIONS)

        self.dob_edit = QDateEdit()
        self.dob_edit.setCalendarPopup(True)
        self.dob_edit.setDisplayFormat("yyyy-MM-dd")
        self.dob_edit.setMinimumDate(QDate(2000, 1, 1))
        self.dob_edit.setMaximumDate(QDate.currentDate())
        # The minimum date doubles as the "unset" state.
        self.dob_edit.setSpecialValueText(self.NOT_SET_TEXT)
        self.dob_edit.setDate(self.dob_edit.minimumDate())

        # --- Trial fields ---
        # Free text rather than a number, so "2b" or "retest" are usable
        self.trial_edit = QLineEdit()
        self.trial_edit.setPlaceholderText("e.g. 1, 2b, retest")

        # Optional, and appended to the end of the file name when present
        self.comment_edit = QLineEdit()
        self.comment_edit.setPlaceholderText("optional - added to the end of the file name")

        self.lux1_spin = self._make_lux_spinbox()
        self.lux2_spin = self._make_lux_spinbox()

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.addRow("Mouse ID:", self.mouse_id_edit)
        form.addRow("Genotype:", self.genotype_edit)
        form.addRow("Sex:", self.sex_combo)
        form.addRow("Date of Birth:", self.dob_edit)
        form.addRow("Trial:", self.trial_edit)
        form.addRow("Lux in Room 1:", self.lux1_spin)
        form.addRow("Lux in Room 2:", self.lux2_spin)
        form.addRow("Comment:", self.comment_edit)

        form_container = QWidget()
        form_container.setLayout(form)
        form_container.setMaximumWidth(self.FORM_WIDTH)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setMaximumWidth(self.FORM_WIDTH)

        self.new_mouse_btn = QPushButton("New Mouse")
        self.new_mouse_btn.setToolTip(
            "Clear the subject fields and reset the trial number to 1."
        )
        self.new_mouse_btn.clicked.connect(self.start_new_mouse)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.new_mouse_btn)
        button_layout.addStretch()

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(10)
        layout.addWidget(form_container)
        layout.addSpacing(10)
        layout.addWidget(self.status_label)
        layout.addLayout(button_layout)
        layout.addStretch()
        self.setLayout(layout)

        # Populate from whatever was carried over, then track edits.
        self.load_from_data_manager(self.data_manager.session_metadata)
        self._connect_field_signals()
        self.data_manager.session_metadata_updated.connect(self.load_from_data_manager)

    def _make_lux_spinbox(self):
        """Create a lux entry box where the minimum value means 'not set'."""
        spin = QDoubleSpinBox()
        spin.setDecimals(1)
        spin.setRange(-1.0, 200000.0)
        spin.setSingleStep(1.0)
        spin.setSuffix(" lux")
        spin.setSpecialValueText(self.NOT_SET_TEXT)
        spin.setValue(spin.minimum())
        return spin

    def _connect_field_signals(self):
        """Push every edit straight into the data manager."""
        self.mouse_id_edit.textChanged.connect(self.apply_to_data_manager)
        self.genotype_edit.textChanged.connect(self.apply_to_data_manager)
        self.sex_combo.currentIndexChanged.connect(self.apply_to_data_manager)
        self.dob_edit.dateChanged.connect(self.apply_to_data_manager)
        self.trial_edit.textChanged.connect(self.apply_to_data_manager)
        self.comment_edit.textChanged.connect(self.apply_to_data_manager)
        self.lux1_spin.valueChanged.connect(self.apply_to_data_manager)
        self.lux2_spin.valueChanged.connect(self.apply_to_data_manager)

    def collect_metadata(self):
        """
        Read the form into a metadata dictionary.

        Returns:
            dict: Unset fields come back as "" (text) or None (numeric)
        """
        dob = self.dob_edit.date()
        dob_str = "" if dob == self.dob_edit.minimumDate() else dob.toString("yyyy-MM-dd")

        sex = "" if self.sex_combo.currentIndex() == 0 else self.sex_combo.currentText()

        lux1 = None if self.lux1_spin.value() == self.lux1_spin.minimum() else self.lux1_spin.value()
        lux2 = None if self.lux2_spin.value() == self.lux2_spin.minimum() else self.lux2_spin.value()

        return {
            "mouse_id": self.mouse_id_edit.text().strip(),
            "genotype": self.genotype_edit.text().strip(),
            "sex": sex,
            "date_of_birth": dob_str,
            "trial_number": self.trial_edit.text().strip(),
            "lux_room_1": lux1,
            "lux_room_2": lux2,
            "comment": self.comment_edit.text().strip(),
        }

    def apply_to_data_manager(self):
        """Store the current form values and refresh the completeness status."""
        if self._loading:
            return
        self.data_manager.set_session_metadata(self.collect_metadata(), persist=False)
        self._persist_timer.start()
        self.update_status()

    def load_from_data_manager(self, metadata):
        """
        Populate the form from stored metadata.

        Args:
            metadata: Metadata dictionary from the data manager
        """
        self._loading = True
        try:
            for key, edit in (("mouse_id", self.mouse_id_edit),
                              ("genotype", self.genotype_edit),
                              ("trial_number", self.trial_edit),
                              ("comment", self.comment_edit)):
                value = str(metadata.get(key) or "")
                # Skip identical text so the caret stays where the user left it.
                if edit.text().strip() != value:
                    edit.setText(value)

            sex = str(metadata.get("sex") or "")
            index = self.sex_combo.findText(sex) if sex else 0
            self.sex_combo.setCurrentIndex(index if index >= 0 else 0)

            dob_str = str(metadata.get("date_of_birth") or "")
            dob = QDate.fromString(dob_str, "yyyy-MM-dd") if dob_str else QDate()
            self.dob_edit.setDate(dob if dob.isValid() else self.dob_edit.minimumDate())

            for key, spin in (("lux_room_1", self.lux1_spin), ("lux_room_2", self.lux2_spin)):
                value = metadata.get(key)
                spin.setValue(spin.minimum() if value is None else float(value))
        finally:
            self._loading = False

        self.update_status()

    def update_status(self):
        """Show whether the metadata is complete or which fields are missing."""
        missing = self.data_manager.get_missing_metadata_fields()
        if missing:
            self.status_label.setText("Missing before recording: " + ", ".join(missing))
            self.status_label.setStyleSheet("color: #b22222; font-weight: bold;")
        else:
            session_name = self.data_manager.get_session_name()
            self.status_label.setText(
                f"Session info complete - files will be named: {session_name}"
            )
            self.status_label.setStyleSheet("color: #2e8b57; font-weight: bold;")

    def start_new_mouse(self):
        """Clear the subject fields and reset the trial number for a new mouse."""
        reply = QMessageBox.question(
            self,
            "New Mouse",
            "Clear Mouse ID, Genotype, Sex, Date of Birth and Comment, and "
            "reset Trial to 1?\n\nLux values are kept.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._loading = True
        try:
            self.mouse_id_edit.clear()
            self.genotype_edit.clear()
            self.sex_combo.setCurrentIndex(0)
            self.dob_edit.setDate(self.dob_edit.minimumDate())
            self.trial_edit.setText("1")
            self.comment_edit.clear()
        finally:
            self._loading = False

        self.apply_to_data_manager()


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