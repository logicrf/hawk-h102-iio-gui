"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       test_boot_checks.py
@brief      Reject damaged, missing or empty boot-file inputs during parallel GUI checks.
@details    Use temporary regular files only, without devices, network or credentials.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.6.1
@date       2026-10-13
"""
import hashlib
import pytest
from h102_iio_demo.board_session import complete_boot_checks


@pytest.mark.parametrize('case',['valid','corrupt-first','corrupt-last','missing','empty'])
def test_complete_boot_files_are_required(tmp_path,case):
    """Every pinned file must be read; one corrupt or missing input rejects readiness."""
    pins={}
    for i in range(4):
        p=tmp_path/f'input-{i}'
        data=bytes([i])*65536
        p.write_bytes(data)
        pins[str(p)]=hashlib.sha256(data).hexdigest()
    if case=='empty':pins={}
    elif case=='corrupt-first':(tmp_path/'input-0').write_bytes(b'changed')
    elif case=='corrupt-last':(tmp_path/'input-3').write_bytes(b'changed')
    elif case=='missing':(tmp_path/'input-2').unlink()
    if case=='valid':complete_boot_checks({'boot_pins':pins})
    else:
        with pytest.raises((RuntimeError,FileNotFoundError)):
            complete_boot_checks({'boot_pins':pins})

# End of file: test_boot_checks.py
# Contact: info@logicrf.com | Website: https://www.logicrf.com
