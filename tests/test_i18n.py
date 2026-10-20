"""Run real bilingual Qt tests with controlled sessions, without board/RF/continuity claims."""
import ast
from copy import deepcopy
from pathlib import Path
from string import Formatter
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6 import QtCore, QtTest, QtWidgets

from test_gui import app, fixture_state, idle
from h102_iio_demo import gui
from h102_iio_demo.i18n import CHINESE, ENGLISH, Message, message
from h102_iio_demo.model import display_frame


def sources(value):
    if isinstance(value, Message):
        yield value.source
        for item in value.values.values(): yield from sources(item)
    elif isinstance(value, str): yield value


def chinese(text):
    return any('\u4e00' <= char <= '\u9fff' for char in text)


def window(tmp_path, **kwargs):
    return gui.MainWindow('offline', tmp_path/'keys', tmp_path/'out', **kwargs)


def ready(w):
    state=fixture_state()
    for item in state['info']['parameters']['rx']: item['sample_rate_hz']=8_000_000
    w.state=state;w.connection=object()
    w._mode_profiles_changed();w._show_actual();w._show_radio();w._controls()


def test_catalog_and_all_registered_templates_are_complete(app, tmp_path):
    """Check complete static translation and matching source/target placeholders/formats."""
    formatter=Formatter()
    assert set(ENGLISH) == set(CHINESE)
    for source, target in ENGLISH.items():
        fields=lambda text:sorted((name,spec,conversion) for _,name,spec,conversion in formatter.parse(text) if name is not None)
        assert fields(source)==fields(target),source
        assert fields(source)==fields(CHINESE[source]),source
    for filename in ('gui.py', 'tx_panel.py'):
        tree=ast.parse((Path(gui.__file__).parent/filename).read_text())
        for node in ast.walk(tree):
            if (isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
                    and node.func.id=='message' and isinstance(node.args[0],ast.Constant)):
                source=node.args[0].value
                assert not chinese(source) or source in ENGLISH,source
    w=window(tmp_path)
    try:
        for _, value in w.i18n._bindings.values():
            for source in sources(value):
                assert not chinese(source) or source in ENGLISH,source
    finally:w.close()


def test_switch_preserves_controls_data_values_and_emits_no_actions(app,tmp_path):
    w=window(tmp_path);ready(w);w.show();w.resize(1100,780)

    w.tx_panel.file.setText('/tmp/'+CHINESE['Start RX']+'/'+CHINESE['Connection']+'.iq')
    for section in w.sections.values():section.set_expanded(True)
    w.tabs.setCurrentIndex(1)
    combos=[w.rf_mode,w.profiles,w.channels,w.mode,w.acquisition_mode,w.stop_condition,w.pattern,w.tx_panel.source,w.tx_panel.channels]
    signals=[]
    for combo in combos:combo.currentIndexChanged.connect(lambda *_:signals.append('index'))
    w.center.valueChanged.connect(lambda *_:signals.append('frequency'))
    state=deepcopy(w.state)
    before=[(box.currentIndex(),[box.itemData(i) for i in range(box.count())]) for box in combos]
    flags=[section.header.isChecked() for section in w.sections.values()]
    for language in ('en','zh_CN','en'):
        w.chrome.language.setCurrentIndex(w.chrome.language.findData(language))
        QtTest.QTest.qWait(20)
        assert before==[(box.currentIndex(),[box.itemData(i) for i in range(box.count())]) for box in combos]
        assert flags==[section.header.isChecked() for section in w.sections.values()]
        assert w.state==state and w.tabs.currentIndex()==1 and not signals
        assert w.controls_dock.widget().horizontalScrollBar().maximum()==0
    assert w.connect_button.text()=='Connect / refresh'
    assert w.tx_panel.file.text()=='/tmp/'+CHINESE['Start RX']+'/'+CHINESE['Connection']+'.iq'
    assert not hasattr(w,'password') and not hasattr(w,'user')
    assert w.i18n.settings.allKeys()==['language']
    assert w.sections['tx'].header.text()=='TX control'
    assert w.fft_widgets[1].getAxis('bottom').labelText=='Baseband frequency'
    assert w.sweep_plot.getAxis('left').labelUnits=='dBFS'
    assert [label.text for _,label in w.sweep_plot.plotItem.legend.items]==['Current round','Max hold']
    # Input fields are never translated; the language selector keeps its native Chinese name.
    for widget in w.findChildren(QtWidgets.QWidget):
        values=[widget.toolTip(),widget.accessibleName()]
        if isinstance(widget,(QtWidgets.QLabel,QtWidgets.QAbstractButton)):values.append(widget.text())
        if isinstance(widget,QtWidgets.QComboBox):values += [widget.itemText(i) for i in range(widget.count())]
        for value in values:assert not chinese(value) or value==CHINESE['Simplified Chinese'],value
    w._disconnect();w.close()


