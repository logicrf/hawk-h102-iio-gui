"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       tx_panel.py
@brief      Provide bilingual TX controls without direct hardware access.
@details    Transmit only after an explicit start; freeze active parameters and read IQ files only.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.6.0
@date       2026-10-15
"""
from pathlib import Path
from PySide6 import QtWidgets
from .tx_model import TxPlan
from .model import mhz_to_hz
from .i18n import LanguageManager, message
from .instrument_widgets import InstrumentCheckBox, icon_button, set_action


class TxPanel(QtWidgets.QGroupBox):
    """Collect TX controls and start/stop in the right panel, preserving stop while active."""
    def __init__(self, parent=None, *, i18n=None):
        super().__init__("TX control",parent)
        self.i18n = i18n if i18n is not None else LanguageManager(self)
        form=QtWidgets.QFormLayout(self)
        self.channels=QtWidgets.QComboBox()
        for label,channels in [('TX1',(1,)),('TX2',(2,)),('TX1 + TX2',(1,2))]:self.channels.addItem(label,channels)
        self.frequency=QtWidgets.QDoubleSpinBox();self.frequency.setRange(50,5800);self.frequency.setDecimals(6)
        self.frequency.setValue(2400);self.frequency.setSuffix(' MHz');self.frequency.setKeyboardTracking(False)
        self.attenuation=QtWidgets.QDoubleSpinBox();self.attenuation.setRange(20,40);self.attenuation.setDecimals(2)
        self.attenuation.setSingleStep(.05);self.attenuation.setValue(40);self.attenuation.setSuffix(' dB')
        self.source=QtWidgets.QComboBox();self.source.addItem("Coherent tone",'tone');self.source.addItem("Loop IQ16 file",'file')
        self.offset=QtWidgets.QDoubleSpinBox();self.offset.setRange(-20000,20000);self.offset.setDecimals(3)
        self.offset.setValue(250);self.offset.setSuffix(' kHz')
        self.peak=QtWidgets.QSpinBox();self.peak.setRange(1,8192);self.peak.setValue(4096)
        self.file=QtWidgets.QLineEdit();self.file.setReadOnly(True)
        self.browse=QtWidgets.QPushButton("Choose IQ file…");self.browse.clicked.connect(self._browse)
        self.seconds=QtWidgets.QSpinBox();self.seconds.setRange(1,300);self.seconds.setValue(10);self.seconds.setSuffix(" s")
        self.monitor=InstrumentCheckBox("Monitor selected RX channels");self.monitor.setChecked(True)
        self.start=QtWidgets.QPushButton("▶ Start TX");self.start.setStyleSheet('QPushButton:enabled{background:#985530;color:white;}')
        self.stop=QtWidgets.QPushButton("■ Stop TX");self.stop.setEnabled(False)
        actions=QtWidgets.QWidget();buttons=QtWidgets.QHBoxLayout(actions);buttons.setContentsMargins(0,0,0,0)
        self.start.hide(); self.stop.hide()
        buttons.addWidget(QtWidgets.QLabel('TX'))
        self.action = icon_button(); buttons.addWidget(self.action); buttons.addStretch()
        self.action.clicked.connect(lambda: self.stop.click() if self.stop.isEnabled() else self.start.click())
        set_action(self.action, 'play', message("Start TX"), i18n=self.i18n)
        self.summary=QtWidgets.QLabel("Off by default · Timed shutdown · Shared LO also tunes the paired TX");self.summary.setWordWrap(True)
        for label,widget in [("Channels",self.channels),("Center frequency",self.frequency),("Attenuation",self.attenuation),
                ("Waveform",self.source),("Tone offset",self.offset),("Digital peak",self.peak),("IQ file",self.file),
                ('',self.browse),("TX duration",self.seconds),('',self.monitor),('',actions),('',self.summary)]:form.addRow(label,widget)
        self.form=form;self.source.currentIndexChanged.connect(self._source_changed);self._source_changed()
        self.shared_frequency_hz=None

    def set_radio(self, radio):
        """Display actual shared RX carriers read-only without requests or implicit TX start."""
        self.shared_frequency_hz=None
        if radio and set(radio.get('mapping',{}).values())=={2}:
            values=radio['rx_center_frequency_hz']
            if values.get('1')==values.get('2') and type(values.get('1')) is int:
                self.shared_frequency_hz=values['1']
                self.frequency.setValue(self.shared_frequency_hz/1e6)
        self.i18n.bind(
            self.summary.setText,
            (
                message("Shared LO · TX follows RX center frequency · Timed shutdown")
                if self.shared_frequency_hz is not None
                else message("Independent RX/TX · Timed shutdown · TX channels on the same LO tune together")
            ),
        )

    def set_available(self, connected, idle, running):
        """Freeze active inputs but keep the right-panel stop action available."""
        self.setEnabled(connected)
        for widget in (self.channels,self.frequency,self.attenuation,self.source,self.offset,
                       self.peak,self.file,self.browse,self.seconds,self.monitor,self.start):
            widget.setEnabled(connected and idle)
        self.stop.setEnabled(connected and running)
        self.frequency.setEnabled(connected and idle and self.shared_frequency_hz is None)
        self.action.setEnabled(connected and (idle or running))
        set_action(
            self.action,
            ('stop' if running else 'play' if idle else 'busy'),
            (message("Stop TX") if running else message("Start TX") if idle else message("TX control busy")),
            ('#ef7777' if running else '#62dcba'),
            i18n=self.i18n,
        )

    def _source_changed(self,*_):
        """Show relevant waveform controls without reading files or triggering hardware operations."""
        file_mode=self.source.currentData()=='file'
        for widget in (self.file,self.browse):self.form.setRowVisible(widget,file_mode)
        for widget in (self.offset,self.peak):self.form.setRowVisible(widget,not file_mode)

    def _browse(self):
        """Select a 262144-byte IQ16 file; perform complete validation before start."""
        name,_=QtWidgets.QFileDialog.getOpenFileName(self,self.i18n.text("Loop IQ16 file"),'',self.i18n.text("IQ data (*.bin *.iq);;All files (*)"))
        if name:self.file.setText(name)

    def plan(self):
        """Freeze the current request and let the backend reject missing files or invalid values."""
        path=None
        if self.source.currentData()=='file':
            if not self.file.text():raise ValueError("Select a loop IQ file")
            path=Path(self.file.text())
        return TxPlan(self.channels.currentData(),mhz_to_hz(f'{self.frequency.value():.6f}'),
                      self.attenuation.value(),self.seconds.value(),self.offset.value()*1000,self.peak.value(),path)


# End of file: tx_panel.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
