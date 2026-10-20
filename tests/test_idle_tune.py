"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_idle_tune.py
@brief      Test idle-tuning commit, recovery evidence and channel ownership.
@details    Use in-memory controls without network, IQ buffers or RF access.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.6.0
@date       2026-10-13
"""
from copy import deepcopy
from threading import Event
import json
import pytest
from h102_iio_demo import backend
from test_gui import fixture_state


@pytest.mark.parametrize('case',['warm','cold','failed-post','failed-tune'])
def test_idle_tune_commits_only_confirmed_radio_and_closes_control(tmp_path,monkeypatch,case):
    """Require independent post for changed state; preserve inputs and failure receipts."""
    state=fixture_state();original=deepcopy(state);c=backend.Connection('offline')
    class Link:
        def __init__(self,connection,info,channels,mode,pattern,board):
            self.connection,self.info,self.channels,self.mode,self.pattern=connection,info,channels,mode,pattern
            self.done=Event();self.active=False;self.directory='/fixture/private';self.timings={};self.closed=False
        def start(self):
            assert self.mode=='idle_tune' and self.pattern=='normal';self.active=True
        def tune(self,frequency,channels):
            assert list(self.channels)==channels==[1,2]
            if case=='failed-tune':raise RuntimeError('INJECTED_TUNE_FAILURE')
            self.radio=deepcopy(self.info['radio'])
            for channel in channels:self.radio['rx_center_frequency_hz'][str(channel)]=frequency
            return dict(radio=self.radio)
        def close(self):
            self.closed=True
            return dict(returncode=1 if case=='failed-tune' else 0,records={'post.json':dict(passed=case!='failed-post',
                configuration_unchanged=True,settings_restored=True,frequency_retained=True,
                radio=getattr(self,'radio',self.info['radio']))})
    monkeypatch.setattr(backend,'SessionLink',Link)
    candidate=Link(c,state['info'],(1,),'live','normal',None) if case!='cold' else None
    if case in ('failed-post','failed-tune'):
        with pytest.raises(RuntimeError):backend.tune_rx_idle(c,state,[1,2],150_000_000,tmp_path/'out',candidate)
        receipt=json.loads((tmp_path/'out/result.json').read_text())
        assert receipt['status']=='FAIL_IDLE_TUNE'
        if case=='failed-tune':assert receipt['recovery_confirmed']
    else:
        result=backend.tune_rx_idle(c,state,[1,2],150_000_000,tmp_path/'out',candidate)
        assert result['info']['radio']['rx_center_frequency_hz']=={'1':150_000_000,'2':150_000_000}
        receipt=json.loads((tmp_path/'out/result.json').read_text());assert receipt['status']=='PASS_IDLE_TUNE'
    assert state==original and not receipt['data_buffers_created'] and not receipt['RF_TX']
    if candidate:assert candidate.closed


@pytest.mark.parametrize('save_fails',[False,True])
def test_repeated_idle_tune_keeps_owner_until_explicit_release(tmp_path,monkeypatch,save_fails):
    """Further commands do not restart the owner or masquerade as completed recovery."""
    state=fixture_state();c=backend.Connection('offline')
    class Link:
        def __init__(self,connection,info,channels,mode,pattern,board):
            self.connection,self.info,self.channels,self.mode,self.pattern=connection,info,channels,mode,pattern
            self.done=Event();self.active=False;self.directory='/fixture/private';self.timings={};self.starts=0;self.closed=False
        def start(self):self.starts+=1;self.active=True
        def tune(self,frequency,channels):
            self.radio=deepcopy(self.info['radio'])
            for channel in channels:self.radio['rx_center_frequency_hz'][str(channel)]=frequency
            return dict(radio=self.radio)
        def close(self):
            self.closed=True
            return dict(returncode=0,records={'post.json':dict(passed=True,configuration_unchanged=True,
                settings_restored=True,frequency_retained=True,radio=self.radio)})
    monkeypatch.setattr(backend,'SessionLink',Link)
    if save_fails:
        original_save=backend.save_json;created=[]
        original_init=Link.__init__
        def init(self,*args):original_init(self,*args);created.append(self)
        monkeypatch.setattr(Link,'__init__',init)
        failed=[False]
        def save(path,value):
            if not failed[0] and path.name=='result.json' and value.get('status')=='PASS_IDLE_TUNE_APPLIED':
                failed[0]=True;raise OSError('injected save failure')
            return original_save(path,value)
        monkeypatch.setattr(backend,'save_json',save)
        with pytest.raises(RuntimeError):backend.tune_rx_idle(c,state,[1,2],150_000_000,tmp_path/'first',keep_control=True)
        assert created[0].closed
        return
    first=backend.tune_rx_idle(c,state,[1,2],150_000_000,tmp_path/'first',keep_control=True)
    link=first['_idle_link']
    second=backend.tune_rx_idle(c,first,[1,2],151_000_000,tmp_path/'second',link,True)
    assert second['_idle_link'] is link and link.starts==1 and not link.closed
    receipt=json.loads((tmp_path/'second/result.json').read_text())
    assert receipt['status']=='PASS_IDLE_TUNE_APPLIED' and receipt['recovery_confirmed'] is None
    assert receipt['recovery_state']=='DEFERRED_ACTIVE_CONTROL'
    backend.close_idle_control(link)
    assert link.closed and (tmp_path/'first/control-end.json').is_file()


@pytest.mark.parametrize('failed',[False,True])
def test_dependent_operation_waits_for_idle_control_release(tmp_path,monkeypatch,failed):
    """Failed independent recovery blocks later operations; wait inside the worker."""
    from PySide6 import QtWidgets,QtTest
    from h102_iio_demo import gui
    import time
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    events=[]
    def close(link):
        time.sleep(.05);events.append('closed')
        if failed:raise backend.IdleControlRecoveryError('injected unconfirmed post')
    monkeypatch.setattr(backend,'close_idle_control',close)
    w=gui.MainWindow('offline',tmp_path/'keys',tmp_path/'out');w.idle_link=object()
    def apply():events.append('applied');return fixture_state()
    t0=time.monotonic();w._launch('apply',apply);assert time.monotonic()-t0<.2
    until=time.monotonic()+3
    while w.worker is not None and time.monotonic()<until:QtTest.QTest.qWait(10)
    assert events==(['closed'] if failed else ['closed','applied'])
    if failed:assert w.recovery_failed and w.state is None
    w.close();app.processEvents()


# End of file: test_idle_tune.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
