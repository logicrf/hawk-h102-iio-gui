"""Test unique visible start/stop, a narrow panel, digit steps and peak display."""
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets, QtTest
from test_gui import app, fixture_state
from h102_iio_demo.gui import MainWindow
from h102_iio_demo.instrument_widgets import FrequencyDial


def test_icon_actions_and_narrow_sidebar(app,tmp_path):
    w=MainWindow('offline',tmp_path/'keys',tmp_path/'out')
    w.resize(1000,780); w.show()
    w.profiles.addItem('8msps-1mhz-'+ 'long-profile-name-'*5)
    for section in w.sections.values():section.set_expanded(True)
    QtTest.QTest.qWait(60)
    assert w.start_button.isHidden() and w.stop_button.isHidden() and w.center_button.isHidden()
    assert w.rx_action.isVisible() and w.record_action.isVisible()
    assert w.tx_panel.start.isHidden() and w.tx_panel.stop.isHidden()
    assert w.controls_dock.widget().horizontalScrollBar().maximum()==0
    assert w.center.isVisible() and w.frequency_readout.isHidden()
    w.close()


def test_tx_action_dispatches_stop_once_running(app,tmp_path):
    w=MainWindow('offline',tmp_path/'keys',tmp_path/'out')
    calls=[]
    w.tx_panel.start.clicked.disconnect();w.tx_panel.stop.clicked.disconnect()
    w.tx_panel.start.clicked.connect(lambda:calls.append('start'))
    w.tx_panel.stop.clicked.connect(lambda:calls.append('stop'))
    w.tx_panel.set_available(True,True,False);w.tx_panel.action.click()
    w.tx_panel.set_available(True,False,True);w.tx_panel.action.click()
    w.tx_panel.set_available(True,False,False);w.tx_panel.action.click()
    assert calls==['start','stop']
    w.close()


def test_frequency_wheel_digit_and_debounce(app):
    dial=FrequencyDial();dial.resize(500,60);dial.setValue(2400);dial.show()
    calls=[];dial.commitRequested.connect(lambda:calls.append(dial.value()))
    editor=dial.lineEdit()
    # Scroll the MHz units digit twice and require one coalesced request.
    font=QtGui.QFontMetrics(editor.font())
    editor.setAlignment(QtCore.Qt.AlignLeft)
    editor.setCursorPosition(0)
    x=editor.contentsRect().x()+font.horizontalAdvance('240')+2
    pos=dial.mapFrom(editor,QtCore.QPoint(x,editor.height()//2))
    for _ in range(2):
        event=QtGui.QWheelEvent(QtCore.QPointF(pos),QtCore.QPointF(dial.mapToGlobal(pos)),
            QtCore.QPoint(),QtCore.QPoint(0,120),QtCore.Qt.NoButton,QtCore.Qt.NoModifier,
            QtCore.Qt.NoScrollPhase,False)
        dial.wheelEvent(event)
    QtTest.QTest.qWait(320)
    assert dial.value()==2402 and calls==[2402]
    dial.close()


def test_display_controls_and_automatic_rx_group(app,tmp_path):
    w=MainWindow('offline',tmp_path/'keys',tmp_path/'out')
    w.state=fixture_state()
    assert not hasattr(w,'lo_group')
    w._show_radio()
    assert w._rx_lo_group()['channels']==[1,2]
    assert w.rf_axis.parentWidget() is w.show_grid.parentWidget()
    w.state['info']['radio']['groups']=[dict(channels=[1],editable=True),dict(channels=[2],editable=True)]
    w.channels.setCurrentIndex(1)
    assert w._rx_lo_group()['channels']==[2]
    w.state=None;w.close()
