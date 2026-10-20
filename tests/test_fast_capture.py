"""Test fast-sweep stitching, control boundaries and recording rejection offline."""
import base64
import hashlib
from pathlib import Path
import numpy as np
import pytest
from h102_iio_demo.board_capture import grid_cells, OverflowGuard
from h102_iio_demo.sweep import SweepPlan, Accumulator
from h102_iio_demo.recorder import IQRecorder
from h102_iio_demo.board_session import validate_sweep_batch


@pytest.mark.parametrize('stop', [5039000000, 5800000000])
def test_native_grid_matches_full_fft_and_preserves_peak(stop):
    plan=SweepPlan(50000000 if stop==5800000000 else 5038000000,stop,61440000,40000000)
    offsets=np.fft.fftshift(np.fft.fftfreq(plan.fft_points,1/plan.sample_rate_hz))
    power=np.full(plan.fft_points,1e-12);power[4701]=.25
    center=plan.centers()[len(plan.centers())//2]
    expected=Accumulator(plan);expected.add(center,offsets,power)
    payload=vars(plan).copy();payload['grid_size']=len(plan.grid())
    cells=grid_cells(power,center,payload)
    actual=Accumulator(plan)
    actual.add_cells(cells['grid_first'],np.frombuffer(base64.b64decode(cells['power_f32le_b64']),dtype='<f4'))
    assert np.allclose(expected.dbfs(),actual.dbfs(),equal_nan=True,atol=1e-5)


def test_wrong_bit_rejected_before_mapping(monkeypatch):
    class HW:
        devices={'axi-adrv9002-rx-lpc':Path('/nonexistent/iio:device0')}
    def forbidden(*a,**kw):raise AssertionError('MMIO should not open')
    monkeypatch.setattr('builtins.open',forbidden)
    with pytest.raises(RuntimeError,match='UNKNOWN_ABI'):OverflowGuard(HW(),{'boot_pins':{}})


def test_batch_rejects_different_rate_and_unbounded_count():
    p=SweepPlan(50000000,5800000000,61440000,40000000)
    plan=vars(p).copy();plan['grid_size']=len(p.grid())
    request={'channels':[1],'actual':{'parameters':{'rx':[dict(channel=1,sample_rate_hz=61440000,rf_bandwidth_hz=40000000)]}}}
    validate_sweep_batch(plan,p.centers()[:32],request)
    with pytest.raises(ValueError):validate_sweep_batch(plan,p.centers()[:33],request)
    plan['sample_rate_hz']=40000000
    with pytest.raises(ValueError):validate_sweep_batch(plan,p.centers()[:1],request)


@pytest.mark.parametrize('guard', [{},dict(stage='ended',passed=True,checked_before_buffer_destroy=True,initial_status=0,final_status=4,cleared_ns=1,armed_ns=2,checked_ns=3)])
def test_recording_without_clean_device_window_stays_partial(tmp_path,guard):
    data=b'\0'*4096;r=IQRecorder(tmp_path/'rec',(1,),{},1,require_device_guard=True)
    r.submit(1,data)
    with pytest.raises(RuntimeError):r.finish(True,[dict(channel=1,bytes=len(data),stream_sha256=hashlib.sha256(data).hexdigest(),device_guard=guard)])
    assert (tmp_path/'rec/rx1.iq.partial').exists()
    assert not r.report['absolute_continuity_proven']
