"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_tx_warm.py
@brief      Test TX warm-channel ownership, invalidation and fresh request binding.
@details    Model connections without hardware to exercise pre-start rejection.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.6.0
@date       2026-10-13
"""
import pytest
from h102_iio_demo import tx_backend
from h102_iio_demo.backend import Connection
from h102_iio_demo.tx_model import TxPlan
from test_tx import info


@pytest.mark.parametrize('case',['current','expired','different-boot','rx-link'])
def test_prepared_tx_rebinds_current_waveform_or_falls_back_before_hardware(tmp_path,monkeypatch,case):
    """Do not reuse old waveforms or grant TX from invalid, foreign-boot or RX warm channels."""
    class Link(tx_backend.TxLink):
        def __init__(self,*args):
            super().__init__(*args);self.closed=False
        def start(self):
            self.observed=self.expected()
            raise RuntimeError('OFFLINE_STOP_BEFORE_HARDWARE')
        def close(self,stop=True):
            self.closed=True
            return dict(returncode=1,records={'post.json':dict(passed=True,rf_off=True,
                settings_restored=True,configuration_unchanged=True)})
    monkeypatch.setattr(tx_backend,'TxLink',Link)
    value=info();value.update(boot_id='current',configuration_id=19)
    value['parameters']['rx']=[dict(channel=c,sample_rate_hz=8_000_000,rf_bandwidth_hz=4_000_000) for c in (1,2)]
    c=Connection('offline')
    candidate=Link(c,dict(value),(1,),None,{'old_request':True},{1:b'old-waveform'})
    if case=='expired':candidate.done.set()
    if case=='different-boot':candidate.info['boot_id']='previous'
    if case=='rx-link':candidate=object()
    s=tx_backend.TxSession(c,value,(),TxPlan((2,),2400000000,30,1,offset_hz=-375000),
                           tmp_path/'session',prepared_link=candidate)
    result=s.run()
    assert result['status']=='FAIL_TX_SESSION' and result['error']=='OFFLINE_STOP_BEFORE_HARDWARE'
    assert result['prepared_control_used']==(case=='current')
    assert s.link.observed['tx']['channels']==[2]
    assert s.link.observed['tx']['attenuation_db']==30
    assert s.link.observed['tx']['waveforms']['2']['offset_hz']==-375000
    assert set(s.link.observed['raw'])=={'2'} and s.link.closed
    if case in ('expired','different-boot'):assert candidate.closed


def test_closing_window_waits_for_pending_tx_warm_and_closes_late_link(tmp_path,monkeypatch):
    """Keep close responsive during warmup and release late channels before destroying threads."""
    from threading import Event
    import time
    from PySide6 import QtWidgets,QtTest
    from h102_iio_demo import gui
    from test_gui import fixture_state
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    started,release=Event(),Event()
    class Link:
        closed=False
        def close(self,stop=True):self.closed=True
    link=Link()
    def prepare(*args):
        started.set();release.wait(3);return link
    monkeypatch.setattr(gui,'warm_tx_control',prepare)
    w=gui.MainWindow('offline',tmp_path/'key',tmp_path/'out');w.show()
    w.connection=Connection('offline');w.state=fixture_state()
    w._warm_next('tx');assert started.wait(1)
    t0=time.monotonic();w.close();assert time.monotonic()-t0<.2
    assert w.closing_requested and w.isVisible()
    release.set()
    until=time.monotonic()+3
    while w.warm_tx_worker is not None and time.monotonic()<until:QtTest.QTest.qWait(10)
    app.processEvents()
    assert w.warm_tx_worker is None and link.closed and not w.isVisible()


# End of file: test_tx_warm.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
