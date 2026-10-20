"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       __main__.py
@brief      Start the local H102 IIO window without accepting passwords as arguments.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.5.0
@date       2026-10-15
"""
import argparse
from pathlib import Path
import sys
from PySide6 import QtWidgets, QtGui
from .gui import MainWindow


def main():
    """Default data/settings paths to the user directory; launch.sh selects the environment."""
    parser = argparse.ArgumentParser(description="LogicRF Hawk H102 IIO RX GUI")
    parser.add_argument("--host", default="")
    parser.add_argument("--known-hosts", type=Path, default=Path.home()/".local/share/logicrf/h102-iio-demo/known_hosts")
    parser.add_argument("--output", type=Path, default=Path.home()/"h102-iio-captures")
    parser.add_argument("--language", choices=("zh_CN", "en"), help="Interface language for this launch")
    args = parser.parse_args()
    app = QtWidgets.QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setFont(QtGui.QFont("Noto Sans CJK SC", 10))
    window = MainWindow(args.host, args.known_hosts, args.output, language=args.language)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

# End of file: __main__.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
