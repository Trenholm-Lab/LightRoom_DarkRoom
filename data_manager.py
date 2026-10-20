"""
Global data manager for LightRoom DarkRoom application.

Centralized storage for application state, camera settings, recording parameters,
and session information. Uses PyQt signals to notify widgets of data changes.
"""

from PyQt5.QtCore import QObject, pyqtSignal, QTime, QDateTime, QDate
from pathlib import Path
import json

# Session metadata fields in display order, mapped to their human readable labels.
SESSION_METADATA_LABELS = {
    "mouse_id": "Mouse ID",
    "genotype": "Genotype",
    "sex": "Sex",
    "date_of_birth": "Date of Birth",
    "trial_number": "Trial",
    "lux_room_1": "Lux in Room 1",
    "lux_room_2": "Lux in Room 2",
    "comment": "Comment",
}

# Fields that may be left blank. Everything else has to be filled in before a
# recording can start.
OPTIONAL_METADATA_FIELDS = {"comment"}

# File used to carry metadata over between application runs.
SESSION_METADATA_FILE = Path(__file__).parent / "last_session_metadata.json"


class DataManager(QObject):
    """
    Centralized data manager for application-wide state.
    
    Stores and manages camera settings, recording parameters, session information,
    and timing data. Emits signals when key data changes to update UI components.
    
    Signals:
        neuron_connectivity_updated: Emitted when connectivity changes
        start_stop_toggled_signal: Emitted when recording starts/stops
        save_path_updated: Emitted when save path changes
        start_time_updated: Emitted when recording start time changes
        session_metadata_updated: Emitted when subject/trial metadata changes
    """
    neuron_connectivity_updated = pyqtSignal()
    start_stop_toggled_signal = pyqtSignal()
    save_path_updated = pyqtSignal()
    start_time_updated = pyqtSignal(dict)
    session_metadata_updated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()

        self.main_window_size = {'H': 1000, 'W': 1500}

        self.stop_method = "Manual"
        self.timer_duration = None
        self.recording_delay = 0
        self.swap_lights_enabled = False
        self.swap_interval = 30  # Default 30 seconds
        self.save_path = None
        self.session_name = None
        self.is_running = {"LightRoom": None, "DarkRoom": None}
        self.recording_started = False
        self.start_time = {"LightRoom": None, "DarkRoom": None}
        self.end_time = {"LightRoom": None, "DarkRoom": None}
        self.start_date = None
        self.start_datetime = None
        self.end_datetime = None
        
        self.recording_configs = {"LightRoom": None, "DarkRoom": None}

        # Subject/trial metadata entered in the "Session Info" tab. Values persist
        # between trials (and between runs) so only what changed has to be edited.
        self.session_metadata = self._blank_session_metadata()
        self.load_session_metadata()

        self.camera_settings = {
            "LightRoom":{
                    "disp_num": None,
                    "status": None,
                    "focus": None,
                    "frame_rate": None, 
                    "exposure": None, 
                    "zoom": None},
            "DarkRoom":{
                    "disp_num": None, 
                    "status": None,
                    "focus": None,
                    "frame_rate": None, 
                    "exposure": None, 
                    "zoom": None}}

    def set_start_time(self, room, QTime_time):
        """Set recording start time for a camera and emit signal."""
        self.start_time[room] = QTime_time
        self.start_time_updated.emit(self.start_time)
    
    def set_end_time(self, room, QTime_time):
        """
        Set recording end time for a camera.
        
        Args:
            room: "LightRoom" or "DarkRoom"
            QTime_time: QTime object representing the end time
        """
        self.end_time[room] = QTime_time
    
    def set_start_date(self, QDate_date):
        """Set recording start date."""
        self.start_date = QDate_date
    
    def set_start_datetime(self, datetime_obj):
        """
        Set recording session start datetime.
        
        Args:
            datetime_obj: QDateTime object
        """
        self.start_datetime = datetime_obj
    
    def set_end_datetime(self, datetime_obj):
        """
        Set recording session end datetime.
        
        Args:
            datetime_obj: QDateTime object
        """
        self.end_datetime = datetime_obj
    
    def set_recording_config(self, room, config_dict):
        """
        Store camera configuration snapshot at recording time.
        
        Args:
            room: "LightRoom" or "DarkRoom"
            config_dict: Dictionary containing camera configuration
        """
        self.recording_configs[room] = config_dict

    def set_is_running(self, room, is_running):
        """
        Set camera recording status.
        
        Args:
            room: "LightRoom" or "DarkRoom"
            is_running: Boolean indicating if camera is recording
        """
        self.is_running[room] = is_running

    def set_save_path(self, path):
        """
        Set save directory path for videos and emit signal.
        
        Args:
            path: Path to directory where videos will be saved
        """
        self.save_path = path
        self.save_path_updated.emit()
    
    def save_data(self):
        """Save session information (placeholder for future implementation)."""
        return 0 
    
    def set_stop_method(self, method):
        """
        Set recording stop method.
        
        Args:
            method: "Manual" or "Timer"
        """
        self.stop_method = method
    
    def set_swap_lights_enabled(self, enabled):
        """
        Enable or disable light swapping during recording.
        
        Args:
            enabled: Boolean indicating if light swapping is enabled
        """
        self.swap_lights_enabled = enabled
    
    def set_swap_interval(self, interval):
        """
        Set the interval for light swapping in seconds.
        
        Args:
            interval: Time in seconds between light swaps
        """
        self.swap_interval = interval
    
    def get_timer_duration(self):
        """
        Get timer duration formatted as MM:SS string.
        
        Returns:
            str: Remaining time as "MM:SS" or "00:00" if unset
        """
        if self.timer_duration is None:
            return "00:00"

        try:
            total_seconds = int(float(self.timer_duration) * 60)
        except Exception:
            return "00:00"

        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02}:{seconds:02}"

      
    def set_timer_duration(self, duration):
        """
        Set timer duration for recording.
        
        Args:
            duration: Duration in minutes (float)
        """
        self.timer_duration = duration
    
    def set_recording_delay(self, delay):
        """
        Set countdown delay before recording starts.
        
        Args:
            delay: Delay in seconds (int)
        """
        self.recording_delay = delay
    
    def set_session_name(self, name):
        """
        Set session name for current recording.
        
        Args:
            name: Session name string
        """
        self.session_name = name
    
    # ------------------------------------------------------------------
    # Subject / trial metadata
    # ------------------------------------------------------------------

    def _blank_session_metadata(self):
        """
        Return a metadata dictionary with every field unset.

        Returns:
            dict: Keys match SESSION_METADATA_LABELS. Text fields use "",
                  numeric fields use None, trial number starts at 1.
        """
        return {
            "mouse_id": "",
            "genotype": "",
            "sex": "",
            "date_of_birth": "",   # "yyyy-MM-dd" or "" when unset
            "trial_number": "1",   # free text, so "2b" or "retest" also work
            "lux_room_1": None,
            "lux_room_2": None,
            "comment": "",         # optional, appended to the file name
        }

    def set_session_metadata(self, metadata, persist=True):
        """
        Update subject/trial metadata and notify listeners.

        Only the keys present in `metadata` are changed, so a single field can be
        updated between trials without re-entering the rest.

        Args:
            metadata: Dictionary of metadata fields to update
            persist: Write the updated metadata to disk for the next run
        """
        for key, value in metadata.items():
            if key in self.session_metadata:
                self.session_metadata[key] = value

        if persist:
            self.save_session_metadata()

        self.session_metadata_updated.emit(dict(self.session_metadata))

    def get_missing_metadata_fields(self):
        """
        List metadata fields that still need a value before recording.

        Returns:
            list[str]: Human readable labels of the unset fields (empty when complete)
        """
        missing = []
        for key, label in SESSION_METADATA_LABELS.items():
            if key in OPTIONAL_METADATA_FIELDS:
                continue
            value = self.session_metadata.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(label)
        return missing

    def is_session_metadata_complete(self):
        """Return True when every metadata field has a value."""
        return not self.get_missing_metadata_fields()

    def get_age_in_days(self, at_datetime=None):
        """
        Age of the subject at recording time, derived from the date of birth.

        Args:
            at_datetime: QDateTime to measure against (defaults to session start,
                         then to the current time)

        Returns:
            int: Age in days, or None if the date of birth is unset/invalid
        """
        dob_str = self.session_metadata.get("date_of_birth")
        if not dob_str:
            return None

        dob = QDate.fromString(dob_str, "yyyy-MM-dd")
        if not dob.isValid():
            return None

        reference = at_datetime or self.start_datetime or QDateTime.currentDateTime()
        return dob.daysTo(reference.date())

    @staticmethod
    def sanitize_for_filename(text):
        """
        Make a metadata value safe to use in a file name.

        Args:
            text: Raw value, e.g. a mouse ID typed by the user

        Returns:
            str: Whitespace and path-unsafe characters replaced with underscores
        """
        cleaned = "".join(
            "_" if c in '/\\:*?"<>|' or c.isspace() else c
            for c in str(text).strip()
        )
        # Collapse runs of underscores so "M 123" and "M/123" both read cleanly
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_")

    def get_session_name(self, date=None):
        """
        Session name used for every file this recording produces.

        Built from the subject metadata as {mouse_id}_{date}_trial{trial}, with
        the comment appended when there is one, e.g.
        "M123_2026-10-20_trial4" or "M123_2026-10-20_trial2b_habituation".

        The trial is free text, so "2b" or "retest" are as valid as "3". The
        user never types a file name.

        Args:
            date: QDate for the recording (defaults to today)

        Returns:
            str: Session name, using "unknown" when no mouse ID is set
        """
        mouse_id = self.sanitize_for_filename(self.session_metadata.get("mouse_id") or "")
        if not mouse_id:
            mouse_id = "unknown"

        date_str = (date or QDate.currentDate()).toString("yyyy-MM-dd")

        trial = self.sanitize_for_filename(self.session_metadata.get("trial_number") or "")
        if not trial:
            trial = "1"

        name = f"{mouse_id}_{date_str}_trial{trial}"

        comment = self.sanitize_for_filename(self.session_metadata.get("comment") or "")
        if comment:
            name = f"{name}_{comment}"

        return name

    def load_session_metadata(self):
        """Load metadata saved by the previous run, ignoring a missing/bad file."""
        try:
            if SESSION_METADATA_FILE.exists():
                stored = json.loads(SESSION_METADATA_FILE.read_text())
                for key in self.session_metadata:
                    if key in stored:
                        self.session_metadata[key] = stored[key]
                # The trial used to be stored as a number; it is free text now
                trial = self.session_metadata.get("trial_number")
                if trial is not None and not isinstance(trial, str):
                    self.session_metadata["trial_number"] = str(trial)
        except Exception as e:
            print(f"[METADATA] Could not load {SESSION_METADATA_FILE}: {e}")

    def save_session_metadata(self):
        """Persist the current metadata so the next run starts pre-filled."""
        try:
            SESSION_METADATA_FILE.write_text(json.dumps(self.session_metadata, indent=2))
        except Exception as e:
            print(f"[METADATA] Could not save {SESSION_METADATA_FILE}: {e}")

    def get_session_file_path(self, camera_name):
        """
        Get full file path for camera recording based on session name.
        
        Args:
            camera_name: "camera_1" or "camera_2"
            
        Returns:
            str: Full path to .h264 video file, or None if path/name not set
        """
        if self.save_path is None or self.session_name is None:
            return None
        
        save_dir = Path(self.save_path)
        filename = f"{self.session_name}_{camera_name}.h264"
        return str(save_dir / filename)
