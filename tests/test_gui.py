"""Test Qt budget checks, unapplied profiles and close waiting without board qualification."""
import json
from threading import Event
import time
from PySide6 import QtWidgets, QtTest
import pytest
from h102_iio_demo import gui


@pytest.fixture(scope='session')
def app():
    # Share one QApplication for translation/style state rather than recreating it per module.
    application = QtWidgets.QApplication.instance()
    if application is None:
        application = QtWidgets.QApplication([])
        application.setStyle('Fusion')
    return application


def idle(window, seconds=3):
    deadline=time.monotonic()+seconds
    while window.worker is not None and time.monotonic()<deadline:
        QtTest.QTest.qWait(20)
    assert window.worker is None


def fixture_state():
    return dict(available=['40msps-20mhz','8msps-4mhz'], info=dict(active='40msps-20mhz',configuration_id=1,api='68.21.6',boot_id='offline',parameters=dict(rx=[dict(channel=c,sample_rate_hz=40_000_000,rf_bandwidth_hz=20_000_000) for c in (1,2)]),radio=dict(rx_center_frequency_hz={'1':2400000000,'2':2400000000},groups=[dict(lo=2,channels=[1,2],tx_shared=[],editable=True)])),actual=dict(kernel='offline',data_idle=True))


def test_lo_mode_selection_is_staged_and_common_tx_frequency_is_readonly(app,tmp_path,monkeypatch):
    """Display logical presets by LO mode without applying selection or duplicate frequency inputs."""
    state=fixture_state();state['available']+=['40msps-20mhz-common','8msps-4mhz-common']
    state['info']['active']='40msps-20mhz-common'
    radio=state['info']['radio'];radio['mapping']={f'{p}{c}LoSelect':2 for p in ('rx','tx') for c in (1,2)}
    radio['groups'][0]['tx_shared']=[1,2]
    monkeypatch.setattr(gui.backend,'inspect',lambda *args:state)
    w=gui.MainWindow('offline',tmp_path/'keys',tmp_path/'out')
    w._connect();idle(w)
    assert w.profiles.count()==2 and w._selected_profile()=='40msps-20mhz-common'
    assert w.rf_mode.currentData()=='shared-lo2'
    assert not w.tx_panel.frequency.isEnabled() and w.tx_panel.frequency.value()==2400
    w.center.setValue(2400.5)
    assert w.center_button.isEnabled() and not w.mode.model().item(3).isEnabled()
    w.rf_mode.setCurrentIndex(0)
    assert w._selected_profile()=='40msps-20mhz' and w.apply_button.isEnabled()
    assert w.state['info']['active']=='40msps-20mhz-common' and w.worker is None
    w._disconnect();w.close()


def test_network_block_and_unapplied_profile(app,tmp_path,monkeypatch):
    monkeypatch.setattr(gui.backend,'inspect',lambda *args: fixture_state())
    w=gui.MainWindow('offline',tmp_path/'keys',tmp_path/'out')
    w._connect();idle(w)
    assert len(w.state['available'])==2
    assert not w.start_button.isEnabled()
    w.mode.setCurrentIndex(1)
    assert w.start_button.isEnabled()
    w.profiles.setCurrentText('8msps-4mhz')
    assert w.apply_button.isEnabled() and not w.start_button.isEnabled()
    w._disconnect()
    assert not w.start_button.isEnabled() and not hasattr(w,'password')
    w.close()


def test_window_waits_for_cleanup_and_responsive_stop(app,tmp_path):
    w=gui.MainWindow('offline',tmp_path/'keys',tmp_path/'out')
    w.show()
    started=Event();stop_event=Event();cleaned=Event()
    class Session:
        stopping=stop_event
        pattern='normal'
        mode='continuous'
        def snapshot(self):return {},{},{}
        def stop(self):stop_event.set()
        def run(self):
            started.set();stop_event.wait(3);time.sleep(.1);cleaned.set()
            return dict(status='PASS_RX_SESSION',recovery_confirmed=True)
    w.session=Session();w._launch('rx',w.session.run)
    for _ in range(20):
        if started.is_set():break
        QtTest.QTest.qWait(10)
    assert started.is_set()
    QtTest.QTest.qWait(30)
    assert w.stop_button.isEnabled()
    w.close()
    assert w.isVisible() and not cleaned.is_set()
    idle(w)
    QtTest.QTest.qWait(20)
    assert cleaned.is_set() and not w.isVisible()