def test_preference_relaunch_invalid_fallback_and_readonly_failure(app,tmp_path):
    config=tmp_path/'settings.ini'
    settings=QtCore.QSettings(str(config),QtCore.QSettings.IniFormat)
    w=window(tmp_path,settings=settings)
    assert w.i18n.language=='en'
    w.chrome.language.setCurrentIndex(w.chrome.language.findData('zh_CN'));w.close()
    w=window(tmp_path,settings=QtCore.QSettings(str(config),QtCore.QSettings.IniFormat))
    assert w.i18n.language=='zh_CN' and w.phase.text()==CHINESE['Disconnected [msg-c748941e]']
    with pytest.raises(ValueError):w.i18n.set_language('unsupported')
    assert w.i18n.language=='zh_CN'
    w.close();settings.setValue('language','invalid');settings.sync()
    w=window(tmp_path,settings=settings)
    assert w.i18n.language=='en';w.close()
    class ReadOnlySettings:
        def value(self,*_):return 'zh_CN'
        def setValue(self,*_):pass
        def sync(self):pass
        def status(self):return QtCore.QSettings.AccessError
    w=window(tmp_path,settings=ReadOnlySettings())
    w.i18n.set_language('en')
    assert w.i18n.language=='en' and 'Could not save language' in w.phase.text()
    w.close()


def test_connection_in_flight_is_not_restarted_by_language(app,tmp_path,monkeypatch):
    entered=Event();gate=Event();calls=[]
    def inspect(*args):
        calls.append('inspect');entered.set();gate.wait(2);return fixture_state()
    monkeypatch.setattr(gui.backend,'inspect',inspect)
    w=window(tmp_path);w._connect()
    worker=w.worker
    w.i18n.set_language('en',persist=False)
    assert 'Connecting' in w.phase.text() and w.worker is worker
    gate.set();idle(w)
    assert calls==['inspect'] and entered.is_set() and 'Connected · 2 profiles' in w.phase.text()
    w.i18n.set_language('zh_CN',persist=False)
    assert message('Connected · {p0} profiles · {p1}',p0=2,p1=message('RX idle')).render('zh_CN') in w.phase.text()
    w._disconnect();w.close()


@pytest.mark.parametrize('tx',[False,True])
def test_active_rx_recording_and_tx_keep_session_and_stop_ownership(app,tmp_path,tx):
    """Use real QThread with a controlled session; switching language does not rebuild or stop it."""
    w=window(tmp_path);ready(w)
    stop=Event();entered=Event();calls=[]
    n=8192;phase=2*np.pi*np.arange(n)/8
    raw=(np.column_stack((np.cos(phase),np.sin(phase)))*16000).astype('<i2').tobytes()
    frame=display_frame(raw,8_000_000)
    stats={1:dict(samples=n,timeouts=0,bytes_per_second=32e6,elapsed=1)}
    session=object.__new__(gui.TxSession) if tx else SimpleNamespace()
    session.mode='continuous';session.pattern='normal';session.recording=not tx
    session.info=w.state['info'];session.stopping=stop
    session.snapshot=lambda:({1:raw},stats,{1:frame})
    session.stop=lambda:(calls.append('stop'),stop.set())
    def run():
        # Keep the model active until the explicit stop; a loaded Qt suite may take
        # longer than three seconds to retranslate every live test window.
        entered.set();stop.wait(30)
        return dict(status='PASS_TX_SESSION' if tx else 'PASS_RX_SESSION',recovery_confirmed=True)
    session.run=run;w.session=session;w._launch('rx',session.run)
    for _ in range(20):
        if entered.is_set():break
        QtTest.QTest.qWait(10)
    w._notice('ready',{'tx':tx});w._refresh()
    worker=w.worker;history=w.waterfall_history[1];curve=w.plots[1][2].yData.copy()
    for language in ('en','zh_CN','en'):
        w.i18n.set_language(language,persist=False)
        assert w.worker is worker and w.session is session and not stop.is_set() and not calls
        assert w.waterfall_history[1] is history
        assert np.array_equal(w.plots[1][2].yData,curve)
    assert ('TX active' if tx else 'Receiving') in w.phase.text()
    assert (w.tx_panel.action if tx else w.rx_action).accessibleName()==('Stop TX' if tx else 'Stop RX')
    assert 'Lost sample count unknown' in w.statistics.text()
    if not tx:assert w.record_action.accessibleName()=='Stop recording and drain files'
    (w.tx_panel.action if tx else w.rx_action).click();idle(w)
    assert calls==['stop'] and stop.is_set() and ('TX stopped' if tx else 'RX ended') in w.phase.text()
    w._disconnect();w.close()


