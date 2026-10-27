"""
Room lighting panel for the LightRoom/DarkRoom GUI.

One RoomLightControls per room: an IR on/off checkbox (GPIO, unchanged) and
the white lights, set as a percent of full-scale LED current through the
GP8403 DAC current sink (see chamber_lights.py). Percent needs no lux meter
and no calibration; the readout under the slider shows the LED current and
DAC code actually being sent, so a meter reading can still be checked.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                             QSlider, QVBoxLayout, QWidget, QAbstractSpinBox)

from chamber_lights import SENSE_OHMS

# Brightness a room's white light starts at when the GUI opens (if switched
# on). 60 % is ~306 mA, the level the design was characterised at - the same
# startup current as the old 1000 lux default, so the MOSFET dissipation on
# launch is unchanged. 100 % would be ~510 mA.
DEFAULT_WHITE_PERCENT = 60.0

# Slider positions per percent: 10 gives 0.1 % resolution over 0-100 %
_SLIDER_PER_PERCENT = 10
_SLIDER_STEPS = 100 * _SLIDER_PER_PERCENT


class RoomLightControls(QWidget):
    """
    IR checkbox + white-light checkbox, percent box, slider and readout.

    Args:
        room: 1 or 2
        lights: chamber_lights.ChamberLights instance (shared by both rooms)
        ir_setter: callable(bool) that switches this room's IR bank
        ir_on, white_on, percent: initial state (applied immediately)
    """

    def __init__(self, room, lights, ir_setter, ir_on=False, white_on=False,
                 percent=DEFAULT_WHITE_PERCENT, parent=None):
        super().__init__(parent)
        self.room = room
        self.lights = lights
        self._ir_setter = ir_setter

        layout = QVBoxLayout()
        layout.setSpacing(2)
        layout.setContentsMargins(5, 2, 5, 2)

        self.ir_chk = QCheckBox(f"IR Lights {room}")
        layout.addWidget(self.ir_chk)

        white_row = QHBoxLayout()
        white_row.setSpacing(5)
        self.white_chk = QCheckBox(f"White Lights {room}")
        white_row.addWidget(self.white_chk)

        self.pct_spin = QDoubleSpinBox()
        self.pct_spin.setRange(0.0, 100.0)
        self.pct_spin.setDecimals(1)
        self.pct_spin.setSuffix(" %")
        self.pct_spin.setFixedWidth(90)
        self.pct_spin.setSingleStep(1.0)
        # Only act on Enter / focus loss, so typing "100" doesn't flash 1, 10
        self.pct_spin.setKeyboardTracking(False)
        white_row.addWidget(self.pct_spin)

        self.pct_slider = QSlider(Qt.Horizontal)
        self.pct_slider.setRange(0, _SLIDER_STEPS)
        white_row.addWidget(self.pct_slider)
        layout.addLayout(white_row)

        self.readout = QLabel()
        self.readout.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.readout)
        self.setLayout(layout)

        self.ir_chk.stateChanged.connect(self._on_ir_changed)
        self.white_chk.stateChanged.connect(self._on_white_changed)
        self.pct_spin.valueChanged.connect(self._on_spin_changed)
        self.pct_slider.valueChanged.connect(self._on_slider_changed)

        self.set_state(ir_on, white_on, percent, apply=True)

    # ------------------------------------------------------------------
    # Slider <-> percent (linear)
    # ------------------------------------------------------------------
    @staticmethod
    def _pct_to_pos(percent):
        return int(round(min(max(percent, 0.0), 100.0) * _SLIDER_PER_PERCENT))

    @staticmethod
    def _pos_to_pct(pos):
        return round(pos / _SLIDER_PER_PERCENT, 1)

    # ------------------------------------------------------------------
    # Widget callbacks
    # ------------------------------------------------------------------
    def _on_ir_changed(self, _state):
        self.apply_ir()

    def _on_white_changed(self, _state):
        self._update_enabled()
        self.apply_white()

    def _on_spin_changed(self, value):
        self.pct_slider.blockSignals(True)
        self.pct_slider.setValue(self._pct_to_pos(value))
        self.pct_slider.blockSignals(False)
        self.apply_white()

    def _on_slider_changed(self, pos):
        self.pct_spin.blockSignals(True)
        self.pct_spin.setValue(self._pos_to_pct(pos))
        self.pct_spin.blockSignals(False)
        self.apply_white()

    def _update_enabled(self):
        on = self.white_chk.isChecked()
        self.pct_spin.setEnabled(on)
        self.pct_slider.setEnabled(on)

    # ------------------------------------------------------------------
    # Hardware
    # ------------------------------------------------------------------
    def apply_ir(self):
        try:
            self._ir_setter(self.ir_chk.isChecked())
        except Exception as e:
            print(f"[GPIO] Error switching room {self.room} IR: {e}")

    def apply_white(self):
        try:
            self.lights.set_percent(self.room, self.target_percent())
        except Exception as e:
            print(f"[Lights] Error setting room {self.room} white light: {e}")
        self.refresh_readout()

    def refresh_readout(self):
        if not self.lights.hardware_ok:
            self.readout.setText("DAC not found - white light not connected")
            self.readout.setStyleSheet("color: red; font-size: 11px;")
            return
        if not self.white_chk.isChecked():
            self.readout.setText("off (0 mA)")
        else:
            mA = self.lights.current_mA(self.room)
            self.readout.setText(
                f"{mA:.2f} mA · DAC code {self.lights.code(self.room)} · "
                f"{mA * SENSE_OHMS:.0f} mV on sense")
        self.readout.setStyleSheet("color: gray; font-size: 11px;")

    # ------------------------------------------------------------------
    # State (used by the light swap and the session log)
    # ------------------------------------------------------------------
    def target_percent(self):
        """Percent this room should be at right now (0 when white is off)."""
        return self.pct_spin.value() if self.white_chk.isChecked() else 0.0

    def state(self):
        return {"ir_on": self.ir_chk.isChecked(),
                "white_on": self.white_chk.isChecked(),
                "percent": self.pct_spin.value()}

    def set_state(self, ir_on, white_on, percent, apply=True):
        """Set all widgets at once. With apply=False nothing is sent to the
        hardware (the caller then applies both rooms together)."""
        widgets = (self.ir_chk, self.white_chk, self.pct_spin, self.pct_slider)
        for w in widgets:
            w.blockSignals(True)
        self.ir_chk.setChecked(bool(ir_on))
        self.white_chk.setChecked(bool(white_on))
        self.pct_spin.setValue(float(percent))
        self.pct_slider.setValue(self._pct_to_pos(self.pct_spin.value()))
        for w in widgets:
            w.blockSignals(False)
        self._update_enabled()
        if apply:
            self.apply_ir()
            self.apply_white()

    def describe(self):
        """One-line summary for the session data file."""
        ir = "ON" if self.ir_chk.isChecked() else "off"
        if not self.white_chk.isChecked():
            white = "off"
        else:
            mA = self.lights.current_mA(self.room)
            white = (f"ON, {self.pct_spin.value():.1f} % of full scale, "
                     f"{mA:.2f} mA, DAC code {self.lights.code(self.room)}, "
                     f"{mA * SENSE_OHMS:.1f} mV on sense resistor")
        if not self.lights.hardware_ok:
            white += " [DAC NOT CONNECTED - simulated]"
        return f"IR {ir}; White {white}"
