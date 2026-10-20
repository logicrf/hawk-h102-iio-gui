"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_refine.py
@brief      Test calibration policy, partial SDK failure and custom window operations.
@details    Use memory/Qt models without replacing real RF calibration or recovery evidence.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.5.0
@date       2026-10-13
"""
from pathlib import Path
import pytest
from PySide6 import QtCore,QtWidgets,QtGui
from h102_iio_demo.board_radio import apply_carrier,restore_carrier,validate_restore_scene
from h102_iio_demo.gui import MainWindow
from test_radio import Hardware


@pytest.mark.parametrize('policy',['off','auto'])
def test_keep_original_calibration_policy(policy):
    hw=Hardware();key=str(hw.phy/'initial_calibrations');hw.values[key]=policy;before=hw.settings()
    apply_carrier(hw,before,[1,2],100_000_000,lambda:None)
    assert all(value==policy for path,value in hw.writes if path==key)


def test_calibration_intermediate_lo_and_gain_snapshot_restores_and_rejects_foreign():
    class CalHardware(Hardware):
        """Model SDK calibration failure with temporary LO and zero-dB gain, preserving dB readback."""
        def write(self,path,value,*args):
            super().write(path,value,*args)
            if str(path).endswith('_hardwaregain'):self.values[str(path)]=value+' dB'
    hw=CalHardware();channels=[1,2]
    for i in (0,1):hw.values[str(hw.phy/f'in_voltage{i}_hardwaregain')]='34.000000 dB'
    before=hw.settings()
    for i in (0,1):
        hw.values[str(hw.alt('',i,''))]='2396600000'
        hw.values[str(hw.phy/f'in_voltage{i}_ensm_mode')]='calibrated'
        hw.values[str(hw.phy/f'in_voltage{i}_hardwaregain')]='0.000000 dB'
    current=hw.settings()
    with pytest.raises(RuntimeError):validate_restore_scene(hw,before,current,channels,100_000_000)
    validate_restore_scene(hw,before,current,channels,100_000_000,failed=current)
    foreign=dict(current);foreign[str(hw.alt('',2,''))]='2000000000'
    with pytest.raises(RuntimeError):validate_restore_scene(hw,before,foreign,channels,100_000_000,failed=foreign)
    changed=dict(current);changed[str(hw.phy/'gain')]='35'
    with pytest.raises(RuntimeError):validate_restore_scene(hw,before,changed,channels,100_000_000,failed=current)
    restore_carrier(hw,before,channels,lambda:None);assert hw.settings()==before
    assert hw.writes[0]==(str(hw.phy/'initial_calibrations'),'off')


def test_custom_window_logo_edges_and_scrollbar_do_not_lose_controls(tmp_path):
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow('offline',tmp_path/'keys',tmp_path/'out');w.show();app.processEvents()
    assert w.windowFlags()&QtCore.Qt.FramelessWindowHint
    assert w.chrome.minimize and w.chrome.maximize and w.chrome.close_button
    assert not w.findChildren(QtWidgets.QMenuBar)
    assert not w.chrome.logo.pixmap().isNull()
    assert w.chrome.edges(QtCore.QPoint(0,0))==QtCore.Qt.LeftEdge|QtCore.Qt.TopEdge
    assert not w.chrome.edges(QtCore.QPoint(100,100))
    # Expand all groups to inspect scrollbars; collapsed content need not force scrolling.
    for section in w.sections.values():section.set_expanded(True)
    app.processEvents()
    scroll=w.controls_dock.widget();bar=scroll.verticalScrollBar()
    assert bar.maximum()>bar.minimum()
    bar.setValue(bar.maximum());assert bar.value()==bar.maximum()
    edge=QtCore.QPoint(w.width()-3,100);global_pos=w.mapToGlobal(edge)
    local=bar.mapFromGlobal(global_pos)
    event=QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress,QtCore.QPointF(local),QtCore.QPointF(global_pos),
                           QtCore.Qt.LeftButton,QtCore.Qt.LeftButton,QtCore.Qt.NoModifier)
    assert not w.chrome.eventFilter(bar,event)
    assert w.chrome.drag is None
    w.close()

# End of file: test_refine.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
