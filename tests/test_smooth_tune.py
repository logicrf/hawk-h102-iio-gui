"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_smooth_tune.py
@brief      Test tuning epochs, export consistency, visible plotting and zoom protection.
@details    Offline fixtures never access the board or grant hardware qualification.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.4.0
@date       2026-10-13
"""
from copy import deepcopy
from pathlib import Path
from threading import Event
import numpy as np
import pytest
from PySide6 import QtWidgets
from h102_iio_demo.backend import Connection,RxSession
from h102_iio_demo.gui import MainWindow
from h102_iio_demo.model import display_frame
from test_gui import fixture_state


def test_live_tune_group_and_one_pending_epoch(tmp_path):
    info=fixture_state()['info']
    for row in info['parameters']['rx']:row['sample_rate_hz']=8_000_000
    session=RxSession(Connection('offline'),info,(1,2),'live','normal',None,tmp_path/'data')
    class Link:
        def permitted(self):return True
    session.link=Link()
    with pytest.raises(ValueError):session.request_tune([1],2_401_000_000)
    with pytest.raises(ValueError):session.request_tune([1,2],6_000_000_001)
    session.request_tune([1,2],2_401_000_000)
    assert session.epoch_stop.is_set() and session.pending_tune['frequency_hz']==2_401_000_000
    assert session.info['radio']['rx_center_frequency_hz']['1']==2_400_000_000
    with pytest.raises(RuntimeError):session.request_tune([1,2],2_402_000_000)
    assert not session.can_tune()


def test_visible_only_plot_and_persistent_zoom(tmp_path):
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow('offline',tmp_path/'keys',tmp_path/'out')
    info=fixture_state()['info'];raw=np.zeros((8192,2),dtype='<i2').tobytes()
    frames={c:dict(display_frame(raw,8_000_000),epoch=0,center_hz=2_400_000_000) for c in (1,2)}
    class Session:
        mode='live';pattern='normal';stopping=Event()
        def snapshot(self):return {1:raw,2:raw},{},frames
    w.session=Session();w.session.info=info
    w._refresh()
    assert w.plots[1][2].xData is not None and w.plots[2][2].xData is None
    assert 2 in w.waterfall_history  # Retain bounded hidden-channel frames without redundant conversion.
    w.fft_widgets[1].setXRange(-.5,.5,padding=0)
    frames[1]=dict(frames[1]);w._refresh()
    assert w.fft_widgets[1].viewRange()[0]==pytest.approx([-.5,.5])
    w.tabs.setCurrentIndex(1);w._refresh()
    assert w.plots[2][2].xData is not None
    w.session=None;w.close()


def test_atomic_export_uses_frame_epoch_not_later_session_info(tmp_path):
    import json
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow('offline',tmp_path/'keys',tmp_path/'out')
    info=fixture_state()['info'];captured=deepcopy(info)
    info['radio']['rx_center_frequency_hz']['1']=2_450_000_000
    raw=np.zeros((8192,2),dtype='<i2').tobytes()
    class Session:
        mode='live';pattern='normal';channels=(1,);output=tmp_path/'session'
        def snapshot_with_info(self):return {1:raw},{},{},captured,3
    w.session=Session();w.session.info=info
    w.export(tmp_path/'export')
    record=json.loads((tmp_path/'export/snapshot.json').read_text())
    assert record['metadata']['epoch']==3
    assert record['metadata']['info']['radio']['rx_center_frequency_hz']['1']==2_400_000_000
    w.session=None;w.close()

# End of file: test_smooth_tune.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
