#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       check_distribution.py
@brief      Verify the English H102 GUI source package without device access.
@details    Check exact regular-file membership, SHA-256, text language, Python syntax,
            local import closure and Markdown links. External device-service inputs remain
            separate and are never downloaded, executed or treated as qualified here.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.1
@date       2026-10-21
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "SOURCE-FILES.json"
EXTERNAL_MODULES = {"numpy", "paramiko", "pytest", "PySide6", "pyqtgraph"}
"""Separately installed host dependencies; no board service is imported or contacted."""
DEVICE_MODULES = {"h102_profile_config", "h102_iio_rx_lease", "h102_iio_owner_lock",
                  "h102_rf_usb_tx_storage", "h102_iio_tx_lease"}
"""Original board-only helpers supplied by the matching firmware/SDK installation."""


def files() -> dict[str, Path]:
    """Return source files, excluding metadata, caches and the documented root venv.

    The root .venv is separately installed host software, never source-package
    content. Other files and symlinks remain subject to exact manifest checks.
    """
    result = {}
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if relative.parts[0] == ".venv":
            continue
        if any(part in {".git", "__pycache__", ".pytest_cache"} for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("SYMLINK_NOT_ALLOWED: " + str(relative))
        if path.is_file() and str(relative) != MANIFEST:
            result[str(relative)] = path
    return result


def verify() -> dict:
    """Validate local package integrity and report explicit external-input limitations.

    No subprocess, network, block-device or board operation is performed. A raised
    error fails the CLI instead of silently omitting a damaged source file.
    """
    expected = json.loads((ROOT / MANIFEST).read_text())["files"]
    actual = files()
    errors = []
    if set(actual) != set(expected):
        errors.append({"file_set": {"missing": sorted(set(expected) - set(actual)),
                                    "extra": sorted(set(actual) - set(expected))}})
    local_modules = {p.stem for directory in (ROOT / "scripts", ROOT / "tests", ROOT / "h102_iio_demo")
                     for p in directory.glob("*.py")}
    local_modules |= {"h102_control", "h102_iio_demo"}
    python_count = markdown_count = 0
    optional_imports = set()
    for name, path in sorted(actual.items()):
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected.get(name, {}).get("sha256"):
            errors.append({"hash": name})
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            errors.append({"nontext": name})
            continue
        if name != "h102_iio_demo/translations/zh_CN.json" and re.search(r"[\u3400-\u9fff]", text):
            errors.append({"language": name})
        if name.endswith(".py"):
            python_count += 1
            try:
                tree = ast.parse(text, filename=name)
            except SyntaxError as error:
                errors.append({"syntax": name, "line": error.lineno})
                continue
            for node in ast.walk(tree):
                imports = []
                if isinstance(node, ast.Import):
                    imports = [entry.name for entry in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                    imports = [node.module]
                for imported in imports:
                    top = imported.split(".")[0]
                    if top in sys.stdlib_module_names or top in local_modules:
                        continue
                    if top in DEVICE_MODULES and name.startswith("h102_iio_demo/board_"):
                        continue
                    if top in EXTERNAL_MODULES:
                        optional_imports.add(top)
                    else:
                        errors.append({"unresolved_import": imported, "file": name})
        if name.endswith(".md"):
            markdown_count += 1
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if target.startswith(("http:", "https:", "mailto:", "#")):
                    continue
                target = unquote(target.split("#")[0])
                if target and not (path.parent / target).exists():
                    errors.append({"broken_link": target, "file": name})
    return {"status": "FAIL" if errors else "PASS_SOURCE_PACKAGE_ONLY",
            "files": len(actual), "python_files": python_count,
            "markdown_files": markdown_count, "external_imports": sorted(optional_imports),
            "device_services": "EXTERNAL_INSTALLED_REQUIREMENTS_UNCHANGED",
            "board_only_external_modules": sorted(DEVICE_MODULES),
            "hardware": "NOT_RUN", "errors": errors}


def main() -> int:
    """Print a machine-readable result and return nonzero for invalid distribution input."""
    try:
        result = verify()
    except (OSError, ValueError) as error:
        result = {"status": "FAIL", "error": str(error)}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS_SOURCE_PACKAGE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())

# End of file: check_distribution.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
