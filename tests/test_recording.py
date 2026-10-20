"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_recording.py
@brief      Test bounded recording queues, pause recovery, failure retention and complete file bytes.
@details    Regular-file fault injection does not qualify board continuity; high-rate queue tests
            model admission speed only, retaining real writes, fsync and file readback.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.1.0
@date       2026-10-14
"""
import hashlib
import json
from threading import Event
import pytest
from h102_iio_demo.recorder import IQRecorder
from h102_iio_demo import recorder as recorder_module


def result(channel, data):
    """Model received-byte declarations without ADC or RF provenance."""
    return dict(channel=channel, bytes=len(data), stream_sha256=hashlib.sha256(data).hexdigest())


def test_dual_record_exact_bytes_and_no_false_continuity(tmp_path):
    recorder = IQRecorder(tmp_path/'record', (1,2), {}, 1)
    data = {1: bytes(range(256))*80, 2: b'\x01\x02\x03\x04'*8000}
    for c in (1,2):
        for offset in range(0,len(data[c]),1024):recorder.submit(c,data[c][offset:offset+1024])
    report=recorder.finish(True,[result(c,data[c]) for c in (1,2)])
    assert report['host_complete'] and not report['absolute_continuity_proven']
    for c in (1,2):assert (tmp_path/'record'/f'rx{c}.iq').read_bytes()==data[c]


def test_mismatch_never_renames_partial(tmp_path):
    recorder=IQRecorder(tmp_path/'record',(1,),{},1)
    recorder.submit(1,b'\0'*4096)
    with pytest.raises(RuntimeError,match='incomplete'):recorder.finish(True,[result(1,b'\0'*4092)])
    assert (tmp_path/'record/rx1.iq.partial').exists()
    assert json.loads((tmp_path/'record/recording.json').read_text())['status']=='INCOMPLETE'


def test_writer_os_error_reported_and_original_retained(tmp_path):
    recorder=IQRecorder(tmp_path/'record',(1,),{},1)
    recorder.files[1].close()
    recorder.submit(1,b'\0'*4096)
    with pytest.raises(RuntimeError,match='incomplete'):recorder.finish(True,[result(1,b'\0'*4096)])
    assert not (tmp_path/'record/rx1.iq').exists()
    assert recorder.error is not None


def test_queue_saturation_is_explicit_not_silent_drop(tmp_path,monkeypatch):
    gate=Event()
    original=IQRecorder._write
    def delayed(self):
        gate.wait(2)
        original(self)
    monkeypatch.setattr(IQRecorder,'_write',delayed)
    recorder=IQRecorder(tmp_path/'record',(1,),{},1)
    try:
        for _ in range(64):recorder.submit(1,b'\0'*4)
        with pytest.raises(RuntimeError,match='full'):recorder.submit(1,b'\0'*4)
    finally:
        gate.set()
        with pytest.raises(RuntimeError):recorder.finish(False,[])


def test_rate_scaled_buffer_covers_burst_and_retains_exact_data(tmp_path,monkeypatch):
    """Accept a burst exceeding the old 64-block limit while the real writer pauses, then verify files."""
    # Model admission speed unrelated to the queue; retain real write/fsync/readback behavior.
    monkeypatch.setattr(recorder_module,'probe_disk_rate',lambda directory:1_000_000_000)
    gate=Event(); original=IQRecorder._write
    def delayed(self):
        gate.wait(3); original(self)
    monkeypatch.setattr(IQRecorder,'_write',delayed)
    recorder=IQRecorder(tmp_path/'burst',(1,),{},64_000_000)
    block=bytes(range(256))*4096
    try:
        for _ in range(80):recorder.submit(1,block)
        assert recorder.queue.qsize()==80
        assert recorder.writer_metrics['max_buffer_bytes']<=256*1024**2
    finally:gate.set()
    data=block*80
    report=recorder.finish(True,[result(1,data)])
    assert (tmp_path/'burst/rx1.iq').read_bytes()==data
    assert report['writer_metrics']['queue_peak_blocks']==80
    assert report['writer_metrics']['write_calls']==80
    assert report['host_complete'] and not report['absolute_continuity_proven']


def test_scaled_buffer_still_fails_at_hard_bound(tmp_path,monkeypatch):
    """Keep a hard cap even with larger queues; never drop blocks or rename incomplete files."""
    monkeypatch.setattr(recorder_module,'probe_disk_rate',lambda directory:1_000_000_000)
    gate=Event(); original=IQRecorder._write
    def delayed(self):
        gate.wait(3); original(self)
    monkeypatch.setattr(IQRecorder,'_write',delayed)
    recorder=IQRecorder(tmp_path/'bounded',(1,),{},100_000_000)
    assert recorder.queue.maxsize==256
    try:
        for _ in range(256):recorder.submit(1,b'\0'*4)
        with pytest.raises(RuntimeError,match='full'):recorder.submit(1,b'\0'*4)
    finally:
        gate.set()
        with pytest.raises(RuntimeError):recorder.finish(False,[])
    assert (tmp_path/'bounded/rx1.iq.partial').exists()
    assert not (tmp_path/'bounded/rx1.iq').exists()


# End of file: test_recording.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
