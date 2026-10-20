"""Test 64-bit frequency, shared-RX write scope and partial rollback offline."""
from pathlib import Path
import pytest
from h102_iio_demo.model import mhz_to_hz
from h102_iio_demo.board_radio import apply_carrier, restore_carrier, describe,validate_restore_scene


@pytest.mark.parametrize('mhz,hz',[('2400.000001',2400000001),('4294.967296',4294967296),('6000',6000000000),('30',30000000)])
def test_decimal_mhz_and_unsigned32_boundary(mhz,hz):
    assert mhz_to_hz(mhz)==hz


@pytest.mark.parametrize('value',['nan','inf','29.999999','6000.000001','2400.0000001','garbage'])
def test_invalid_frequency(value):
    with pytest.raises(ValueError):mhz_to_hz(value)


class Hardware:
    """Model shared LO and one injected fault without importing the board SDK."""
    phy=Path('/fixture/phy')
    def __init__(self,fail=False):
        self.values={str(self.phy/'initial_calibrations'):'off',str(self.phy/'in_voltage0_ensm_mode'):'rf_enabled',str(self.phy/'in_voltage1_ensm_mode'):'rf_enabled',str(self.phy/'gain'):'30',**{str(self.alt('adrv9002-phy',i,'frequency')):str(2400000000 if i<2 else 2450000000) for i in range(4)}}
        self.fail,self.writes=fail,[]
    def alt(self,name,index,attribute):return self.phy/f'lo{index}'
    def settings(self):return dict(self.values)
    def read(self,path):return self.values[str(path)]
    def write(self,path,value,*args):
        self.writes.append((str(path),value));self.values[str(path)]=value
        if str(path)==str(self.alt('',0,'')):
            self.values[str(self.alt('',1,''))]=value
            if self.fail:
                self.fail=False;raise OSError('injected driver failure after RX LO update')


def test_shared_rx_changes_no_tx_or_gain_and_restores_policy():
    hw=Hardware();before=hw.settings();checks=[]
    expected=apply_carrier(hw,before,[1,2],2400500000,lambda:checks.append(True))
    assert hw.settings()==expected
    assert hw.read(hw.alt('',0,''))==hw.read(hw.alt('',1,''))=='2400500000'
    assert hw.read(hw.alt('',2,''))==hw.read(hw.alt('',3,''))=='2450000000'
    assert hw.read(hw.phy/'gain')=='30'
    assert hw.read(hw.phy/'initial_calibrations')=='off'
    assert len(checks)==3


def test_partial_update_rolls_back_without_tx_writes():
    hw=Hardware(fail=True);before=hw.settings()
    with pytest.raises(OSError):apply_carrier(hw,before,[1,2],2400500000,lambda:None)
    assert hw.settings()!=before
    restore_carrier(hw,before,[1,2],lambda:None)
    assert hw.settings()==before
    assert not any(path in (str(hw.alt('',2,'')),str(hw.alt('',3,''))) for path,_ in hw.writes)


