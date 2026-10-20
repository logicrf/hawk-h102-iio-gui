"""Test TX requests, IQ peaks/cycles and independent board rejection offline."""
from dataclasses import replace
import numpy as np
import pytest
from h102_iio_demo.tx_model import TxPlan,tone,waveform
from h102_iio_demo.board_tx import raw_validate,validate,apply_tx_carrier


def info():
    return dict(radio=dict(mapping=dict(rx1LoSelect=2,rx2LoSelect=2,tx1LoSelect=1,tx2LoSelect=1)),
                parameters=dict(tx=[dict(channel=c,sample_rate_hz=8000000,rf_bandwidth_hz=4000000) for c in (1,2)]))


def test_tone_matches_fft_and_peak():
    raw,meta=tone(8000000,4000000,250001,8192)
    iq=np.frombuffer(raw,dtype='<i2').reshape(-1,2)
    spectrum=np.fft.fft(iq[:,0]+1j*iq[:,1])
    assert np.argmax(abs(spectrum))==meta['bins']
    assert meta['offset_hz']==250000
    assert meta['peak']<=8192
    raw_validate(raw,meta)


@pytest.mark.parametrize('changes',[dict(channels=(1,1)),dict(frequency_hz=49999999),dict(frequency_hz=5800000001),
    dict(attenuation_db=19.9),dict(attenuation_db=40.05),dict(attenuation_db=float('nan')),dict(attenuation_db=30.01),
    dict(seconds=0),dict(seconds=301),dict(offset_hz=0),dict(offset_hz=1800000),dict(peak=8193)])
def test_invalid_parameters(changes):
    with pytest.raises(ValueError):replace(TxPlan((1,),2400000000),**changes).prepare(info())


def test_channels_and_shared_lo():
    value=info();plan=TxPlan((2,),2400000000)
    request,data=plan.prepare(value)
    assert set(data)=={2}
    assert validate(request,value['radio']['mapping'],value['parameters'])==[1,2]
    value['radio']['mapping']['rx1LoSelect']=1
    with pytest.raises(ValueError):plan.prepare(value)
    with pytest.raises(ValueError):validate(request,value['radio']['mapping'],value['parameters'])


def test_shared_lo_requires_actual_matching_rx_frequencies():
    """Both host/board reject missing or mismatched inputs; unshared RX does not constrain TX frequency."""
    value=info();value['radio']['mapping'].update(tx1LoSelect=2,tx2LoSelect=2)
    plan=TxPlan((1,2),1000000000)
    value['radio']['rx_center_frequency_hz']={'1':1000000000,'2':1000000000}
    request,_=plan.prepare(value)
    assert validate(request,value['radio']['mapping'],value['parameters'],
                    value['radio']['rx_center_frequency_hz'])==[1,2]
    for frequencies in ({'1':1000000000}, {'1':1000000000,'2':1000000001},
                        {'1':1000000000,'2':'1000000000'}):
        value['radio']['rx_center_frequency_hz']=frequencies
        with pytest.raises(ValueError):plan.prepare(value)
        with pytest.raises(ValueError):validate(request,value['radio']['mapping'],value['parameters'],frequencies)
    value['radio']['mapping']['rx2LoSelect']=1
    value['radio']['rx_center_frequency_hz']={'1':1000000000,'2':2450000000}
    request,_=plan.prepare(value)
    assert validate(request,value['radio']['mapping'],value['parameters'],
                    value['radio']['rx_center_frequency_hz'])==[1,2]


@pytest.mark.parametrize('shared,current,reject,writes',[
    (True,1000000000,False,0),(True,1000000001,True,0),
    (False,2450000000,False,2),(False,1000000000,False,0)])
def test_tx_carrier_does_not_retune_shared_rx(shared,current,reject,writes):
    """Exercise the real write entry and reject shared-LO mismatch before the first write."""
    class Hardware:
        def __init__(self):self.values={2:str(current),3:str(current)};self.writes=[]
        def alt(self,name,channel,attribute):return channel
        def read(self,path):return self.values[path]
        def write(self,path,value):self.writes.append((path,value));self.values[path]=value
    hw=Hardware();mapping=info()['radio']['mapping']
    if shared:mapping.update(tx1LoSelect=2,tx2LoSelect=2)
    if reject:
        with pytest.raises(RuntimeError,match='TX_SHARED_RX_LO_CHANGED'):
            apply_tx_carrier(hw,mapping,[1,2],1000000000)
    else:apply_tx_carrier(hw,mapping,[1,2],1000000000)
    assert len(hw.writes)==writes


def test_file_size_peak_hash_and_clock(tmp_path):
    raw,meta=tone(8000000,4000000,-250000)
    path=tmp_path/'tone.iq';path.write_bytes(raw)
    value=info();req,data=TxPlan((1,2),2400000000,iq_path=path).prepare(value)
    assert data[1]==data[2]==raw
    with pytest.raises(ValueError):raw_validate(raw[:-1],meta)
    with pytest.raises(ValueError):raw_validate(bytes(len(raw)),meta)
    with pytest.raises(ValueError):waveform(np.full((65536,2),8192,dtype='<i2').tobytes())
    with pytest.raises(ValueError):waveform(bytes(len(raw)))
    req['waveforms']['1']['sample_rate_hz']=40000000
    with pytest.raises(ValueError):validate(req,value['radio']['mapping'],value['parameters'])
    path.write_bytes(raw+b'\0')
    with pytest.raises(ValueError):TxPlan((1,),2400000000,iq_path=path).prepare(value)


def test_tx_network_monitor_budget_and_tx_only(tmp_path):
    from h102_iio_demo.backend import Connection
    from h102_iio_demo.tx_backend import TxSession
    value=info();value['parameters']['rx']=[dict(channel=c,sample_rate_hz=40000000,rf_bandwidth_hz=20000000) for c in (1,2)]
    connection=Connection('offline')
    with pytest.raises(ValueError):TxSession(connection,value,(1,),TxPlan((1,),2400000000),tmp_path/'bad')
    session=TxSession(connection,value,(),TxPlan((1,),2400000000),tmp_path/'ok')
    assert session.channels==() and not session.can_tune()
