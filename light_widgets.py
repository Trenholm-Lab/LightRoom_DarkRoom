"""
Room lighting panel for the LightRoom/DarkRoom GUI.

One RoomLightControls per room: an IR on/off checkbox (GPIO, unchanged) and
the white lights, which are now set in lux through the GP8403 DAC current
sink (see chamber_lights.py). The slider is logarithmic so that 10, 100 and
1000 lux are all easy to reach; the readout under it shows the LED current
and DAC code actually being sent.
"""

import math

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                             QSlider, QVBoxLayout, QWidget, QAbstractSpinBox)

from chamber_lights import SENSE_OHMS

# Lux a room's white light is set to when the GUI starts (if switched on)
DEFAULT_WHITE_LUX = 1000.0

_SLIDER_STEPS = 1000     # slider positions 1..STEPS are log-spaced
_SLIDER_MIN_LUX = 1.0    # lux at slider position 1 (position 0 = 0 lux)


class RoomLightControls(QWidget):
    """
    IR checkbox + white-light checkbox, lux box, log slider and readout.

    Args:
        room: 1 or 2
        lights: chamber_lights.ChamberLights instance (shared by both rooms)
        ir_setter: callable(bool) that switches this room's IR bank
        ir_on, white_on, lux: initial state (applied immediately)
    """

    def __init__(self, room, lights, ir_setter, ir_on=False, white_on=False,
                 lux=DEFAULT_WHITE_LUX, parent=None):
        super().__init__(parent)
        self.room = room
        self.lights = lights
        self._ir_setter = ir_setter
        self._max_lux = max(1.0, math.floor(lights.max_lux(room)))

        layout = QVBoxLayout()
        layout.setSpacing(2)
        layout.setContentsMargins(5, 2, 5, 2)

        self.ir_chk = QCheckBox(f"IR Lights {room}")
        layout.addWidget(self.ir_chk)

        white_row = QHBoxLayout()
        white_row.setSpacing(5)
        self.white_chk = QCheckBox(f"White Lights {room}")
        white_row.addWidget(self.white_chk)

        self.lux_spin = QDoubleSpinBox()
        self.lux_spin.setRange(0.0, float(self._max_lux))
        self.lux_spin.setDecimals(1)
        self.lux_spin.setSuffix(" lux")
        self.lux_spin.setFixedWidth(115)
        # Only act on Enter / focus loss, so typing "1000" doesn't flash 1, 10, 100
        self.lux_spin.setKeyboardTracking(False)
        try:
            self.lux_spin.setStepType(QAbstractSpinBox.AdaptiveDecimalStepType)
        except AttributeError:
            self.lux_spin.setSingleStep(1.0)
        white_row.addWidget(self.lux_spin)

        self.lux_slider = QSlider(Qt.Horizontal)
        self.lux_slider.setRange(0, _SLIDER_STEPS)
        white_row.addWidget(self.lux_slider)
        layout.addLayout(white_row)

        self.readout = QLabel()
        self.readout.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.readout)
        self.setLayout(layout)

        self.ir_chk.stateChanged.connect(self._on_ir_changed)
        self.white_chk.stateChanged.connect(self._on_white_changed)
        self.lux_spin.valueChanged.connect(self._on_spin_changed)
        self.lux_slider.valueChanged.connect(self._on_slider_changed)

        self.set_state(ir_on, white_on, lux, apply=True)

    # ------------------------------------------------------------------
    # Slider <-> lux (log scale)
    # ------------------------------------------------------------------
    def _lux_to_pos(self, lux):
        if lux <= 0:
            return 0
        if lux <= _SLIDER_MIN_LUX:
            return 1
        frac = math.log(lux / _SLIDER_MIN_LUX) / math.log(self._max_lux / _SLIDER_MIN_LUX)
        return int(round(1 + frac * (_SLIDER_STEPS - 1)))

    def _pos_to_lux(self, pos):
        if pos <= 0:
            return 0.0
        frac = (pos - 1) / (_SLIDER_STEPS - 1)
        lux = _SLIDER_MIN_LUX * (self._max_lux / _SLIDER_MIN_LUX) ** frac
        # Round to something readable: 0.1 lux below 100, 1 lux above
        return round(lux, 1) if lux < 100 else float(round(lux))

    # ------------------------------------------------------------------
    # Widget callbacks
    # ------------------------------------------------------------------
    def _on_ir_changed(self, _state):
        self.apply_ir()

    def _on_white_changed(self, _state):
        self._update_enabled()
        self.apply_white()

    def _on_spin_changed(self, value):
        self.lux_slider.blockSignals(True)
        self.lux_slider.setValue(self._lux_to_pos(value))
        self.lux_slider.blockSignals(False)
        self.apply_white()

    def _on_slider_changed(self, pos):
        self.lux_spin.blockSignals(True)
        self.lux_spin.setValue(self._pos_to_lux(pos))
        self.lux_spin.blockSignals(False)
        self.apply_white()

    def _update_enabled(self):
        on = self.white_chk.isChecked()
        self.lux_spin.setEnabled(on)
        self.lux_slider.setEnabled(on)

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
            self.lights.set_lux(self.room, self.target_lux())
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
            text = f"{mA:.2f} mA · DAC code {self.lights.code(self.room)}"
            if not self.lights.is_calibrated(self.room):
                text += " · lux not calibrated (estimate)"
            self.readout.setText(text)
        self.readout.setStyleSheet("color: gray; font-size: 11px;")

    # ------------------------------------------------------------------
    # State (used by the light swap and the session log)
    # ------------------------------------------------------------------
    def target_lux(self):
        """Lux this room should be at right now (0 when white is off)."""
        return self.lux_spin.value() if self.white_chk.isChecked() else 0.0

    def state(self):
        return {"ir_on": self.ir_chk.isChecked(),
                "white_on": self.white_chk.isChecked(),
                "lux": self.lux_spin.value()}

    def set_state(self, ir_on, white_on, lux, apply=True):
        """Set all widgets at once. With apply=False nothing is sent to the
        hardware (the caller then applies both rooms together)."""
        widgets = (self.ir_chk, self.white_chk, self.lux_spin, self.lux_slider)
        for w in widgets:
            w.blockSignals(True)
        self.ir_chk.setChecked(bool(ir_on))
        self.white_chk.setChecked(bool(white_on))
        self.lux_spin.setValue(float(lux))
        self.lux_slider.setValue(self._lux_to_pos(self.lux_spin.value()))
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
            cal = self.lights.calibration[self.room]
            cal_txt = f"calibrated {cal.date}" if cal.calibrated else "uncalibrated estimate"
            white = (f"ON, {self.lux_spin.value():.1f} lux set ({cal_txt}), "
                     f"{mA:.2f} mA, DAC code {self.lights.code(self.room)}, "
                     f"{mA * SENSE_OHMS:.1f} mV on sense resistor")
        if not self.lights.hardware_ok:
            white += " [DAC NOT CONNECTED - simulated]"
        return f"IR {ir}; White {white}"
