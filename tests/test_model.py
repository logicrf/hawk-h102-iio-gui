"""Test user data contracts and known inputs using offline cases only."""
import hashlib
import json
import numpy as np
import pytest
from h102_iio_demo.model import budget, decode_iq, RampChecker, display_frame, save_snapshot


def info(fs1, fs2=None):
    """Use asymmetric channels to catch accidental use of channel 1's sample rate."""
    return {"parameters": {"rx": [{"channel": 1, "sample_rate_hz": fs1}, {"channel": 2, "sample_rate_hz": fs2 or fs1}]}}


@pytest.mark.parametrize("fs,channels,allowed,required", [
    (20_000_000, (1,), False, 80_000_000),
    (20_000_000, (1,2), False, 160_000_000),
    (8_000_000, (1,2), True, 64_000_000),
    (16_000_000, (2,), True, 64_000_000),
    (16_000_001, (1,), False, 64_000_004),
    (40_000_000, (1,), False, 160_000_000)])
def test_budget(fs, channels, allowed, required):
    b = budget(info(fs), channels)
    assert (b.allowed, b.required) == (allowed, required)


def test_selected_actual_channel_and_invalid():
    assert budget(info(40_000_000, 8_000_000), (2,)).required == 32_000_000
    for invalid in ((), (1,1), (3,)):
        with pytest.raises(ValueError):
            budget(info(1), invalid)


def test_signed_little_endian_layout():
    raw = bytes.fromhex('0080ff7fff ff0000'.replace(' ', ''))
    assert decode_iq(raw).tolist() == [[-32768,32767],[-1,0]]
    assert not decode_iq(raw).flags.writeable
    with pytest.raises(ValueError): decode_iq(raw[:-1])


def ramp(start, n):
    a = (np.arange(start, start+n, dtype=np.uint32) & 65535).astype('<u2')
    return np.column_stack((a,a)).tobytes()


def test_ramp_wrap_and_cross_block_gap():
    checker = RampChecker()
    assert checker.check(ramp(65530,10))['within_errors'] == 0
    assert checker.check(ramp(65540,10))['boundary_errors'] == 0
    failure = checker.check(ramp(65552,10))
    assert failure['boundary_errors'] == 2
    pair = np.frombuffer(ramp(10,10),dtype='<u2').copy(); pair[5] += 1
    assert RampChecker().check(pair.tobytes())['iq_errors'] == 1


def test_known_tone_axis_and_dbfs():
    n, fs, frequency = 8192, 8_000_000, 1_000_000
    phase = 2*np.pi*frequency*np.arange(n)/fs
    a = np.column_stack((np.cos(phase),np.sin(phase)))*16384
    frame = display_frame(a.astype('<i2').tobytes(),fs)
    index = np.argmax(frame['dbfs'])
    assert frame['frequency_mhz'][index] == pytest.approx(1)
    assert frame['dbfs'][index] == pytest.approx(-6.0206,abs=.01)
    assert len(frame['i']) == 2048
    assert frame['time_us'][1] == pytest.approx(.125)


def test_export_identity_integrity_and_no_overwrite(tmp_path):
    raw = ramp(0,1024)
    p = tmp_path/'new'
    result = save_snapshot(p,{2:raw},{'configuration_id':17,'source':'ramp16'})
    assert (p/'rx2.bin').read_bytes() == raw
    assert result['channels']['2']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert json.loads((p/'snapshot.json').read_text())['metadata']['configuration_id'] == 17
    with pytest.raises(FileExistsError): save_snapshot(p,{2:raw},{})