def test_sweep_retranslation_preserves_frame_history_and_view(app,tmp_path):
    w=window(tmp_path);ready(w)
    w.mode.setCurrentIndex(w.mode.findData('sweep'))
    x=np.linspace(50,5800,1024);y=np.full(1024,-80.0);y[100]=-20
    frame=dict(frequency_mhz=x,dbfs=y,max_hold=y,round=2,complete=True,segment=225,segment_count=225,center_hz=5800_000_000)
    w.session=SimpleNamespace(mode='sweep',pattern='normal',channel=1,snapshot=lambda:(frame,frame,2,450))
    w._refresh_sweep();history=w.sweep_history
    before=w.sweep_plot.viewRange();last=w.sweep_last_frame
    w.i18n.set_language('en',persist=False)
    assert w.sweep_plot.plotItem.titleLabel.text=='Segmented sweep · Round 2 complete'
    assert 'Complete rounds 2' in w.statistics.text() and 'Peak ' in w.statistics.text()
    assert w.sweep_history is history and w.sweep_last_frame is last
    assert np.allclose(w.sweep_plot.viewRange(),before)
    w.i18n.set_language('zh_CN',persist=False)
    assert message('Segmented sweep · Round {p0} {p1}',p0=2,p1=message('complete')).render('zh_CN') in w.sweep_plot.plotItem.titleLabel.text
    w.session=None;w._disconnect();w.close()


def test_error_details_paths_and_fingerprint_remain_literal(app,tmp_path):
    w=window(tmp_path)
    detail='0xc907 /tmp/'+CHINESE['Connection']+'.iq {raw} <fault>'
    w.i18n.bind(w.phase.setText,message("Cannot start: ")+detail)
    w.i18n.set_language('en',persist=False)
    assert w.phase.text()=='Cannot start: '+detail
    fingerprint='SHA256:0123abc'
    dialog=w.i18n.text("Device {host}\nHost key fingerprint:\n{fingerprint}\n\nAfter verification, trust and connect?",host='10.168.1.217',fingerprint=fingerprint)
    assert 'Host key fingerprint' in dialog and fingerprint in dialog
    w.i18n.set_language('zh_CN',persist=False)
    assert w.phase.text()==CHINESE['Cannot start: ']+detail
    w.close()


def test_standard_qt_dialog_buttons_follow_language(app,tmp_path):
    w=window(tmp_path)
    box=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
    assert box.button(QtWidgets.QDialogButtonBox.Cancel).text().replace('&','')=='Cancel'
    w.i18n.set_language('en',persist=False)
    QtTest.QTest.qWait(20)
    assert box.button(QtWidgets.QDialogButtonBox.Cancel).text().replace('&','')=='Cancel'
    w.i18n.set_language('zh_CN',persist=False)
    QtTest.QTest.qWait(20)
    assert CHINESE['Cancel'] in box.button(QtWidgets.QDialogButtonBox.Cancel).text()
    box.close();w.close()