@pytest.mark.parametrize('fail',[False,True])
@pytest.mark.parametrize('policy',['off','auto'])
def test_common_lo_commits_or_restores_both_port_carriers(fail,policy,monkeypatch):
    """Run actual RX/TX cache transactions; failure may change carriers only within the selected group."""
    class CommonHardware(Hardware):
        def __init__(self,fail=False):
            super().__init__(fail)
            self.cached={0:'rf_enabled',1:'rf_enabled'}
            for i in (0,1):
                self.values[str(self.phy/f'out_voltage{i}_en')]='0'
                self.values[str(self.phy/f'out_voltage{i}_ensm_mode')]='calibrated'
                self.values[str(self.phy/f'out_voltage{i}_atten_control_mode')]='spi'
        def settings(self):
            return {k:v for k,v in self.values.items() if not k.endswith('_en') and not ('out_voltage' in k and k.endswith('_ensm_mode'))}
        def stop(self):
            for i in (0,1):self.write(self.phy/f'out_voltage{i}_en','0')
            return []
        def write(self,path,value,*args):
            if path in (self.alt('',0,''),self.alt('',2,'')):
                assert all(self.read(self.phy/f'in_voltage{i}_ensm_mode')=='calibrated' for i in (0,1))
            super().write(path,value,*args)
            for i in (0,1):
                if path==self.phy/f'out_voltage{i}_atten_control_mode':self.cached[i]=self.values[str(self.phy/f'out_voltage{i}_ensm_mode')]
                if path==self.phy/f'out_voltage{i}_en' and value=='1':self.values[str(self.phy/f'out_voltage{i}_ensm_mode')]=self.cached[i]
            if path==self.alt('',2,''):self.values[str(self.alt('',3,''))]=value
    hw=CommonHardware(fail=fail)
    hw.values[str(hw.phy/'initial_calibrations')]=policy
    for i in (2,3):hw.values[str(hw.alt('',i,''))]='2400000000'
    calibrations=[]
    def calibrate(device,path,check,timings=None):
        assert all(device.read(device.alt('',i,''))=='2600000000' for i in range(4))
        assert all(device.read(device.phy/f'in_voltage{i}_ensm_mode')=='calibrated' for i in (0,1))
        assert device.read(path)=='auto'
        assert all(device.read(device.phy/f'out_voltage{i}_ensm_mode')=='calibrated' for i in (0,1))
        calibrations.append(True)
    monkeypatch.setattr('h102_iio_demo.board_radio.run_initial_calibrations',calibrate)
    before=hw.settings()
    def checked(calibrated=False):
        for i in (0,1):
            power=hw.read(hw.phy/f'out_voltage{i}_en')
            assert power=='0' or (calibrated and power=='1' and hw.read(hw.phy/f'out_voltage{i}_ensm_mode')=='calibrated')
    if fail:
        with pytest.raises(OSError):apply_carrier(hw,before,[1,2],2600000000,checked,tx_channels=[1,2])
        validate_restore_scene(hw,before,hw.settings(),[1,2],2600000000,failed=hw.settings(),tx_channels=[1,2])
        restore_carrier(hw,before,[1,2],checked,[1,2])
        assert hw.settings()==before
    else:
        expected=apply_carrier(hw,before,[1,2],2600000000,checked,tx_channels=[1,2])
        assert hw.settings()==expected
        assert all(hw.read(hw.alt('',i,''))=='2600000000' for i in range(4))
    assert all(hw.read(hw.phy/f'out_voltage{i}_en')=='0' for i in (0,1))
    assert not any('out_voltage' in p and p.endswith('_ensm_mode') and v!='calibrated' for p,v in hw.writes)
    assert len(calibrations)==(1 if policy=='auto' and not fail else 0)


@pytest.mark.parametrize('policy',['off','auto'])
def test_driver_shared_lo_uses_one_frequency_write_without_gui_tx_power(tmp_path,policy):
    """Use one joint driver transaction when supported; never bypass auto mode or power TX directly."""
    class AtomicHardware(Hardware):
        def __init__(self):
            super().__init__();self.phy=tmp_path
            # Model the real sysfs capability attribute; use the in-memory model for other attributes.
            (self.phy/'fdd_shared_lo_atomic').write_text('1')
            self.values={str(self.phy/'initial_calibrations'):policy,
                         **{str(self.alt('',i,'')):'2400000000' for i in range(4)}}
        def read(self,path):
            if path.name=='fdd_shared_lo_atomic':return path.read_text().strip()
            return super().read(path)
        def write(self,path,value,*args):
            self.writes.append((str(path),value));self.values[str(path)]=value
            if path==self.alt('',0,''):
                for i in range(4):self.values[str(self.alt('',i,''))]=value
    hw=AtomicHardware();before=hw.settings();checks=[]
    expected=apply_carrier(hw,before,[1,2],1000000000,lambda:checks.append(True),tx_channels=[1,2])
    assert hw.settings()==expected
    assert hw.writes==[(str(hw.phy/'initial_calibrations'),policy),(str(hw.alt('',0,'')),'1000000000')]
    assert len(checks)==3
