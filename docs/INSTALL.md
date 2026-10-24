# Installation

## Host

Use a Linux desktop with Python 3.10 or later, Qt-compatible graphics drivers and libiio 0.x, including its network backend. The application uses a native ctypes libiio adapter; installing an unrelated Python package named `iio` is not a substitute for the shared library.

On an Ubuntu host with libiio available from the distribution:

```bash
sudo apt install python3-venv libiio0 libgl1 libegl1 libopengl0 \
  libglib2.0-0 libfontconfig1 libdbus-1-3 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 libxcb-shape0 \
  libx11-xcb1 fonts-noto-cjk
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
bash ./launch.sh --host DEVICE_IP
```

Run from a graphical desktop session. Python dependency checks do not validate the Qt/OpenGL/XCB system libraries. Use `bash ./launch.sh` because ZIP extraction may not preserve executable permissions.

`requirements.lock` records the development environment. `requirements.txt` supplies compatible version ranges. `H102_GUI_PYTHON=/path/to/python` selects an existing environment. Windows/macOS installation is not qualified by this delivery.

## Device

The device needs the matching H102 Kuiper system and fixed-operation control API, including the five reviewed native GUI helpers. Ordinary operation uses the device IP and control service on TCP 30432, plus libiio networking. Installation and maintenance are administrator tasks; there is no automatic SSH or password fallback.

This application does not install a board service. A missing or incompatible service must be upgraded separately. The local API lock and installed-helper identity manifest describe exact requirements; translating host sources does not change the accepted board helper bytes.

## Language

The first launch defaults to English. Select English or Simplified Chinese in the title bar; the choice is saved locally. `--language en` or `--language zh_CN` overrides the language for one launch. Language changes do not reconnect the device or restart acquisition.

## Offline checks

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
.venv/bin/python scripts/check_distribution.py
```

These checks use model sessions and temporary files. They do not start RF, write an SD card or establish hardware qualification.

The source checker verifies the packaged files and ignores the local root `.venv`,
Git metadata and Python/test caches. It does not verify installed third-party
dependencies. Run `.venv/bin/python -m pip check` separately for dependency consistency.