def test_shared_center_integer_hz_and_busy_block(app,tmp_path,monkeypatch):
    from copy import deepcopy
    state=fixture_state();calls=[]
    monkeypatch.setattr(gui.backend,'inspect',lambda *args:deepcopy(state))
    def tune(connection,current_state,channels,hz,output,prepared_link=None,keep_control=False):
        calls.append((channels,hz))
        new=deepcopy(state)
        new['info']['radio']['rx_center_frequency_hz']={str(c):hz for c in (1,2)}
        return new
    monkeypatch.setattr(gui.backend,'tune_rx_idle',tune)
    w=gui.MainWindow('offline',tmp_path/'keys',tmp_path/'out')
    w._connect();idle(w)
    assert w._rx_lo_group()['channels']==[1,2] and not hasattr(w,'lo_group')
    w.center.setValue(4294.967296)
    assert w.center_button.isEnabled()
    gate=Event()
    w._launch('apply',lambda:(gate.wait(1),deepcopy(state))[1])
    assert not w.center_button.isEnabled() and not w.center.isEnabled()
    w._tune_center();assert not calls
    gate.set();idle(w)
    w.center.setValue(4294.967296);w._tune_center();idle(w)
    assert calls==[([1,2],4294967296)]
    assert '4294.967296' in w.center_actual.text()
    w.close()


def test_rf_axis_and_export_use_received_lo_not_new_target(app,tmp_path):
    import numpy as np
    from copy import deepcopy
    from h102_iio_demo.model import display_frame
    received=fixture_state()['info'];received['parameters']['rx'][0]['sample_rate_hz']=8_000_000
    n=8192;phase=2*np.pi*np.arange(n)/8
    raw=(np.column_stack((np.cos(phase),np.sin(phase)))*16000).astype('<i2').tobytes()
    frame=display_frame(raw,8_000_000)
    class Session:
        info=received;channels=(1,);mode='snapshot';pattern='normal';output=tmp_path/'session'
        def snapshot(self):return {1:raw},{},{1:frame}
    w=gui.MainWindow('offline',tmp_path/'keys',tmp_path/'out');w.session=Session()
    w.state=deepcopy(fixture_state())
    w.state['info']['radio']['rx_center_frequency_hz']={'1':2400500000,'2':2400500000}
    w.rf_axis.setChecked(True);w._refresh()
    fft=w.plots[1][2];peak=np.argmax(fft.yData)
    assert fft.xData[peak]==pytest.approx(2401)
    assert '2400.000000' in w.fft_widgets[1].toolTip()
    export=w.export(tmp_path/'export')
    assert export['metadata']['info']['radio']['rx_center_frequency_hz']['1']==2400000000
    w.close()


def test_waterfall_bounds_peak_and_display_only_axis(app,tmp_path):
    """Bound display cache; refresh, frequency-axis and brightness changes add no duplicate IQ rows."""
    import numpy as np
    from h102_iio_demo.model import display_frame
    w=gui.MainWindow('offline',tmp_path/'keys',tmp_path/'out')
    n=8192;phase=2*np.pi*np.arange(n)/8
    raw=(np.column_stack((np.cos(phase),np.sin(phase)))*16000).astype('<i2').tobytes()
    frame=display_frame(raw,8_000_000)
    for _ in range(260):
        w._update_waterfall(1,dict(frame),0,False)
    history=w.waterfall_history[1]
    assert history.shape==(240,512) and history.dtype==np.float32
    assert history.nbytes==491520
    assert history[-1].max()==pytest.approx(frame['dbfs'].max())
    w._update_waterfall(1,frame,0,False)
    before=history.copy()
    w._update_waterfall(1,frame,2400,True)
    assert np.array_equal(before,w.waterfall_history[1])
    rect=w.waterfall_images[1].boundingRect()
    assert w.waterfall_images[1].mapRectToParent(rect).left()>2395
    w.waterfall_floor.setValue(-50)
    assert w.waterfall_ceiling.value()>w.waterfall_floor.value()
    assert np.array_equal(before,w.waterfall_history[1])
    w.close()
