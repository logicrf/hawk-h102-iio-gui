"""Configure candidate imports without device access."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import pytest
from PySide6 import QtCore
from h102_iio_demo import i18n


@pytest.fixture(autouse=True)
def isolated_gui_preferences(tmp_path, monkeypatch):
    """Isolate settings per test without reading or replacing actual user preferences."""
    monkeypatch.setattr(i18n, 'default_settings', lambda: QtCore.QSettings(
        str(tmp_path / 'ui-settings.ini'), QtCore.QSettings.IniFormat))
