#!/usr/bin/env bash
set -euo pipefail
GUI_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
GUI_PYTHON=${H102_GUI_PYTHON:-$GUI_ROOT/.venv/bin/python}
if [[ ! -x "$GUI_PYTHON" ]]; then
  echo 'Python environment missing; install README dependencies or set H102_GUI_PYTHON.' >&2
  exit 1
fi
export PYTHONPATH="$GUI_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$GUI_PYTHON" -m h102_iio_demo "$@"
