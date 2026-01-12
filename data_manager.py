"""
Global data manager for LightRoom DarkRoom application.

Centralized storage for application state, camera settings, recording parameters,
and session information. Uses PyQt signals to notify widgets of data changes.
"""

from PyQt5.QtCore import QObject, pyqtSignal, QTime, QDateTime
from pathlib import Path


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
    """
    neuron_connectivity_updated = pyqtSignal()
    start_stop_toggled_signal = pyqtSignal()
    save_path_updated = pyqtSignal()
    start_time_updated = pyqtSignal(dict)

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
