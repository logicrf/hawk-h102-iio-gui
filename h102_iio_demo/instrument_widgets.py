"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       instrument_widgets.py
@brief      Provide instrument-style digit tuning and frameless icon controls.
@details    Use on the Qt thread; wheel events emit coalesced requests without hardware access.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.7.0
@date       2026-10-15
"""
from PySide6 import QtCore, QtGui, QtWidgets


class InstrumentCheckBox(QtWidgets.QCheckBox):
    """Retain keyboard/accessibility behavior and draw explicit high-contrast checkbox marks."""
    def paintEvent(self, event):
        """Draw within the native indicator geometry, supporting high DPI and disabled state."""
        super().paintEvent(event)
        if not self.isChecked():return
        option=QtWidgets.QStyleOptionButton();self.initStyleOption(option)
        rect=self.style().subElementRect(QtWidgets.QStyle.SE_CheckBoxIndicator,option,self)
        painter=QtGui.QPainter(self);painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen=QtGui.QPen(QtGui.QColor('#f4fffb' if self.isEnabled() else '#93aba9'),2)
        pen.setCapStyle(QtCore.Qt.RoundCap);pen.setJoinStyle(QtCore.Qt.RoundJoin);painter.setPen(pen)
        points=[QtCore.QPointF(rect.x()+rect.width()*x,rect.y()+rect.height()*y)
                for x,y in ((.23,.5),(.43,.71),(.78,.28))]
        painter.drawPolyline(QtGui.QPolygonF(points));painter.end()


def action_icon(kind, color):
    """Draw common actions as vectors, avoiding missing font glyphs and platform button differences."""
    pixmap = QtGui.QPixmap(32, 32)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtGui.QPen(QtGui.QColor(color), 2))
    painter.setBrush(QtGui.QColor(color))
    if kind == 'play':
        painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(10, 6), QtCore.QPointF(26, 16), QtCore.QPointF(10, 26)]))
    elif kind == 'stop':
        painter.drawRoundedRect(7, 7, 18, 18, 2, 2)
    elif kind == 'record':
        painter.drawEllipse(7, 7, 18, 18)
    elif kind == 'save':
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(6, 5, 20, 22, 2, 2)
        painter.drawRect(11, 5, 10, 8)
        painter.drawRect(11, 19, 10, 8)
    else:
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawArc(6, 6, 20, 20, 30 * 16, 280 * 16)
    painter.end()
    return QtGui.QIcon(pixmap)


def icon_button(parent=None):
    """Create a borderless button that retains focus and hover feedback."""
    button = QtWidgets.QToolButton(parent)
    button.setFixedSize(42, 42)
    button.setIconSize(QtCore.QSize(28, 28))
    button.setStyleSheet('QToolButton{border:0;background:transparent;border-radius:6px;}'
                        'QToolButton:hover{background:#253642;}'
                        'QToolButton:focus{border:1px solid #62dcba;}')
    return button


def set_action(button, kind, label, color='#62dcba', *, i18n=None):
    """Update icon, accessibility name and tooltip together rather than using color alone."""
    button.setIcon(action_icon(kind, color))
    if i18n is None:
        button.setToolTip(label)
        button.setAccessibleName(label)
    else:
        i18n.bind(button.setToolTip, label)
        i18n.bind(button.setAccessibleName, label)


class FrequencyDial(QtWidgets.QDoubleSpinBox):
    """Tune MHz digits by pointer position and coalesce wheel changes for 250 ms."""
    commitRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDecimals(6)
        self.setRange(30, 6000)
        self.setSuffix(' MHz')
        self.setKeyboardTracking(False)
        self.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.setMinimumWidth(290)
        self.setStyleSheet("font-family:'DejaVu Sans Mono';font-size:30px;color:#62dcba;border:0;background:transparent;")
        self.setToolTip("Point at a digit and scroll to tune; enter MHz and press Enter. Device readback is shown below.")
        self._debounce = QtCore.QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self.commitRequested)
        self.lineEdit().returnPressed.connect(self._enter)

    def _enter(self):
        self._debounce.stop()
        self.interpretText()
        self.commitRequested.emit()

    def wheelEvent(self, event):
        """Act only over digits so scrolling the page cannot accidentally retune."""
        if not self.isEnabled():
            event.ignore()
            return
        editor = self.lineEdit()
        point = editor.mapFrom(self, event.position().toPoint())
        index = editor.cursorPositionAt(point)
        text = editor.text()
        if index >= len(text) or not text[index].isdigit():
            event.ignore()
            return
        decimal = text.find('.')
        power = decimal - index - (1 if index < decimal else 0)
        steps = int(event.angleDelta().y() / 120)
        if steps:
            self.setValue(self.value() + steps * 10 ** power)
            editor.setCursorPosition(index)
            self._debounce.start()
        event.accept()


# End of file: instrument_widgets.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
