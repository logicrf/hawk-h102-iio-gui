"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.
@file conftest.py
@brief Isolate Qt preferences and release completed test windows between cases.
@details One QApplication is shared by the test process. Closed, idle windows
         must be destroyed before later translation broadcasts; active workers
         remain intact for diagnostics. No device access or forced thread stop.
@author LogicRF Technologies
@architect LogicRF
@email info@logicrf.com
@website https://www.logicrf.com
@version 1.1.0
@date 2026-10-24
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import pytest
from PySide6 import QtCore, QtWidgets
from h102_iio_demo import gui, i18n


@pytest.fixture(autouse=True)
def isolated_gui_preferences(tmp_path, monkeypatch):
    """Isolate settings per test without reading or replacing actual user preferences."""
    monkeypatch.setattr(i18n, 'default_settings', lambda: QtCore.QSettings(
        str(tmp_path / 'ui-settings.ini'), QtCore.QSettings.IniFormat))


@pytest.fixture(autouse=True)
def release_closed_test_windows(isolated_gui_preferences):
    """Dispose idle test windows before the next test reuses QApplication.

    Qt translation changes broadcast to all surviving widget trees. A closed
    window still retained by Python bindings can delay unrelated worker-finished
    signals. Keep active workers intact for failure diagnostics; never force-stop
    a session or change the tested timeout to make an assertion pass.
    """
    yield
    application = QtWidgets.QApplication.instance()
    if application is None:
        return
    for window in application.topLevelWidgets():
        if not isinstance(window, gui.MainWindow):
            continue
        if any(getattr(window, name, None) is not None
               for name in ('worker', 'warm_worker', 'warm_tx_worker')):
            continue
        window.close()
        if not window.isVisible():
            window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    application.processEvents()

# End of file: conftest.py
# Contact: info@logicrf.com | Website: https://www.logicrf.com
