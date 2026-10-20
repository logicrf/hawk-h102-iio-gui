"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file test_overflow_abi_cap3.py
@brief Check ADC ABI/version admission and overflow rejection for reviewed old/new bitstreams.
@details Map actual regular files; model W1C responses without H102 or /dev/mem access.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 0.1.0
@date 2026-10-18
"""
import mmap
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from h102_iio_demo import board_capture as capture


class OverflowAbiTests(unittest.TestCase):
    """Run the real constructor/state machine with explicit mapping/W1C models only."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        primary=self.root/'adc/iio:device3';primary.mkdir(parents=True);node=primary.parent/'of_node';node.mkdir()
        (node/'reg').write_bytes(struct.pack('>II',0x43c00000,0x6000))
        (node/'compatible').write_bytes(b'adi,axi-adrv9002-rx-1.0\0')
        self.node=node;self.backing=self.root/'registers';self.backing.write_bytes(bytes(0x6000))
        with self.backing.open('r+b') as stream:
            for offset in (0,0x1000):stream.seek(offset);stream.write(struct.pack('<I',0x000a0300))
        self.hw=SimpleNamespace(devices={'axi-adrv9002-rx-lpc':primary,'axi-adrv9002-rx2-lpc':primary},read=lambda path:'1')
        self.maps=[];original_open=open;original_mmap=mmap.mmap
        def model_open(path,*args,**kwargs):
            self.assertEqual(str(path),'/dev/mem');return original_open(self.backing,*args,**kwargs)
        def model_map(fd,length,*,flags,prot,offset):
            self.assertEqual((length,offset),(0x6000,0x43c00000))
            value=original_mmap(fd,length,flags=flags,prot=prot,offset=0);self.maps.append(value);return value
        a=patch('builtins.open',side_effect=model_open);a.start();self.addCleanup(a.stop)
        b=patch.object(capture.mmap,'mmap',side_effect=model_map);b.start();self.addCleanup(b.stop)

    def identity(self,bit):return dict(boot_pins={'/boot/h102_logicrf_master.bit':bit})

    def test_both_exact_bits_preserve_window_checks(self):
        self.assertEqual(len(capture.SUPPORTED_BIT_SHA256),2)
        for bit in sorted(capture.SUPPORTED_BIT_SHA256):
            with self.subTest(bit=bit),capture.OverflowGuard(self.hw,self.identity(bit)) as guard:
                for channel in (1,2):
                    guard.begin(channel)
                    offset=(channel-1)*0x1000+0x88
                    self.assertEqual(struct.unpack_from('<I',guard.memory,offset)[0],4)
                    struct.pack_into('<I',guard.memory,offset,0)  # Model the hardware W1C acknowledgement.
                    guard.arm(channel)
                guard.poll()
                for channel in (1,2):self.assertTrue(guard.end(channel)['passed'])
            self.assertTrue(self.maps[-1].closed)

    def test_unknown_bit_and_wrong_dt_never_map(self):
        with self.assertRaisesRegex(RuntimeError,'UNKNOWN_ABI'):
            capture.OverflowGuard(self.hw,self.identity('f'*64))
        self.assertFalse(self.maps)
        (self.node/'reg').write_bytes(struct.pack('>II',0x43c00000,0x5000))
        with self.assertRaisesRegex(RuntimeError,'UNKNOWN_ABI'):
            capture.OverflowGuard(self.hw,self.identity(next(iter(capture.SUPPORTED_BIT_SHA256))))
        self.assertFalse(self.maps)

    def test_wrong_core_version_closes_mapping(self):
        with self.backing.open('r+b') as stream:stream.seek(0x1000);stream.write(struct.pack('<I',0xdeadbeef))
        with self.assertRaisesRegex(RuntimeError,'CORE_VERSION'):
            capture.OverflowGuard(self.hw,self.identity(next(iter(capture.SUPPORTED_BIT_SHA256))))
        self.assertTrue(self.maps[-1].closed)

    def test_warmup_and_live_overflow_stay_fatal_and_sticky(self):
        with capture.OverflowGuard(self.hw,self.identity(next(iter(capture.SUPPORTED_BIT_SHA256)))) as guard:
            guard.begin(1)
            with self.assertRaisesRegex(RuntimeError,'WARMUP_OVERFLOW'):guard.arm(1)
            struct.pack_into('<I',guard.memory,0x88,0);guard.arm(1)
            struct.pack_into('<I',guard.memory,0x88,4)
            with self.assertRaisesRegex(RuntimeError,'RX1_ADC_DMA_OVERFLOW'):guard.poll()
            self.assertEqual(struct.unpack_from('<I',guard.memory,0x88)[0],4)
            with self.assertRaisesRegex(RuntimeError,'RX1_ADC_DMA_OVERFLOW'):guard.end(1)


if __name__=='__main__':unittest.main()
# End of file: test_overflow_abi_cap3.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
