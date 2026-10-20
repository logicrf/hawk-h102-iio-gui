"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_calibration_wait.py
@brief      Test automatic calibration budgets and bounded heartbeat supervision.
@details    Model time, watchdog notification and command replies without device/firmware access.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.6.0
@date       2026-10-13
"""
import json,time
from threading import Event,Lock
from queue import Queue
import pytest
from h102_iio_demo import board_session as native
from h102_iio_demo.session_link import SessionLink


@pytest.mark.parametrize('action',['tune','sweep_batch'])
def test_slow_auto_command_outlives_off_budget(monkeypatch,action):
    """Auto accepts a modeled 60-second reply while off retains the bounded 45-second limit."""
    class Reply:
        def __init__(self):self.elapsed=0
        def wait(self, seconds):
            self.elapsed+=10
            return self.elapsed>=60
    class Clock:
        def __init__(self):self.value=0
        def monotonic(self):self.value+=10;return self.value
    for policy,passed in [('auto',True),('off',False)]:
        clock=Clock();monkeypatch.setattr('h102_iio_demo.session_link.time.monotonic',clock.monotonic)
        link=object.__new__(SessionLink);link.info={'radio':{'initial_calibrations':policy}}
        link.lock=Lock();link.pending={};link.outgoing=Queue();link.done=Event();link.finished=None;link.error=None
        event=Reply()
        # Substitute only this module's command Event; done remains a real Event.
        monkeypatch.setattr('h102_iio_demo.session_link.Event',lambda:event)
        link.permitted=lambda:True
        # Model pending I/O replies while running the production _command implementation.
        original=link.outgoing.put_nowait
        def put(value):
            original(value);link.pending[value['id']]['result']={'permitted':True,'radio':{}}
        link.outgoing.put_nowait=put
        if passed:assert link._command({'action':action})['permitted']
        else:
            with pytest.raises(RuntimeError,match='TUNE_DEADLINE'):link._command({'action':action})
        assert not link.pending


@pytest.mark.parametrize('state',['fresh','expired','stop'])
def test_auto_watchdog_requires_fresh_heartbeat_and_no_stop(tmp_path,monkeypatch,state):
    """Renew only fresh control heartbeats without writing health.json or accessing hardware."""
    (tmp_path/'heartbeat.json').write_text(json.dumps({'updated_ns':time.monotonic_ns()-(20_000_000_000 if state=='expired' else 0)}))
    if state=='stop':(tmp_path/'stop').touch()
    calls=[];alarms=[]
    monkeypatch.setattr(native,'notify',calls.append);monkeypatch.setattr(native.signal,'alarm',alarms.append)
    if state=='expired':
        with pytest.raises(TimeoutError,match='HOST_HEARTBEAT_EXPIRED'):
            with native.supervised_tune(tmp_path,'auto'):time.sleep(.6)
    else:
        with native.supervised_tune(tmp_path,'auto'):time.sleep(.6)
    assert bool(calls)==(state=='fresh') and alarms==[180,0]
    assert not (tmp_path/'health.json').exists()

# End of file: test_calibration_wait.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
