"""Test heartbeat deadlines, sweep coverage, power stitching and Qt mode boundaries offline."""
import numpy as np
import pytest
from h102_iio_demo.board_session import heartbeat_age
from h102_iio_demo.sweep import SweepPlan,Accumulator,fft_power


def test_board_monotonic_heartbeat_expiry_and_future_rejected():
    assert heartbeat_age({'updated_ns':1_000_000_000},15_999_999_999)<15
    with pytest.raises(TimeoutError):heartbeat_age({'updated_ns':1_000_000_000},16_000_000_000)
    with pytest.raises(TimeoutError):heartbeat_age({'updated_ns':2_000_000_000},1_999_999_999)


def test_segment_coverage_and_partial_unknown():
    plan=SweepPlan(2_397_000_000,2_403_000_000,8_000_000,4_000_000)
    plan.validate();assert len(plan.centers())==2
    accumulator=Accumulator(plan)
    offsets=np.fft.fftshift(np.fft.fftfreq(8192,1/8_000_000))
    accumulator.add(plan.centers()[0],offsets,np.full(8192,.25))
    assert np.isnan(accumulator.dbfs()).any()
    for center in plan.centers()[1:]:accumulator.add(center,offsets,np.full(8192,.25))
    assert np.isfinite(accumulator.dbfs()).all()
    assert np.allclose(accumulator.dbfs(),10*np.log10(.25))
    assert len(SweepPlan(30_000_000,6_000_000_000,40_000_000,20_000_000).grid())==32768
    with pytest.raises(ValueError):SweepPlan(30_000_000,6_000_000_000,192000,50000).validate()


def test_overlap_averages_linear_power_and_hann_tone_frequency():
    plan=SweepPlan(2_399_000_000,2_401_000_000,8_000_000,4_000_000)
    offsets=np.fft.fftshift(np.fft.fftfreq(8192,1/8_000_000))
    accumulator=Accumulator(plan)
    accumulator.add(2_400_000_000,offsets,np.full(8192,.1))
    accumulator.add(2_400_000_000,offsets,np.full(8192,.9))
    assert np.allclose(accumulator.dbfs(),10*np.log10(.5))
    phase=2*np.pi*np.arange(65536)/16
    raw=(np.column_stack((np.cos(phase),np.sin(phase)))*16000).astype('<i2').tobytes()
    x,power=fft_power(raw,8_000_000,8192)
    assert x[np.argmax(power)]==500_000
    assert 10*np.log10(power.max())==pytest.approx(20*np.log10(16000/32768),abs=.001)


def test_wide_grid_preserves_tone_between_display_points():
    plan=SweepPlan(30_000_000,6_000_000_000,8_000_000,4_000_000)
    accumulator=Accumulator(plan)
    offsets=np.fft.fftshift(np.fft.fftfreq(8192,1/8_000_000));power=np.full(8192,1e-12)
    power[4701]=.25
    accumulator.add(2_400_000_000,offsets,power)
    assert np.nanmax(accumulator.dbfs())==pytest.approx(10*np.log10(.25))


def test_gui_live_and_sweep_mode_contract(tmp_path):
    from PySide6 import QtWidgets
    from h102_iio_demo.gui import MainWindow
    from test_gui import fixture_state
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow('offline',tmp_path/'keys',tmp_path/'out')
    w.state=fixture_state();w.connection=object();w.profiles.addItems(w.state['available'])
    w.mode.setCurrentIndex(2);w._controls()
    assert not w.seconds.isEnabled() and not w.start_button.isEnabled()  # 40 MSPS exceeds the continuous budget.
    w.channels.setCurrentIndex(2);w.pattern.setCurrentIndex(1);w.mode.setCurrentIndex(3)
    assert w.channels.currentData()==(1,) and w.pattern.currentData()=='normal'
    assert not w.pattern.isEnabled() and w.start_button.isEnabled() and w.sweep_box.isEnabled()
    w.close()


def test_live_api_has_no_unused_duration_constraint(tmp_path):
    from h102_iio_demo.backend import Connection,RxSession
    from test_gui import fixture_state
    info=fixture_state()['info']
    for rx in info['parameters']['rx']:rx['sample_rate_hz']=8_000_000
    connection=Connection('offline')
    session=RxSession(connection,info,(1,),'live','normal',None,tmp_path/'out')
    assert session.seconds is None and session.mode=='live'
    with pytest.raises(ValueError):RxSession(connection,info,(1,),'continuous','normal',None,tmp_path/'out')
