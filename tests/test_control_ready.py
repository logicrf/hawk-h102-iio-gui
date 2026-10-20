"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_control_ready.py
@brief      Test persistence failures and independent recovery during control preparation.
@details    Model owner/file failures without live-device or RF qualification.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.6.0
@date       2026-10-13
"""
import json
import pytest
from h102_iio_demo import backend


class Link:
    """Model owner lifecycle to detect omitted exception cleanup."""
    instances = []

    def __init__(self, *args):
        self.active=False;self.ready={};self.directory='offline';self.timings={};self.closed=False
        self.instances.append(self)

    def start(self):
        """Model an authorized owner before any IQ buffer exists."""
        self.active=True

    def close(self, stop=True):
        """Model independent post completion without real-board claims."""
        self.closed=True
        return {'returncode':0,'records':{'post.json':{'passed':True,'configuration_unchanged':True,'settings_restored':True}}}


def test_prepare_ready_without_data_and_close(tmp_path,monkeypatch):
    monkeypatch.setattr(backend,'SessionLink',Link);monkeypatch.setattr(backend,'board_for',lambda _:None)
    link=backend.prepare_idle_control(None,{},[1],tmp_path/'ready')
    record=json.loads((tmp_path/'ready/result.json').read_text())
    assert record['status']=='PASS_IDLE_CONTROL_READY'
    assert record['data_buffers_created'] is False and record['RF_TX'] is False
    assert record['recovery_confirmed'] is None and not link.closed
    backend.close_idle_control(link)
    assert link.closed and (tmp_path/'ready/control-end.json').exists()


def test_save_failure_after_ready_still_closes_owner(tmp_path,monkeypatch):
    monkeypatch.setattr(backend,'SessionLink',Link);monkeypatch.setattr(backend,'board_for',lambda _:None)
    original=backend.save_json
    def save(path,value):
        """Inject disk-full after ready while allowing other evidence writes."""
        if path.name=='result.json':raise OSError('fixture disk full')
        original(path,value)
    monkeypatch.setattr(backend,'save_json',save)
    with pytest.raises(OSError,match='disk full'):
        backend.prepare_idle_control(None,{},[1],tmp_path/'failed')
    assert Link.instances[-1].closed
    assert (tmp_path/'failed/control-end.json').exists()

# End of file: test_control_ready.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
