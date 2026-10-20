"""Verify exact English host mappings without changing installed device requirements."""
import hashlib
import json
from pathlib import Path

from h102_control.source_identity import installed_sources

ROOT = Path(__file__).resolve().parents[1]


def test_exact_reviewed_payloads_map_but_edits_and_unknown_names_do_not():
    """Translation permits only reviewed hashes; edited sources still face server rejection."""
    pins = json.loads((ROOT/'h102_control/installed-helpers.json').read_text())['helpers']
    assert set(pins) == {'board_session.py','board_radio.py','board_capture.py','board_tx.py','tx_cyclic.py'}
    for name, entry in pins.items():
        local = hashlib.sha256((ROOT/'h102_iio_demo'/name).read_bytes()).hexdigest()
        assert local == entry['local_sha256']
        assert installed_sources({name:local}) == {name:entry['installed_sha256']}
        changed = hashlib.sha256((ROOT/'h102_iio_demo'/name).read_bytes()+b'\n# edited').hexdigest()
        assert installed_sources({name:changed}) == {name:changed}
        assert installed_sources({name:entry['installed_sha256']}) == {name:entry['installed_sha256']}
    assert installed_sources({'unknown.py':'0'*64}) == {'unknown.py':'0'*64}


def test_client_lock_matches_delivered_sources():
    """Local client pins include the adapter and preserve the pre-translation provenance."""
    lock = json.loads((ROOT/'docs/h102-control-api.lock.json').read_text())
    assert lock['original_files'] and len(lock['files']) == 7
    for name, digest in lock['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest
