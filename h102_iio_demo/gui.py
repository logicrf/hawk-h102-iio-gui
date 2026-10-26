"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       gui.py
@brief      Provide bilingual H102 IIO reception, configuration and bounded live plotting.
@details    Workers perform hardware operations; the Qt thread displays snapshots and waits for recovery.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.8.0
@date       2026-10-15
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time
import numpy as np

from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

from . import backend
from .model import budget, save_snapshot, mhz_to_hz, save_json
from .sweep import SweepPlan, SweepSession
from .window_chrome import WindowChrome, CollapsibleSection
from .tx_panel import TxPanel
from .preset_modes import profile_mode, logical_profile, mode_profiles
from .i18n import LanguageManager, message, join_messages
from .instrument_widgets import FrequencyDial, InstrumentCheckBox, icon_button, set_action
from .tx_backend import TxSession, warm_tx_control


class Worker(QtCore.QThread):
    """Execute one operation and pass Python results only, never shared C handles."""
    completed = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    notice = QtCore.Signal(str, object)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        """Return the actual exception without creating or modifying widgets in a worker."""
        try:
            self.completed.emit(self.function())
        except Exception as error:
            self.failed.emit(error)


class MainWindow(QtWidgets.QMainWindow):
    """Keep configuration and RX/TX exclusive; idle control warmup holds no board locks."""
    def __init__(self, host: str, known_hosts: Path, output_root: Path, parent=None, *, language=None, settings=None):
        super().__init__(parent)
        self.i18n = LanguageManager(self, settings)
        self.known_hosts, self.output_root = known_hosts, output_root
        self.connection = None
        self.warm_link = None
        self.warm_worker = None
        self.warm_tx_link = None
        self.warm_tx_worker = None
        self.idle_link = None
        self.state = None
        self.worker = None
        self.session = None
        self.last_result = None
        self.record_next = False
        self.pending_frequency = None
        self.pending_result = self.pending_error = None
        self.operation = None
        self.closing_requested = False
        self.recovery_failed = False
        self.last_frames = {}
        self.operation_started = 0.0
        self.view_keys = {}
        self.last_stats_refresh = 0.0
        self.ui_metrics = dict(refresh_count=0,max_refresh_seconds=0.0,first_visible_seconds=None,plotted_frames=0,last_visible_seconds=None)
        self.setWindowFlag(QtCore.Qt.FramelessWindowHint,True)
        self.setWindowTitle("LogicRF Hawk H102 · IIO RX / TX / Sweep · v0.8.0")
        self.resize(1160, 880)
        self._build(host)
        self.chrome=WindowChrome(self);self.setMenuWidget(self.chrome)
        self.chrome.setStyleSheet('QWidget#h102-titlebar{background:#111b23;} QToolButton{border:0;border-radius:4px;background:transparent;color:#9aafbe;font-size:20px;} QToolButton:hover{background:#2b3d49;} QToolButton#h102-close-window:hover{background:#a6474b;color:white;}')
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(30)
        self._controls()
        self.i18n.capture(self)
        for plot in (*self.fft_widgets.values(), *self.wave_widgets.values(),
                     *self.waterfall_widgets.values(), self.sweep_plot, self.sweep_waterfall):
            self.i18n.capture_plot(plot)
        self.i18n.changed.connect(self._language_changed)
        self.i18n.storage_failed.connect(lambda _: self.i18n.bind(
            self.phase.setText, message("Could not save language preference; current selection remains active")))
        self.i18n.set_language(language or self.i18n.preferred, persist=False)

    def _language_changed(self, language):
        """Synchronize language selection without refreshing controls or rebuilding acquisition."""
        blocker = QtCore.QSignalBlocker(self.chrome.language)
        self.chrome.language.setCurrentIndex(self.chrome.language.findData(language))
        del blocker

    def _build(self, host):
        """Arrange a tuning bar, spectrum/waterfall and right-hand device panel inspired by SigDigger."""
        self.setMouseTracking(True)
        self.setMinimumSize(1100, 760)
        self.resize(1440, 940)
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#182129; color:#ccd8e1; }
            QGroupBox { border:0; background:#19232c; border-radius:6px; margin-top:18px; padding:12px 10px 10px; }
            QGroupBox::title { subcontrol-origin:margin; left:2px; color:#95abbc; font-weight:600; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#111b23; border:1px solid transparent; border-radius:5px; padding:6px; selection-background-color:#2575a5; }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color:#438b9b; }
            QPushButton { background:#2a3a46; border:0; border-radius:5px; padding:7px 11px; }
            QPushButton:hover { background:#355061; } QPushButton:pressed { background:#416171; }
            QPushButton:disabled { color:#607482; background:#21303a; }
            QTabWidget::pane { border:0; }
            QTabBar::tab { background:#172630; color:#9fb3c2; padding:8px 22px;
                margin:0 5px 5px 0; border:0; border-radius:7px; min-width:48px; }
            QTabBar::tab:hover:!selected { background:#263b47; color:#d7e8f0; }
            QTabBar::tab:selected { background:#285047; color:#9cf0d6; font-weight:600; }
            QTabBar::tab:disabled { background:#172129; color:#506572; }
            QCheckBox { spacing:8px; color:#cbdce5; }
            QCheckBox::indicator { width:17px; height:17px; border:1px solid #8099aa;
                border-radius:4px; background:#102530; }
            QCheckBox::indicator:hover { border:1px solid #a2dccc; background:#1c3c43; }
            QCheckBox::indicator:checked { background:#247e69; border:1px solid #78e3c4; }
            QCheckBox:disabled { color:#607585; }
            QCheckBox::indicator:disabled { background:#1d2b34; border:1px solid #425967; }
            QDockWidget::title { background:#182129; color:#95abbc; padding:10px; }
            QScrollArea { border:0; }
            QScrollBar:vertical { background:#182129; width:10px; margin:4px 1px; border:0; }
            QScrollBar::handle:vertical { background:#3b5262; min-height:44px; border-radius:4px; }
            QScrollBar::handle:vertical:hover { background:#56788c; }
            QScrollBar::handle:vertical:pressed { background:#6c9aab; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; border:0; background:transparent; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
            QScrollBar:horizontal { background:#182129; height:10px; margin:1px 4px; border:0; }
            QScrollBar::handle:horizontal { background:#3b5262; min-width:44px; border-radius:4px; }
            QScrollBar::handle:horizontal:hover { background:#56788c; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; border:0; background:transparent; }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }
            QAbstractScrollArea::corner { background:#182129; border:0; }
            QSplitter::handle { background:#182129; height:5px; }
            QMenuBar { background:#182129; color:#8fa4b4; }
        """)
        central = QtWidgets.QWidget(); self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central); root.setContentsMargins(14, 10, 14, 10); root.setSpacing(12)
        heading = QtWidgets.QHBoxLayout()
        brand = QtWidgets.QLabel("LogicRF  ·  Hawk H102")
        brand.setStyleSheet("font-size:18px;font-weight:600;color:#d9e9f2")
        brand.hide(); heading.addStretch()
        self.connect_status = QtWidgets.QLabel("Gigabit IIO  ·  RX / TX")
        self.connect_status.setStyleSheet("color:#8aa5b8")
        heading.addWidget(self.connect_status); self.connect_status.hide()

        tune = QtWidgets.QFrame(); tune.setStyleSheet("QFrame{background:#111b23;border:0;border-radius:8px;}")
        top = QtWidgets.QVBoxLayout(tune); top.setContentsMargins(12, 8, 12, 8)
        banner = QtWidgets.QHBoxLayout()
        self.frequency_readout = QtWidgets.QLabel("— MHz")
        self.frequency_readout.setStyleSheet("font-family:'DejaVu Sans Mono';font-size:30px;color:#62dcba;border:0")
        self.frequency_readout.hide()
        self.center = FrequencyDial()
        banner.addWidget(self.center, 1)
        self.start_button = QtWidgets.QPushButton("▶ Start RX")
        self.start_button.setMinimumWidth(120)
        self.start_button.setStyleSheet("QPushButton:enabled{background:#187d69;color:white;border:0;}")
        self.stop_button = QtWidgets.QPushButton("■ Stop RX")
        self.save_button = QtWidgets.QPushButton("Save IQ…")
        self.start_button.hide(); self.stop_button.hide(); self.save_button.hide()
        banner.addWidget(QtWidgets.QLabel('RX'))
        self.rx_action = icon_button(); banner.addWidget(self.rx_action)
        self.rx_action.clicked.connect(lambda: self._stop() if self.stop_button.isEnabled() else self._start())
        self.snapshot_action = icon_button(); banner.addWidget(self.snapshot_action)
        set_action(self.snapshot_action, 'save', message("Export latest IQ snapshot"), i18n=self.i18n)
        self.snapshot_action.clicked.connect(self._save)
        self.record_action = icon_button(); banner.addWidget(self.record_action)
        set_action(
            self.record_action,
            'record',
            message("Record raw IQ (check DMA overflow and complete file writes; keep partial files on failure)"),
            '#ef7777',
            i18n=self.i18n,
        )
        self.record_action.clicked.connect(self._record)
        top.addLayout(banner)
        tuning = QtWidgets.QHBoxLayout()
        self.center_button = QtWidgets.QPushButton("Apply center frequency")
        self.rf_axis = InstrumentCheckBox("RF frequency axis")
        self.center_button.hide()
        tuning.deleteLater()
        self.center_actual = QtWidgets.QLabel("Connect to read RX LO groups and carrier")
        self.center_actual.setWordWrap(True); self.center_actual.setStyleSheet("color:#8ba7ba;border:0;font-size:11px")
        top.addWidget(self.center_actual); root.addWidget(tune)
        self.center.valueChanged.connect(self._controls)
        self.center_button.clicked.connect(self._tune_center)
        self.center.commitRequested.connect(self._tune_center)

        self.rf_axis.toggled.connect(self._axis_changed)
        self.start_button.clicked.connect(self._start); self.stop_button.clicked.connect(self._stop); self.save_button.clicked.connect(self._save)

        pg.setConfigOptions(antialias=False, background="#0b1319", foreground="#a9c0d0")
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setDrawBase(False)
        self.plots, self.fft_widgets = {}, {}
        self.wave_widgets = {}
        self.waterfall_widgets, self.waterfall_images, self.waterfall_history = {}, {}, {}
        self.waterfall_seen, self.waterfall_frequency = {}, {}
        self.waterfall_geometry = {}
        self.cursor_lines, self.cursor_proxies, self.cursor_slots = {}, [], []
        self.peak_markers, self.peak_labels, self.hold_curves, self.hold_values = {}, {}, {}, {}
        for channel in (1, 2):
            pane = QtWidgets.QWidget(); layout = QtWidgets.QVBoxLayout(pane); layout.setContentsMargins(3, 3, 3, 3)
            splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
            fft = pg.PlotWidget(title=f"RX{channel} · Spectrum")
            self.i18n.axis(fft, 'bottom', message("Baseband frequency"), units='MHz'); fft.getAxis("bottom").enableAutoSIPrefix(False)
            self.i18n.axis(fft, 'left', message("Amplitude"), units='dBFS'); fft.showGrid(x=False, y=False, alpha=.05); self.i18n.bind(fft.setToolTip, message("Hann window, DC removed; dBFS is digital amplitude, not calibrated dBm"))
            fft.disableAutoRange(); fft.setYRange(-160, 0, padding=0)
            spectrum = fft.plot(pen=pg.mkPen("#74d4b3", width=1))
            spectrum.setDownsampling(auto=True,method='peak');spectrum.setClipToView(True)
            self.hold_curves[channel] = fft.plot(pen=pg.mkPen('#d7a65e', width=1))
            self.peak_markers[channel] = pg.ScatterPlotItem(size=8, brush='#efbe6a')
            self.peak_labels[channel] = pg.TextItem(color='#efbe6a', anchor=(.5,1))
            fft.addItem(self.peak_markers[channel]); fft.addItem(self.peak_labels[channel])
            fft.getViewBox().setMouseMode(pg.ViewBox.RectMode)
            cursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#8fa9bc", style=QtCore.Qt.DashLine))
            cursor.hide(); fft.addItem(cursor, ignoreBounds=True); self.cursor_lines[channel] = cursor
            slot = lambda args,c=channel:self._cursor_moved(c,args)
            self.cursor_slots.append(slot)
            proxy = pg.SignalProxy(fft.scene().sigMouseMoved, rateLimit=20, slot=slot)
            self.cursor_proxies.append(proxy)
            waterfall = pg.PlotWidget(title=f"RX{channel} · Waterfall")
            self.i18n.axis(waterfall, 'bottom', message("Baseband frequency"), units='MHz'); waterfall.getAxis("bottom").enableAutoSIPrefix(False)
            self.i18n.axis(waterfall, 'left', message("Display frames")); self.i18n.bind(waterfall.setToolTip, message("Latest 240 display frames; not the full stream or an exact time axis"))
            waterfall.setYRange(-240, 0, padding=0); waterfall.setMouseEnabled(x=True, y=False)
            waterfall.setXLink(fft)
            item = pg.ImageItem(axisOrder="row-major")
            item.setLookupTable(pg.colormap.get("inferno").getLookupTable(nPts=256))
            waterfall.addItem(item); waterfall.disableAutoRange()
            wave = pg.PlotWidget(title=f"RX{channel} · I / Q")
            self.i18n.axis(wave, 'bottom', message("Time"), units='µs'); wave.getAxis("bottom").enableAutoSIPrefix(False)
            self.i18n.axis(wave, 'left', message("Amplitude"), units='ADC code'); wave.addLegend(offset=(10, 10)); wave.showGrid(x=False, y=False, alpha=.05); self.i18n.bind(wave.setToolTip, message("First 2,048 samples of the latest complete IQ block"))
            i = wave.plot(pen=pg.mkPen("#5ac8ef", width=1), name="I")
            q = wave.plot(pen=pg.mkPen("#e4ae57", width=1), name="Q")
            wave.disableAutoRange();self.wave_widgets[channel]=wave
            for widget in (fft,waterfall,wave):
                widget.hideButtons()
                for name in ('left','bottom'):
                    widget.getAxis(name).setPen(pg.mkPen('#354651'))
                    widget.getAxis(name).setTextPen(pg.mkPen('#879baa'))
            self.plots[channel] = (i, q, spectrum); self.fft_widgets[channel] = fft
            self.waterfall_widgets[channel], self.waterfall_images[channel] = waterfall, item
            for widget in (fft, waterfall, wave): splitter.addWidget(widget)
            splitter.setSizes([360, 260, 150]); wave.hide(); layout.addWidget(splitter)
            self.tabs.addTab(pane, f"RX{channel}")
        self.tabs.currentChanged.connect(self._refresh)
        root.addWidget(self.tabs, 1)
        self.phase = QtWidgets.QLabel("Disconnected [msg-c748941e]")
        self.phase.setWordWrap(True)
        self.phase.setMinimumWidth(0)
        self.phase.setWordWrap(True); self.phase.setStyleSheet("color:#8eb9d5;padding:4px")
        root.addWidget(self.phase)
        self.cursor_label = QtWidgets.QLabel("Spectrum: zoom / pan; cursor uses LO at capture time")
        self.cursor_label.setStyleSheet("color:#718fa3;font-size:11px")
        root.addWidget(self.cursor_label); self.cursor_label.hide()

        dock = QtWidgets.QDockWidget("Device & acquisition", self)
        dock.setObjectName("h102-receiver-controls")
        dock.setAllowedAreas(QtCore.Qt.RightDockWidgetArea)
        dock.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        side = QtWidgets.QWidget(); side.setMinimumWidth(300)
        controls = QtWidgets.QVBoxLayout(side); controls.setContentsMargins(9, 7, 9, 9)
        self.sections={}
        def add_section(key,title,content,expanded=True):
            section=CollapsibleSection(title,content,expanded)
            self.sections[key]=section;controls.addWidget(section)
        connection_box = QtWidgets.QGroupBox("Connection")
        connection_layout = QtWidgets.QFormLayout(connection_box)
        self.host = QtWidgets.QLineEdit(host)
        connection_layout.addRow("IP / host", self.host)
        buttons = QtWidgets.QHBoxLayout()
        self.connect_button = QtWidgets.QPushButton("Connect / refresh"); self.disconnect_button = QtWidgets.QPushButton("Disconnect")
        buttons.addWidget(self.connect_button); buttons.addWidget(self.disconnect_button); connection_layout.addRow(buttons)
        self.connect_button.clicked.connect(self._connect); self.disconnect_button.clicked.connect(self._disconnect)
        add_section('connection',"Connection",connection_box)
        config_box = QtWidgets.QGroupBox("RX configuration [msg-c5ba0e40]")
        form = QtWidgets.QFormLayout(config_box)
        self.profiles = QtWidgets.QComboBox(); self.profiles.setMinimumWidth(0)
        self.rf_mode = QtWidgets.QComboBox()
        self.rf_mode.addItem("Independent RX / TX",'independent');self.rf_mode.addItem("Shared RX / TX LO",'shared-lo2')
        self.i18n.bind(self.rf_mode.setToolTip, message("Select and apply while idle; shared LO makes TX follow RX, independent mode allows separate frequencies."))
        self.rf_mode.currentIndexChanged.connect(self._mode_profiles_changed)
        self.apply_button = QtWidgets.QPushButton("Apply profile")
        self.channels = QtWidgets.QComboBox()
        for label, data in (("RX1", (1,)), ("RX2", (2,)), ("RX1 + RX2", (1, 2))): self.channels.addItem(label, data)
        self.mode = QtWidgets.QComboBox(); self.mode.addItem("Live RX · Timed stop", "continuous"); self.mode.addItem("Single capture / 65,536 IQ", "snapshot")
        self.mode.addItem("Live RX · Manual stop", "live"); self.mode.addItem("Single-channel sweep", "sweep")
        self.mode.hide()
        self.acquisition_mode=QtWidgets.QComboBox()
        for label,data in [("Live RX",'live'),("Single capture",'snapshot'),("Segmented sweep",'sweep')]:
            self.acquisition_mode.addItem(label,data)
        self.stop_condition=QtWidgets.QComboBox()
        self.stop_condition.addItem("Manual stop",'live');self.stop_condition.addItem("Timed stop",'continuous')
        self.mode.setCurrentIndex(2)
        self.acquisition_mode.currentIndexChanged.connect(self._select_acquisition_mode)
        self.stop_condition.currentIndexChanged.connect(self._select_acquisition_mode)
        self.pattern = QtWidgets.QComboBox(); self.pattern.addItem("Normal IQ", "normal"); self.pattern.addItem("Digital RAMP16 check", "ramp16")
        self.seconds = QtWidgets.QSpinBox(); self.seconds.setRange(1, 300); self.seconds.setValue(300); self.seconds.setSuffix(" s")
        for label, widget in (("RX / TX LO mode", self.rf_mode), ("Profile", self.profiles), ("", self.apply_button), ("Channels", self.channels), ("Acquisition", self.acquisition_mode), ("Stop condition", self.stop_condition), ("Source", self.pattern), ("RX duration", self.seconds)): form.addRow(label, widget)
        self.config_form=form
        self.channels.currentIndexChanged.connect(self._group_changed)
        add_section('rx',"RX configuration [msg-e36a115a]",config_box)
        self.tx_panel=TxPanel(i18n=self.i18n);add_section('tx',"TX control",self.tx_panel,False)
        self.tx_panel.start.clicked.connect(self._start_tx)
        self.tx_panel.stop.clicked.connect(self._stop)
        self.sweep_box=QtWidgets.QGroupBox("Segmented sweep")
        sweep_form=QtWidgets.QFormLayout(self.sweep_box)
        self.sweep_start=QtWidgets.QDoubleSpinBox();self.sweep_stop=QtWidgets.QDoubleSpinBox()
        for spin in (self.sweep_start,self.sweep_stop):
            spin.setRange(30,6000);spin.setDecimals(6);spin.setSuffix(" MHz")
        self.sweep_start.setValue(2395);self.sweep_stop.setValue(2405)
        self.sweep_fft=QtWidgets.QComboBox()
        for n in (1024,2048,4096,8192,16384):self.sweep_fft.addItem(str(n),n)
        self.sweep_fft.setCurrentText("8192")
        self.sweep_averages=QtWidgets.QSpinBox();self.sweep_averages.setRange(1,32)
        self.sweep_settle=QtWidgets.QSpinBox();self.sweep_settle.setRange(0,2000);self.sweep_settle.setValue(2);self.sweep_settle.setSuffix(" ms")
        self.sweep_repeat=InstrumentCheckBox("Repeat until stopped")
        self.sweep_wide=QtWidgets.QPushButton("Fast panorama · 40 MHz / 2048 bins")
        self.i18n.bind(
            self.sweep_wide.setToolTip,
            message("Apply 61.44 MSPS / 40 MHz, 50–5800 MHz, 2048 bins, one average, 2 ms settle; target under 10 s per round. Preparation is separate; increase FFT size for detail."),
        )
        self.sweep_wide.clicked.connect(self._wide_sweep_profile)
        sweep_form.addRow(self.sweep_wide)
        self.sweep_estimate=QtWidgets.QLabel("Segmented scan; use a wideband profile for wide spans")
        self.sweep_estimate.setWordWrap(True)
        sweep_form.addRow(self.sweep_estimate)
        for spin in (self.sweep_start,self.sweep_stop,self.sweep_settle):spin.valueChanged.connect(self._controls)
        for label,widget in (("Start",self.sweep_start),("Stop",self.sweep_stop),("FFT size",self.sweep_fft),
                             ("Averages",self.sweep_averages),("Settle time",self.sweep_settle),("",self.sweep_repeat)):
            sweep_form.addRow(label,widget)
        add_section('sweep',"Segmented sweep",self.sweep_box)
        sweep_pane=QtWidgets.QWidget();sweep_layout=QtWidgets.QVBoxLayout(sweep_pane)
        self.sweep_plot=pg.PlotWidget(title="Segmented sweep")
        self.i18n.axis(self.sweep_plot, 'bottom', message("RF frequency"), units='MHz');self.sweep_plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.i18n.axis(self.sweep_plot, 'left', message("Amplitude"), units='dBFS');self.sweep_plot.addLegend();self.sweep_plot.showGrid(x=False,y=False,alpha=.05); self.i18n.bind(self.sweep_plot.setToolTip, message("Segments are captured at different times; not a simultaneous full-band spectrum"))
        self.sweep_curve=self.sweep_plot.plot(pen=pg.mkPen("#5bdfae"),name="Current round")
        self.sweep_max_curve=self.sweep_plot.plot(pen=pg.mkPen("#e4ae57"),name="Max hold")
        self.sweep_waterfall=pg.PlotWidget(title="Complete sweep history (not an exact time axis)")
        self.i18n.axis(self.sweep_waterfall, 'bottom', message("RF frequency"), units='MHz');self.sweep_waterfall.getAxis("bottom").enableAutoSIPrefix(False)
        self.i18n.axis(self.sweep_waterfall, 'left', message("Previous rounds"));self.sweep_waterfall.setYRange(-240,0,padding=0);self.sweep_waterfall.setXLink(self.sweep_plot)
        self.sweep_waterfall.setMouseEnabled(x=True,y=False)
        self.sweep_image=pg.ImageItem(axisOrder="row-major");self.sweep_image.setLookupTable(pg.colormap.get("inferno").getLookupTable(nPts=256))
        self.sweep_waterfall.addItem(self.sweep_image)
        sweep_layout.addWidget(self.sweep_plot,2);sweep_layout.addWidget(self.sweep_waterfall,1)
        self.tabs.addTab(sweep_pane,"Wideband sweep")
        self.sweep_last_frame=None;self.sweep_last_round=0;self.sweep_history=None
        self.apply_button.clicked.connect(self._apply)
        for box in (self.profiles, self.channels, self.mode, self.pattern): box.currentIndexChanged.connect(self._controls)
        actual_box = QtWidgets.QGroupBox("Readback / network budget")
        actual_layout = QtWidgets.QVBoxLayout(actual_box)
        self.actual = QtWidgets.QLabel("Disconnected; actual settings come from device readback"); self.actual.setWordWrap(True)
        self.budget_label = QtWidgets.QLabel("Continuous IIO budget: 64 MB/s"); self.budget_label.setWordWrap(True)
        actual_layout.addWidget(self.actual); actual_layout.addWidget(self.budget_label); add_section('actual',"Readback / network budget",actual_box,False)
        display_box = QtWidgets.QGroupBox("Display tools")
        display_form = QtWidgets.QFormLayout(display_box)
        self.show_grid = InstrumentCheckBox("Grid")
        self.show_iq = InstrumentCheckBox("I/Q waveform")
        self.show_peak = InstrumentCheckBox("Peak marker"); self.show_peak.setChecked(True)
        self.show_hold = InstrumentCheckBox("Max hold")
        self.box_zoom = InstrumentCheckBox("Rectangle zoom"); self.box_zoom.setChecked(True)
        self.i18n.bind(self.box_zoom.setToolTip, message("Checked: drag to zoom. Unchecked: drag to pan. Double-click to reset."))
        display_form.addRow(self.rf_axis)
        display_form.addRow(self.show_peak); display_form.addRow(self.show_hold); display_form.addRow(self.box_zoom)
        self.box_zoom.toggled.connect(lambda enabled: [p.getViewBox().setMouseMode(pg.ViewBox.RectMode if enabled else pg.ViewBox.PanMode) for p in (*self.fft_widgets.values(), self.sweep_plot)])
        self.show_peak.toggled.connect(self._reset_peaks)
        self.show_hold.toggled.connect(self._reset_peaks)
        self.sweep_plot.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        display_form.addRow(self.show_grid); display_form.addRow(self.show_iq)
        self.show_grid.toggled.connect(self._grid_visibility)
        self.show_iq.toggled.connect(self._iq_visibility)
        self.waterfall_floor = QtWidgets.QSpinBox(); self.waterfall_floor.setRange(-200, -1); self.waterfall_floor.setValue(-150); self.waterfall_floor.setSuffix(" dBFS")
        self.waterfall_ceiling = QtWidgets.QSpinBox(); self.waterfall_ceiling.setRange(-199, 0); self.waterfall_ceiling.setValue(-90); self.waterfall_ceiling.setSuffix(" dBFS")
        self.reset_view_button = QtWidgets.QPushButton("Reset spectrum / waveform view")
        display_form.addRow("Waterfall floor", self.waterfall_floor); display_form.addRow("Waterfall ceiling", self.waterfall_ceiling); display_form.addRow(self.reset_view_button)
        self.waterfall_floor.valueChanged.connect(self._waterfall_levels_changed); self.waterfall_ceiling.valueChanged.connect(self._waterfall_levels_changed)
        self.reset_view_button.clicked.connect(self._reset_view); add_section('display',"Display",display_box,False)
        stats_box = QtWidgets.QGroupBox("RX statistics")
        stats_layout = QtWidgets.QVBoxLayout(stats_box)
        self.statistics = QtWidgets.QLabel("No IQ data"); self.statistics.setWordWrap(True); stats_layout.addWidget(self.statistics); add_section('stats',"RX statistics",stats_box,False)
        footer = QtWidgets.QLabel("RX disables TX; transmission requires an explicit start. Normal IQ lost sample count is unknown; RAMP16 checks modulo 65,536.\nWaterfall frames may be merged; all complete blocks are still checked. Snapshot saves the latest complete block; dual RX is not guaranteed synchronous.\ndBFS is digital amplitude, not calibrated dBm; carrier readback does not prove absolute RF frequency accuracy.")
        footer.setWordWrap(True); footer.setStyleSheet("color:#7893a5;font-size:11px"); add_section('notes',"Notes",footer,False); controls.addStretch()
        for combo in side.findChildren(QtWidgets.QComboBox):
            combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(10)
            combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            combo.currentTextChanged.connect(combo.setToolTip)
        for layout in side.findChildren(QtWidgets.QFormLayout):
            layout.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
            layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        for label in side.findChildren(QtWidgets.QLabel):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
        scroll.setWidget(side); dock.setWidget(scroll); self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.controls_dock = dock
        self.resizeDocks([dock], [360], QtCore.Qt.Horizontal)

    def _reset_peaks(self, *_):
        """Clear hold history on mode changes; never join peaks across profiles, frequencies or sessions."""
        self.hold_values.clear()
        for channel in (1,2):
            self.hold_curves[channel].clear()
            self.peak_markers[channel].clear()
            self.i18n.bind(self.peak_labels[channel].setText, '')
        self.last_frames.clear()

    def _select_acquisition_mode(self, *_):
        """Map display mode and stop conditions to the existing acquisition backend."""
        choice=self.acquisition_mode.currentData()
        mode=self.stop_condition.currentData() if choice=='live' else choice
        self.mode.setCurrentIndex(self.mode.findData(mode))

    def _grid_visibility(self, visible):
        """Change plot grids only, retaining axes, units and original IQ measurements."""
        for plot in (*self.fft_widgets.values(), *self.wave_widgets.values(), self.sweep_plot):
            plot.showGrid(x=visible, y=visible, alpha=.05)

    def _iq_visibility(self, visible):
        """Show I/Q traces on demand; hidden raw blocks remain acquired, checked and exportable."""
        for plot in self.wave_widgets.values():
            plot.setVisible(visible)

    def _new_connection(self):
        """Construct in-memory connection parameters without storing passwords."""
        connection = backend.Connection(self.host.text().strip())
        connection.validate()
        return connection

    def _launch(self, operation, function):
        """Retain a worker until native finished; never destroy its running QThread early."""
        if self.worker is not None:
            return
        self.operation, self.pending_result, self.pending_error = operation, None, None
        self.operation_started = time.monotonic()
        idle=self.idle_link if operation!='tune' else None
        if idle is not None:self.idle_link=None
        def perform():
            if idle is not None:backend.close_idle_control(idle)
            return function()
        worker = self.worker = Worker(perform, self)
        worker.completed.connect(self._completed, QtCore.Qt.QueuedConnection)
        worker.failed.connect(self._failed, QtCore.Qt.QueuedConnection)
        worker.notice.connect(self._notice, QtCore.Qt.QueuedConnection)
        worker.finished.connect(self._thread_finished, QtCore.Qt.QueuedConnection)
        self.i18n.bind(
            self.phase.setText,
            {'connect': message("Connecting and reading device…"), 'apply': message("Applying profile and checking readback…"), 'rx': message("Preparing RX…"), 'tune': message("Tuning RX and checking readback…"), 'warm': message("Warming control channel (RX idle)…"), 'release': message("Checking device state and releasing control…"), 'disconnect': message("Disconnecting and checking device state…")}[operation],
        )
        if operation == "rx":
            self.session.event = worker.notice.emit
        self._controls(); worker.start()

    @QtCore.Slot(object)
    def _completed(self, result):
        """Save terminal results and wait for actual worker exit before updating controls."""
        self.pending_result = result

    @QtCore.Slot(object)
    def _failed(self, error):
        """Keep displayable exceptions without credentials or raw logs."""
        self.pending_error = error

    @QtCore.Slot(str, object)
    def _notice(self, kind, value):
        """Emit phase changes only; plot timers read a bounded cache."""
        if kind=='retuning':
            for curves in self.plots.values():
                for curve in curves:curve.clear()
            for image in self.waterfall_images.values():image.clear()
            self.i18n.bind(self.phase.setText, message("Tuning to {p0:.6f} MHz…", p0=value['frequency_hz'] / 1000000.0))
            self._controls();return
        if kind=='tuned':
            self.state['info']=value['info'];self._show_radio()
            self.waterfall_history.clear();self.waterfall_seen.clear();self.waterfall_frequency.clear()
            for item in self.waterfall_images.values():item.clear()
            self.last_frames.clear();self.view_keys.clear()
            self.i18n.bind(self.phase.setText, message("RX resumed · Tuning control {p0:.2f}s · Previous frequency data separated", p0=value['gap_seconds']))
            self._controls()
            QtCore.QTimer.singleShot(0,self._apply_pending_frequency)
            return
        if kind == "ready":
            if value.get("tx"):
                self.i18n.bind(self.phase.setText, message("TX active · Timed shutdown · Stop TX in the sidebar also stops RX"))
                self._controls();return
            text = {'live': message("Live RX · Online tuning available; confirmed frequency kept after stop"), 'sweep': message("Sweeping · Segments captured at different times; original center restored after stop")}
            self.i18n.bind(self.phase.setText, text.get(self.session.mode, message("Receiving · Stops and restores at timeout")))
            self._controls()

    @QtCore.Slot()
    def _thread_finished(self):
        """Require thread, buffer and independent recovery completion before restart or close."""
        operation, result, error = self.operation, self.pending_result, self.pending_error
        self.worker.deleteLater(); self.worker = None
        self.operation = None
        if error is not None:
            self.pending_frequency = None
            if operation=='tune' and self.idle_link is not None and self.idle_link.done.is_set():self.idle_link=None
            if isinstance(error,backend.IdleControlRecoveryError):self.recovery_failed=True
            if operation not in ("rx","warm"):
                self.connection = None; self.state = None
            self.i18n.bind(self.phase.setText, message("Failed: ") + str(error)[:400])
        elif operation=='warm':
            self.warm_link=result
            self.i18n.bind(self.phase.setText, message("RX idle · Control channel ready"))
        elif operation in ("connect", "apply", "tune"):
            self._release_warm('rx' if operation=='tune' else None)
            self.warm_link=result.pop('_warm_link',None)
            self.idle_link=result.pop('_idle_link',None)
            self.state = result
            self.recovery_failed = False
            self.rf_mode.blockSignals(True)
            self.rf_mode.setCurrentIndex(self.rf_mode.findData(profile_mode(result['info']['active'])))
            self.rf_mode.model().item(1).setEnabled(any(profile_mode(p)=='shared-lo2' for p in result['available']))
            self.rf_mode.blockSignals(False)
            self._mode_profiles_changed()
            self.profiles.setCurrentIndex(self.profiles.findData(result['info']['active']))
            self._show_actual()
            self._show_radio()
            if operation=='connect':self.sections['connection'].set_expanded(False)
            control = message("Control ready (exclusive) · No RX / TX") if self.idle_link is not None else message("RX idle")
            count=len({logical_profile(p) for p in result['available']})
            self.i18n.bind(self.phase.setText, message("Connected · {p0} profiles · {p1}", p0=count, p1=control))
            if operation == "tune":
                self.i18n.bind(
                    self.phase.setText,
                    message("RX center applied and verified · {p0:.2f}s · Ready for RX", p0=result.get('tune_seconds', 0)),
                )
        elif operation=='disconnect':self._disconnect()
        elif operation == "rx":
            self.last_result = result
            result['ui_metrics']=dict(self.ui_metrics)
            if hasattr(self.session,'output') and self.session.output.is_dir():
                save_json(self.session.output/'gui-metrics.json',self.ui_metrics)
            if result.get('final_radio'):
                self.state['info']['radio']=result['final_radio'];self._show_radio()
            self.recovery_failed = not result.get("recovery_confirmed", False)
            if result["status"] == "PASS_SWEEP_SESSION":
                self.i18n.bind(
                    self.phase.setText,
                    message("Sweep ended · {p0} complete rounds / {p1} segments · Original center restored", p0=result['rounds'], p1=result['segments']),
                )
                self._show_radio()
            elif result["status"] == "PASS_TX_SESSION":
                self.i18n.bind(self.phase.setText, message("TX stopped · RF off and settings restored · Assess RF quality using IQ evidence"))
            elif result["status"] == "PASS_RX_SESSION" and result.get('recording'):
                qualification = message("No lost samples verified within this recording window") if result['recording'].get('absolute_continuity_proven') else message("Device continuity not verified")
                self.i18n.bind(
                    self.phase.setText,
                    (message("IQ files fully written · ") + qualification + ' · ' + str(self.session.output / 'recording')),
                )
            elif result["status"] == "PASS_RX_SESSION":
                self.i18n.bind(
                    self.phase.setText,
                    (
                        message("RX ended · Restored · Normal IQ lost sample count unknown")
                        if self.session.pattern == 'normal'
                        else message("Digital RX ended · Restored · Review statistics and rate")
                    ),
                )
            else:
                self.i18n.bind(
                    self.phase.setText,
                    (
                        (
                            message("RX failed: ")
                            + result.get('error', result.get('recording_error', result.get('recovery_error', message("See session records"))))[:240]
                        )
                        + (message(" · Original settings restored") if result.get('recovery_confirmed') else message(" · Recovery unconfirmed"))
                    ),
                )
            self._refresh()
        self._controls()
        if operation == 'tune' and error is None:
            QtCore.QTimer.singleShot(0,self._apply_pending_frequency)
        if self.closing_requested:
            if self.recovery_failed:
                self.closing_requested = False
                self.i18n.bind(
                    self.phase.setText,
                    (
                        message("Device recovery unconfirmed; window remains open. Reconnect to check. Records: ")
                        + str(getattr(self.session, 'output', self.output_root))
                    ),
                )
            else:
                QtCore.QTimer.singleShot(0, self.close)
            return
        if (operation=='rx' and not self.closing_requested and not self.recovery_failed
                and self.state and self.state.get('actual',{}).get('identity')):
            QtCore.QTimer.singleShot(0,self._warm_next)
            QtCore.QTimer.singleShot(0,lambda:self._warm_next('tx'))
        elif (operation in ('connect','apply','tune') and not self.closing_requested
              and self.state and self.state.get('actual',{}).get('identity')):
            QtCore.QTimer.singleShot(0,lambda:self._warm_next('tx'))
            if self.warm_link is None:QtCore.QTimer.singleShot(0,self._warm_next)

    def _release_warm(self, kind=None):
        """Close unused warmup channels by EOF; they own no hardware session or buffer."""
        for name in (('warm_link','warm_tx_link') if kind is None
                     else ('warm_tx_link',) if kind=='tx' else ('warm_link',)):
            link=getattr(self,name)
            if link is not None:link.close(stop=False);setattr(self,name,None)

    def _warm_next(self, kind='rx'):
        """Warm one RX or TX control channel while idle, discarding late results after close/reconnect.

        Warmup grants no hardware permit and does not compete with active operations.
        """
        worker_name,link_name=('warm_tx_worker','warm_tx_link') if kind=='tx' else ('warm_worker','warm_link')
        if (getattr(self,worker_name) is not None or self.worker is not None
                or self.connection is None or self.closing_requested):return
        if kind=='rx' and self.idle_link is not None:return
        connection,info=self.connection,self.state['info']
        cached=getattr(self,link_name)
        if (cached is not None and not cached.done.is_set() and not cached.active
                and cached.info['boot_id']==info['boot_id'] and cached.info['configuration_id']==info['configuration_id']):return
        self._release_warm(kind)
        prepare=warm_tx_control if kind=='tx' else backend.warm_control
        worker=Worker(lambda:prepare(connection,info),self);setattr(self,worker_name,worker)
        def completed(link):
            if connection is self.connection and not self.closing_requested:
                self._release_warm(kind);setattr(self,link_name,link)
            else:link.close(stop=False)
        def finished():
            worker.deleteLater();setattr(self,worker_name,None)
            if self.closing_requested and self.worker is None:QtCore.QTimer.singleShot(0,self.close)
        worker.completed.connect(completed)
        worker.failed.connect(lambda error:None)  # A warmup miss leaves the complete cold path available.
        worker.finished.connect(finished);worker.start()

    def _show_actual(self):
        """Show actual rates, bandwidths and profile identity, separating selection from applied state."""
        info = self.state["info"]
        rows = "  |  ".join(f"RX{v['channel']}：{v['sample_rate_hz']/1e6:g} MSPS / {v['rf_bandwidth_hz']/1e6:g} MHz" for v in info["parameters"]["rx"])
        self.i18n.bind(
            self.actual.setText,
            message(
                "Active profile: {p0}  ·  Configuration ID {p1}  ·  API {p2}\n{p3}",
                p0=info['active'],
                p1=info['configuration_id'],
                p2=info['api'],
                p3=rows,
            ),
        )
        self.i18n.bind(
            self.actual.setToolTip,
            message("boot_id: {p0}\nKernel: {p1}", p0=info['boot_id'], p1=self.state['actual']['kernel']),
        )

    def _show_radio(self):
        """Build controls from actual profile LO groups; distinguish readback from physical validation."""
        radio = self.state["info"]["radio"]
        values = radio["rx_center_frequency_hz"]
        self.i18n.bind(
            self.center_actual.setText,
            (
                (
                    message("Driver readback: ")
                    + join_messages(
                          ' / ',
                          (message('RX{p0} {p1:.6f} MHz', p0=c, p1=values[str(c)] / 1000000.0) for c in (1, 2)),
                      )
                )
                + message(" · Calibration policy {p0}", p0=radio.get('initial_calibrations', 'unknown'))
            ),
        )
        self.i18n.bind(
            self.center_actual.setToolTip,
            message("Preserves device calibration policy. Off does not recalibrate large jumps; carrier readback does not prove RF accuracy or image rejection. Auto follows driver rules and rolls back on failure."),
        )
        self._group_changed()

    def _rx_lo_group(self):
        """Infer the tuning group from selected RX and actual sharing, without a redundant selector."""
        if not self.state:return None
        channels=self.channels.currentData() or (1,)
        return next((g for g in self.state['info']['radio']['groups'] if channels[0] in g['channels']),None)

    def _group_changed(self, *_):
        """Display the selected group's actual frequency without writing the device."""
        group = self._rx_lo_group()
        if self.state and group:
            hz = self.state["info"]["radio"]["rx_center_frequency_hz"][str(group["channels"][0])]
            self.center.setValue(hz / 1e6)
        if self.state and group:
            self.i18n.bind(self.frequency_readout.setText, message('{p0:,.6f} MHz', p0=hz / 1000000.0))
        if group:
            names=' + '.join(f'RX{c}' for c in group['channels'])
            shared = message(" · Shared LO, RX/TX tune together") if group['tx_shared'] else message(" · Shared LO, both RX channels tune together") if len(group['channels']) > 1 else ''
            self.i18n.bind(self.center.setToolTip, names + shared + message(" · Point at a digit and scroll, or enter MHz and press Enter"))
        self._controls()

    def _tune_center(self):
        """Freeze group and integer Hz; update actual frequency only after a successful transaction."""
        if self.operation == 'tune' or (self.operation == 'rx' and self.session is not None
                                      and getattr(self.session,'epoch_stop',None) is not None
                                      and self.session.epoch_stop.is_set() and not self.session.stopping.is_set()):
            self.pending_frequency = self.center.value()
            self.i18n.bind(self.phase.setText, message("Tuning · Next target {p0:.6f} MHz", p0=self.pending_frequency))
            return
        if not self.center_button.isEnabled():
            return
        try:
            hz = mhz_to_hz(f"{self.center.value():.6f}")
            channels = self._rx_lo_group()["channels"]
            if self.operation=='rx':
                self.session.request_tune(channels,hz);self._controls();return
            target = self.output_root / datetime.now().strftime("tune-%Y%m%d-%H%M%S-%f")
            prepared=self.idle_link or self.warm_link
            self.warm_link=None
            self._launch("tune", lambda: backend.tune_rx_idle(self.connection,self.state,channels,hz,target,prepared,True))
        except Exception as error:
            self.i18n.bind(self.phase.setText, message("Cannot tune: ") + str(error)); self._controls()

    def _apply_pending_frequency(self):
        """Execute only the latest queued target; discard pending requests on failure, stop or close."""
        value, self.pending_frequency = self.pending_frequency, None
        if value is not None and not self.recovery_failed and not self.closing_requested:
            self.center.setValue(value)
            self._tune_center()

    def _axis_changed(self, *_):
        """Label old IQ using its captured LO identity rather than a later requested frequency."""
        self.last_frames = {}
        self._refresh()

    def _connect(self):
        """Recheck identity and actual idle state; invalidate old connection state on failure."""
        try:
            self._release_warm()
            self.connection = self._new_connection()
            output=self.output_root/('control-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            self._launch("connect", lambda: backend.inspect(self.connection,None,True,output))
        except Exception as error:
            self.i18n.bind(self.phase.setText, message("Cannot connect: ") + str(error)); self.connection = None; self.state = None; self._controls()

    def _disconnect(self):
        """Release logical connection references only after workers have stopped."""
        if self.worker is not None:
            return
        if self.idle_link is not None:
            self._launch('disconnect',lambda:None);return
        self._release_warm()
        self.connection = None; self.state = None; self.session = None
        self.profiles.clear()
        self.i18n.bind(self.actual.setText, message("Disconnected [msg-1f0ac695]"))
        self.i18n.bind(self.frequency_readout.setText, '— MHz')
        self.i18n.bind(self.center_actual.setText, message("RX LO not read back yet"))
        self.i18n.bind(self.phase.setText, message("Disconnected [msg-1f0ac695]"))
        self._controls()

    def _selected_profile(self):
        """Display logical combinations while sending complete device-provided profile IDs."""
        return self.profiles.currentData() or self.profiles.currentText()

    def _mode_profiles_changed(self, *_):
        """Regroup existing items for selection; only Apply changes device configuration."""
        if not self.state:return
        selected=self.profiles.currentText()
        self.profiles.blockSignals(True);self.profiles.clear()
        for label,name in mode_profiles(self.state['available'],self.rf_mode.currentData()):
            self.profiles.addItem(label,name)
        self.profiles.setCurrentText(logical_profile(selected))
        self.profiles.blockSignals(False)
        self._controls()

    def _apply(self):
        """Apply a stopped-session preset through IIO and independently query actual parameters."""
        if self.state and self.worker is None:
            self._release_warm()
            selected = self._selected_profile()
            output=self.output_root/('control-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            self._launch("apply", lambda: backend.inspect(self.connection, selected,True,output))

    def _start(self):
        """Freeze profile, channels and limits; never create a continuous buffer above the budget."""
        if not self.start_button.isEnabled():
            return
        try:
            self.session=None;self.operation_started=time.monotonic()
            self.last_result = None; self.last_frames = {};self.view_keys={}
            self._reset_peaks()
            self.ui_metrics=dict(refresh_count=0,max_refresh_seconds=0.0,first_visible_seconds=None,plotted_frames=0,last_visible_seconds=None)
            self.waterfall_seen = {}; self.waterfall_history = {}; self.waterfall_frequency = {}
            for item in self.waterfall_images.values(): item.clear()
            selected_channels = self.channels.currentData()
            for channel, curves in self.plots.items():
                for curve in curves:
                    curve.clear()
                self.tabs.setTabEnabled(channel - 1, channel in selected_channels)
            self.tabs.setCurrentIndex(selected_channels[0] - 1)
            self.i18n.bind(self.statistics.setText, message("Waiting for the first complete IQ block…"))
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            sweep=self.mode.currentData()=="sweep"
            self.tabs.setTabEnabled(2,sweep)
            if sweep:
                channel=selected_channels[0]
                actual=next(v for v in self.state['info']['parameters']['rx'] if v['channel']==channel)
                plan=SweepPlan(mhz_to_hz(f"{self.sweep_start.value():.6f}"),mhz_to_hz(f"{self.sweep_stop.value():.6f}"),
                    actual['sample_rate_hz'],actual['rf_bandwidth_hz'],self.sweep_fft.currentData(),
                    self.sweep_averages.value(),self.sweep_settle.value(),self.sweep_repeat.isChecked())
                self.session=SweepSession(self.connection,self.state['info'],channel,plan,self.output_root/stamp)
                self.sweep_last_frame=None;self.sweep_last_round=0;self.sweep_history=None
                self.sweep_curve.clear();self.sweep_max_curve.clear();self.sweep_image.clear();self.tabs.setCurrentIndex(2)
            else:
                prepared=self.idle_link if self.mode.currentData() in ('live','continuous') and self.idle_link is not None else self.warm_link
                self.session = backend.RxSession(self.connection, self.state["info"], self.channels.currentData(),
                                                 self.mode.currentData(), self.pattern.currentData(), self.seconds.value(), self.output_root / stamp,prepared_link=prepared, recording=self.record_next)
                if self.mode.currentData() in ("live","continuous"):
                    self.warm_link=None
                    if prepared is self.idle_link:self.idle_link=None
            self._launch("rx", self.session.run)
        except Exception as error:
            self.i18n.bind(self.phase.setText, message("Cannot start: ") + str(error)); self._controls()

    def _wide_sweep_profile(self):
        """Apply an explicitly selected wideband preview through the existing transaction."""
        if self.worker is not None or self.state is None:return
        name='61p44msps-40mhz'
        if name not in self.state['available']:
            self.i18n.bind(self.phase.setText, message("Device has no 61.44 MSPS / 40 MHz profile"))
            return
        self.sweep_start.setValue(50);self.sweep_stop.setValue(5800)
        self.sweep_fft.setCurrentText('2048');self.sweep_averages.setValue(1);self.sweep_settle.setValue(2)
        self.rf_mode.setCurrentIndex(self.rf_mode.findData('independent'))
        self.profiles.setCurrentIndex(self.profiles.findData(name))
        self._apply()

    def _record(self):
        """Record from a new frequency-locked session, never relabel display cache as full history."""
        if self.worker is not None:
            self._stop()
            return
        if self.mode.currentData() not in ('live','continuous'):
            self.i18n.bind(self.phase.setText, message("Select Live RX to record; use snapshot export for a single capture"))
            return
        self.record_next = True
        try:
            self._start()
        finally:
            self.record_next = False

    def _start_tx(self):
        """Freeze TX parameters and run in a worker; one owner manages optional RX monitoring."""
        if self.worker is not None or self.state is None or self.recovery_failed:return
        try:
            if self._selected_profile()!=self.state['info']['active']:raise ValueError("Apply the selected profile first")
            plan=self.tx_panel.plan()
            channels=self.channels.currentData() if self.tx_panel.monitor.isChecked() else ()
            stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-tx'
            self.session=TxSession(self.connection,self.state['info'],channels,plan,self.output_root/stamp,
                                   prepared_link=self.warm_tx_link)
            self.warm_tx_link=None
            self.pattern.setCurrentIndex(self.pattern.findData('normal'))
            self.mode.setCurrentIndex(self.mode.findData('continuous'))
            self.seconds.setValue(plan.seconds)
            self.last_frames={};self.view_keys={};self.waterfall_seen={};self.waterfall_history={};self.waterfall_frequency={}
            self.ui_metrics=dict(refresh_count=0,max_refresh_seconds=0.,first_visible_seconds=None,plotted_frames=0,last_visible_seconds=None)
            for channel,curves in self.plots.items():
                for curve in curves:curve.clear()
                self.tabs.setTabEnabled(channel-1,channel in channels)
            for item in self.waterfall_images.values():item.clear()
            self.tabs.setTabEnabled(2,False)
            if channels:self.tabs.setCurrentIndex(channels[0]-1)
            self.i18n.bind(self.statistics.setText, message("Preparing TX; waiting for RX IQ…") if channels else message("TX only; no RX monitoring"))
            summary=self.session.tx_request
            offsets=[f"TX{ch}: {v.get('offset_hz',0)/1000:.6f} kHz" for ch,v in summary['waveforms'].items() if v['kind']=='tone']
            self.i18n.bind(
                self.tx_panel.summary.setText,
                (
                    (message("Actual coherent tone offset ") + join_messages(' / ', offsets))
                    if offsets
                    else message("Preloaded loop IQ file; user is responsible for spectral content")
                ),
            )
            self._launch('rx',self.session.run)
            self.i18n.bind(self.phase.setText, message("Preloading TX waveform and checking RF settings…"))
            QtCore.QTimer.singleShot(0,lambda:self.controls_dock.widget().ensureWidgetVisible(self.tx_panel.action))
        except Exception as error:
            self.i18n.bind(self.phase.setText, message("Cannot start TX: ") + str(error));self._controls()

    def _stop(self):
        """Request stop and keep configuration disabled until recovery is confirmed."""
        if self.session and self.operation == "rx":
            self.pending_frequency = None
            self.session.stop(); self.stop_button.setEnabled(False); self.tx_panel.stop.setEnabled(False)
            self.i18n.bind(self.phase.setText, message("Stopping RX/TX and restoring device…"))
            self._controls()

    def _controls(self, *_):
        """Centralize control availability for budgets, connection, unapplied selection and activity."""
        busy, connected = self.worker is not None, self.state is not None and self.connection is not None
        for widget in (self.host, self.connect_button):
            widget.setEnabled(not busy)
        self.disconnect_button.setEnabled(connected and not busy)
        for widget in (self.rf_mode, self.profiles, self.channels, self.mode, self.pattern):
            widget.setEnabled(connected and not busy)
        for widget in (self.acquisition_mode,self.stop_condition):widget.setEnabled(connected and not busy)
        common=connected and profile_mode(self.state['info']['active'])=='shared-lo2'
        self.mode.model().item(3).setEnabled(not common)
        self.acquisition_mode.model().item(2).setEnabled(not common)
        if common and self.mode.currentData()=='sweep':self.mode.setCurrentIndex(2)
        mode=self.mode.currentData()
        for widget in (self.acquisition_mode,self.stop_condition):widget.blockSignals(True)
        self.acquisition_mode.setCurrentIndex(self.acquisition_mode.findData('live' if mode in ('live','continuous') else mode))
        if mode in ('live','continuous'):self.stop_condition.setCurrentIndex(self.stop_condition.findData(mode))
        for widget in (self.acquisition_mode,self.stop_condition):widget.blockSignals(False)
        self.config_form.setRowVisible(self.stop_condition,mode in ('live','continuous'))
        self.seconds.setEnabled(connected and not busy and self.mode.currentData() == "continuous")
        sweep=self.mode.currentData()=="sweep"
        self.i18n.bind(self.start_button.setText, message("Start sweep") if sweep else message("Start RX"))
        self.i18n.bind(
            self.save_button.setText,
            (message("Save spectrum…") if self.session is not None and self.session.mode == 'sweep' else message("Save IQ…")),
        )
        self.sections['sweep'].setVisible(sweep)
        self.config_form.setRowVisible(self.seconds,self.mode.currentData()=='continuous')
        self.sweep_box.setEnabled(connected and not busy and sweep)
        self.sweep_wide.setEnabled(connected and not busy and '61p44msps-40mhz' in (self.state or {}).get('available',[]))
        if connected and sweep:
            actual=next(v for v in self.state['info']['parameters']['rx'] if v['channel']==self.channels.currentData()[0])
            try:
                estimate=SweepPlan(int(self.sweep_start.value()*1e6),int(self.sweep_stop.value()*1e6),actual['sample_rate_hz'],actual['rf_bandwidth_hz'])
                count=len(estimate.centers())
                self.i18n.bind(
                    self.sweep_estimate.setText,
                    message(
                        "Bandwidth {p0:g} MHz · {p1} segments · Settle total {p2:.1f}s, plus tuning and capture",
                        p0=(actual['rf_bandwidth_hz'] / 1000000.0),
                        p1=count,
                        p2=(count * self.sweep_settle.value() / 1000),
                    ),
                )
            except ValueError as error:self.i18n.bind(self.sweep_estimate.setText, str(error) + message("; use a wideband panorama profile"))
        self.channels.model().item(2).setEnabled(not sweep)
        if sweep and self.channels.currentIndex()==2:self.channels.setCurrentIndex(0)
        if sweep and self.pattern.currentIndex()!=0:self.pattern.setCurrentIndex(0)
        self.pattern.setEnabled(connected and not busy and not sweep)
        mismatch = connected and self._selected_profile() != self.state["info"]["active"]
        self.apply_button.setEnabled(connected and not busy and mismatch)
        allowed = True
        if connected:
            payload = budget(self.state["info"], self.channels.currentData())
            allowed = payload.allowed or self.mode.currentData() in ("snapshot","sweep")
            wording = message("Within budget; does not imply continuous acquisition acceptance for this profile") if payload.allowed else message("Over continuous budget; lower sample rate / channel count, or use a finite snapshot")
            self.i18n.bind(
                self.budget_label.setText,
                (
                    message(
                        "Input {p0:g} MB/s / IIO budget {p1:g} MB/s  ·  {p2}",
                        p0=(payload.required / 1000000.0),
                        p1=(payload.limit / 1000000.0),
                        p2=wording,
                    )
                    + (message("  ·  Selected profile not applied") if mismatch else '')
                ),
            )
            self.budget_label.setStyleSheet("color:#64cbb0" if payload.allowed else "color:#ef9b71")
        tx_running=busy and self.operation=='rx' and isinstance(self.session,TxSession)
        self.sections['tx'].header.setEnabled(not tx_running)
        if tx_running:self.sections['tx'].set_expanded(True)
        self.tx_panel.set_radio(self.state['info']['radio'] if connected else None)
        self.tx_panel.set_available(connected,not busy and not mismatch and not self.recovery_failed,
                                    tx_running and not self.session.stopping.is_set())
        group = self._rx_lo_group()
        editable = connected and group is not None and group["editable"]
        online = (busy and self.operation=='rx' and self.session is not None
                  and hasattr(self.session,'can_tune') and self.session.can_tune())
        tuning_allowed = not busy or online
        queued_tuning = self.operation == 'tune' or (self.operation == 'rx' and self.session is not None
                         and getattr(self.session,'epoch_stop',None) is not None and self.session.epoch_stop.is_set()
                         and not self.session.stopping.is_set())
        self.center.setEnabled(editable and (tuning_allowed or queued_tuning))
        changed = False
        if editable:
            target = mhz_to_hz(f"{self.center.value():.6f}")
            changed = any(self.state["info"]["radio"]["rx_center_frequency_hz"][str(c)] != target for c in group["channels"])
        self.center_button.setEnabled(editable and tuning_allowed and not mismatch and changed and not self.recovery_failed)
        self.rf_axis.setEnabled(self.session is not None and self.session.pattern == "normal" and self.session.mode!="sweep")
        self.start_button.setEnabled(connected and not busy and not mismatch and allowed and not self.recovery_failed)
        self.stop_button.setEnabled(busy and self.operation == "rx" and self.session is not None
                                    and not isinstance(self.session,TxSession) and not self.session.stopping.is_set())
        self.save_button.setEnabled(self.session is not None and bool(self.session.snapshot()[0]))
        receiving = busy and self.operation == 'rx' and not tx_running
        stopping = receiving and self.session is not None and self.session.stopping.is_set()
        set_action(
            self.rx_action,
            ('busy' if stopping else 'stop' if receiving else 'play'),
            (message("Stopping and restoring") if stopping else message("Stop RX") if receiving else message("Start RX")),
            ('#ef7777' if receiving else '#62dcba'),
            i18n=self.i18n,
        )
        self.rx_action.setEnabled(self.start_button.isEnabled() or self.stop_button.isEnabled())
        recording = receiving and getattr(self.session, 'recording', False)
        set_action(
            self.record_action,
            ('stop' if recording else 'record'),
            (message("Stop recording and drain files") if recording else message("Record raw IQ (check DMA overflow and complete file writes; keep partial files on failure)")),
            '#ef7777',
            i18n=self.i18n,
        )
        self.record_action.setEnabled((recording and self.stop_button.isEnabled()) or
                                      (self.start_button.isEnabled() and self.mode.currentData() in ('live','continuous')))
        self.snapshot_action.setEnabled(self.save_button.isEnabled())
        set_action(
            self.snapshot_action,
            'save',
            (message("Export current sweep spectrum") if sweep else message("Export latest IQ snapshot")),
            i18n=self.i18n,
        )

    def _refresh(self, *_):
        """Plot visible channels only; hidden channels remain checked and preserve axis state."""
        if self.session is None:return
        if self.session.mode=='sweep':self._refresh_sweep();return
        if getattr(self.session,'epoch_stop',None) is not None and self.session.epoch_stop.is_set():return
        started=time.monotonic()
        raw,stats,frames=self.session.snapshot()
        visible=self.tabs.currentIndex()+1
        for channel,frame in frames.items():
            radio=self.session.info.get('radio')
            hz=frame.get('center_hz',radio['rx_center_frequency_hz'][str(channel)] if radio else None)
            absolute=self.rf_axis.isChecked() and self.session.pattern=='normal' and hz is not None
            # Append one bounded history row; hidden channels avoid full image/curve conversion.
            if self.waterfall_seen.get(channel) is not frame:
                self._update_waterfall(channel,frame,hz/1e6 if absolute else 0,absolute,render=False)
            if channel!=visible or self.last_frames.get(channel) is frame:continue
            i,q,fft=self.plots[channel]
            i.setData(frame['time_us'],frame['i']);q.setData(frame['time_us'],frame['q'])
            x=frame['frequency_mhz']+hz/1e6 if absolute else frame['frequency_mhz']
            fft.setData(x,frame['dbfs'])
            values = frame['dbfs']
            peak_index = int(np.nanargmax(values))
            self.peak_markers[channel].setData([x[peak_index]], [values[peak_index]])
            self.peak_markers[channel].setVisible(self.show_peak.isChecked())
            self.peak_labels[channel].setVisible(self.show_peak.isChecked())
            self.i18n.bind(
                self.peak_labels[channel].setText,
                message('{p0:.6f} MHz · {p1:.1f} dBFS', p0=x[peak_index], p1=values[peak_index]),
            )
            self.peak_labels[channel].setPos(float(x[peak_index]), float(values[peak_index]))
            hold_key = (frame.get('epoch',0), hz, len(values), absolute)
            old_key, old_values = self.hold_values.get(channel, (None, None))
            held = values.copy() if old_key != hold_key else np.maximum(old_values, values)
            self.hold_values[channel] = (hold_key, held)
            if self.show_hold.isChecked(): self.hold_curves[channel].setData(x, held)
            key=(frame.get('epoch',0),absolute,hz,len(x),float(x[0]),float(x[-1]))
            if self.view_keys.get(channel)!=key:
                self.fft_widgets[channel].setXRange(float(x[0]),float(x[-1]),padding=0)
                self.i18n.axis(
                    self.fft_widgets[channel],
                    'bottom',
                    (message("RF frequency") if absolute else message("Baseband frequency")),
                    units='MHz',
                )
                text=f" · LO {hz/1e6:.6f} MHz" if hz is not None else ''
                self.i18n.bind(self.fft_widgets[channel].setTitle, message("RX{p0} · Spectrum", p0=channel))
                self.i18n.bind(self.fft_widgets[channel].setToolTip, message("Capture time{p0} · Hann / DC removed; digital amplitude, not calibrated dBm", p0=text))
                wave=self.wave_widgets[channel];wave.setXRange(float(frame['time_us'][0]),float(frame['time_us'][-1]),padding=0)
                lo=float(min(frame['i'].min(),frame['q'].min()));hi=float(max(frame['i'].max(),frame['q'].max()))
                wave.setYRange(lo,hi if hi>lo else lo+1,padding=.05)
                self.view_keys[channel]=key
            self._render_waterfall(channel,frame,hz/1e6 if absolute else 0,absolute)
            self.last_frames[channel]=frame
            self.ui_metrics['plotted_frames']+=1
            self.ui_metrics['last_visible_seconds']=time.monotonic()-self.operation_started
            if self.ui_metrics['first_visible_seconds'] is None:
                self.ui_metrics['first_visible_seconds']=time.monotonic()-self.operation_started
        if time.monotonic()-self.last_stats_refresh>=.25:
            rows=[]
            for channel,value in sorted(stats.items()):
                tail = message("Lost sample count unknown") if self.session.pattern == 'normal' else message("Errors {p0}/{p1}/{p2} (mod 65536)", p0=value['within_errors'], p1=value['boundary_errors'], p2=value['iq_errors'])
                rows.append(message("RX{p0}  {p1:,} IQ\n{p2:.2f} MB/s · {p3:.1f}s · Timeouts {p4} · {p5}", p0=channel, p1=value['samples'], p2=value.get('bytes_per_second', 0) / 1000000.0, p3=value.get('elapsed', 0), p4=value['timeouts'], p5=tail))
            if rows:self.i18n.bind(self.statistics.setText, join_messages('\n', rows))
            self.last_stats_refresh=time.monotonic()
        self.save_button.setEnabled(bool(raw))
        self.snapshot_action.setEnabled(bool(raw))
        self.ui_metrics['refresh_count']+=1
        self.ui_metrics['max_refresh_seconds']=max(self.ui_metrics['max_refresh_seconds'],time.monotonic()-started)

    def _refresh_sweep(self):
        """Keep bounded current/peak-hold sweeps; only completed rounds enter the waterfall."""
        frame,complete,rounds,segments=self.session.snapshot()
        if frame is None:return
        if frame is not self.sweep_last_frame:
            x=frame['frequency_mhz'];y=frame['dbfs']
            self.sweep_curve.setData(x,y,connect='finite');self.sweep_max_curve.setData(x,frame['max_hold'],connect='finite')
            valid=np.isfinite(y)
            peak = message("No valid frequency bins")
            if valid.any():
                index=np.nanargmax(y);peak = message("Peak {p0:.6f} MHz / {p1:.2f} dBFS", p0=x[index], p1=y[index])
            self.i18n.bind(
                self.statistics.setText,
                message(
                    "Complete rounds {p0} · Total segments {p1}\nCurrent round {p2}/{p3} segments · {p4}\nSegments are not simultaneous; LO/DC spurs not corrected, not calibrated dBm",
                    p0=rounds,
                    p1=segments,
                    p2=frame['segment'],
                    p3=frame['segment_count'],
                    p4=peak,
                ),
            )
            self.i18n.bind(
                self.sweep_plot.setTitle,
                message(
                    "Segmented sweep · Round {p0} {p1}",
                    p0=frame['round'],
                    p1=(message("complete") if frame['complete'] else message("partial")),
                ),
            )
            if not frame['complete'] and 'mean_segment_seconds' in frame:
                remaining=(frame['segment_count']-frame['segment'])*frame['mean_segment_seconds']
                self.i18n.bind(
                    self.phase.setText,
                    message(
                        "Sweep {p0}/{p1} segments · {p2:.0f} ms/segment · About {p3:.1f}s left",
                        p0=frame['segment'],
                        p1=frame['segment_count'],
                        p2=(frame['mean_segment_seconds'] * 1000),
                        p3=remaining,
                    ),
                )
            if self.worker is not None:
                self.i18n.bind(self.frequency_readout.setText, message('{p0:,.6f} MHz', p0=frame['center_hz'] / 1000000.0))
                self.i18n.bind(
                    self.center_actual.setText,
                    message(
                        "Sweep readback: RX{p0} LO {p1:.6f} MHz · Shared RX tunes with the LO",
                        p0=self.session.channel,
                        p1=(frame['center_hz'] / 1000000.0),
                    ),
                )
            self.sweep_last_frame=frame
        if complete and complete['round']!=self.sweep_last_round:
            y=complete['dbfs'];stride=max(1,(len(y)+511)//512);bins=len(y)//stride
            compressed=np.nanmax(y[:bins*stride].reshape(bins,stride),axis=1)
            if self.sweep_history is None:self.sweep_history=np.full((240,bins),-200,dtype=np.float32)
            self.sweep_history[:-1]=self.sweep_history[1:];self.sweep_history[-1]=compressed
            self.sweep_image.setImage(self.sweep_history,autoLevels=False,levels=(self.waterfall_floor.value(),self.waterfall_ceiling.value()))
            x=complete['frequency_mhz'];self.sweep_image.setRect(QtCore.QRectF(float(x[0]),-240,float(x[-1]-x[0]),240))
            self.sweep_last_round=complete['round']
            self.sweep_waterfall.setYRange(-min(240,max(10,complete['round'])),0,padding=0)
        self.save_button.setEnabled(True)

    def _update_waterfall(self, channel, frame, offset, absolute, render=True):
        """Keep 240 display rows and at most 512 bins; display peak aggregation is not full recording."""
        frequency = frame["frequency_mhz"]
        values = frame["dbfs"]
        stride = max(1, (len(values) + 511) // 512)
        bins = len(values) // stride
        compressed = values[:bins * stride].reshape(bins, stride).max(axis=1)
        x = frequency[:bins * stride].reshape(bins, stride).mean(axis=1)
        if channel not in self.waterfall_history or self.waterfall_history[channel].shape[1] != bins or not np.array_equal(self.waterfall_frequency[channel], x):
            self.waterfall_history[channel] = np.full((240, bins), -200, dtype=np.float32)
            self.waterfall_frequency[channel] = x
            self.waterfall_seen.pop(channel, None)
        if self.waterfall_seen.get(channel) is not frame:
            history = self.waterfall_history[channel]
            history[:-1] = history[1:]; history[-1] = compressed
            self.waterfall_seen[channel] = frame
        if render:self._render_waterfall(channel,frame,offset,absolute)

    def _render_waterfall(self,channel,frame,offset,absolute):
        """Convert float32 history to an image only when visible, using the matching frequency epoch."""
        x=self.waterfall_frequency[channel]
        image=self.waterfall_images[channel]
        image.setImage(self.waterfall_history[channel],autoLevels=False,
                       levels=(self.waterfall_floor.value(),self.waterfall_ceiling.value()))
        dx=float(x[1]-x[0]) if len(x)>1 else 1.0
        geometry=(float(x[0])+offset-dx/2,dx*len(x),absolute)
        if self.waterfall_geometry.get(channel)!=geometry:
            image.setRect(QtCore.QRectF(geometry[0],-240,geometry[1],240))
            self.i18n.axis(
                self.waterfall_widgets[channel],
                'bottom',
                (message("RF frequency") if absolute else message("Baseband frequency")),
                units='MHz',
            )
            self.waterfall_geometry[channel]=geometry

    def _waterfall_levels_changed(self, *_):
        """Brightness changes display only; require upper bound above lower bound."""
        if self.waterfall_floor.value() >= self.waterfall_ceiling.value():
            self.waterfall_ceiling.setValue(self.waterfall_floor.value() + 1)
        for item in self.waterfall_images.values():
            item.setLevels((self.waterfall_floor.value(), self.waterfall_ceiling.value()))
        self.sweep_image.setLevels((self.waterfall_floor.value(),self.waterfall_ceiling.value()))

    def _reset_view(self):
        """Restore complete FFT and bounded waveform views without changing acquisition."""
        self.view_keys.clear();self.last_frames.clear()
        for widget in self.fft_widgets.values():widget.setYRange(-160,0,padding=0)
        self._refresh()
        self.sweep_plot.getViewBox().autoRange()

    def _cursor_moved(self, channel, args):
        """Inspect existing plot data with the cursor without implicit tuning or relabeling."""
        widget = self.fft_widgets[channel]
        point = args[0]
        if widget.sceneBoundingRect().contains(point):
            position = widget.plotItem.vb.mapSceneToView(point)
            self.cursor_lines[channel].setPos(position.x()); self.cursor_lines[channel].show()
            label = 'RF' if self.rf_axis.isChecked() and self.session and (self.session.pattern == 'normal') else message("Baseband")
            self.cursor_label.show()
            self.i18n.bind(
                self.cursor_label.setText,
                message(
                    "RX{p0} cursor: {p1} {p2:.6f} MHz · {p3:.2f} dBFS (digital amplitude)",
                    p0=channel,
                    p1=label,
                    p2=position.x(),
                    p3=position.y(),
                ),
            )

    def export(self, path: Path):
        """Save the latest complete block and session identity, without claiming full-stream recording."""
        if self.session is None:
            raise ValueError("No IQ data yet")
        if self.session.mode=="sweep":return self.session.export(path)
        if hasattr(self.session,'snapshot_with_info'):
            raw,stats,_,info,epoch=self.session.snapshot_with_info()
        else:
            raw,stats,_=self.session.snapshot();info=self.session.info;epoch=0
        if not raw:
            raise ValueError("No complete IQ block yet")
        return save_snapshot(path, raw, {"info": info, "epoch": epoch, "channels": self.session.channels,
                                       "mode": self.session.mode, "source": self.session.pattern,
                                       "statistics": stats, "session_result": self.last_result,
                                       "session_directory": str(self.session.output)})

    def _save(self):
        """Choose a directory and create a timestamped new snapshot without replacing old files."""
        root = QtWidgets.QFileDialog.getExistingDirectory(self, self.i18n.text("Choose IQ parent directory"), str(self.output_root))
        if root:
            try:
                path = Path(root) / datetime.now().strftime("h102-iq-%Y%m%d-%H%M%S-%f")
                self.export(path)
                self.i18n.bind(self.phase.setText, message("IQ saved: ") + str(path))
            except Exception as error:
                self.i18n.bind(self.phase.setText, message("Save failed: ") + str(error))

    def closeEvent(self, event):
        """Request stop before close; report failed recovery and preserve running workers."""
        if self.worker is not None:
            self.closing_requested = True
            self._stop()
            self.i18n.bind(self.phase.setText, message("Waiting for operation completion and device recovery before closing…"))
            event.ignore()
            return
        if self.idle_link is not None:
            self.closing_requested=True;self._launch('release',lambda:None);event.ignore();return
        self._release_warm()
        if self.warm_worker is not None or self.warm_tx_worker is not None:
            self.closing_requested=True
            self.i18n.bind(self.phase.setText, message("Closing idle control connections…"));event.ignore();return
        self.connection = None
        self.timer.stop(); event.accept()

# End of file: gui.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
