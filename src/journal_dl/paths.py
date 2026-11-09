# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Where journal-dl keeps its settings and data, per operating system.

    Linux    ~/.config/journal-dl                         ~/.local/share/journal-dl   (XDG respected)
    macOS    ~/Library/Application Support/journal-dl     (same folder for both)
    Windows  %APPDATA%\\journal-dl                         %LOCALAPPDATA%\\journal-dl

Older installs used ~/.config/ovid-dl and ~/.local/share/ovid-archive; if those exist they keep being
used, so nothing has to move. JOURNAL_DL_CONFIG / JOURNAL_DL_DATA override everything.
"""
import os
import sys
from pathlib import Path

APP = "journal-dl"


def _platform_dir(kind: str) -> Path:
    home = Path.home()
    if sys.platform == "win32":
        var = "APPDATA" if kind == "config" else "LOCALAPPDATA"
        base = os.environ.get(var) or str(home / ("AppData/Roaming" if kind == "config" else "AppData/Local"))
        return Path(base) / APP
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP
    var = "XDG_CONFIG_HOME" if kind == "config" else "XDG_DATA_HOME"
    base = os.environ.get(var) or str(home / (".config" if kind == "config" else ".local/share"))
    return Path(base) / APP


def config_dir() -> Path:
    env = os.environ.get("JOURNAL_DL_CONFIG") or os.environ.get("OVID_DL_CONFIG")
    if env:
        return Path(env)
    legacy = Path.home() / ".config" / "ovid-dl"
    if sys.platform not in ("win32", "darwin") and legacy.is_dir():
        return legacy
    return _platform_dir("config")


def data_dir() -> Path:
    env = os.environ.get("JOURNAL_DL_DATA") or os.environ.get("OVID_ARCHIVE_DATA")
    if env:
        return Path(env)
    legacy = Path.home() / ".local" / "share" / "ovid-archive"
    if sys.platform not in ("win32", "darwin") and legacy.is_dir():
        return legacy
    return _platform_dir("data")


def logs_dir() -> Path:
    return data_dir() / "logs"


def default_output() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "Journal Downloads"
