# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""User settings (settings.json in the config folder): archive folder, library proxy, browser.

Set them with `journal-dl --setup`. Example for an institution that uses an EZproxy:

    {"output": "D:/Journals", "proxy": "proxy.library.example.edu",
     "login_hosts": ["login.example.edu"], "institution_name": "Example University"}
"""
import json
import os
from pathlib import Path

from . import paths

DEFAULTS = {
    "output": None,                 # None -> <Documents>/Journal Downloads
    "proxy": "",                    # EZproxy host, e.g. "proxy.library.example.edu"; "" = no proxy (campus / VPN)
    "login_hosts": [],              # the institution's sign-in host(s), to notice when a session has expired
    "institution_name": "",         # shown by Wiley when signed in ("" = don't check)
    "library_journal_search": "",   # library catalogue journal-search URL ending in the query text (for Ovid)
    "library_ovid_door": "",        # a journal the catalogue opens on Ovid (any one works)
    "chrome": None,                 # path to Chrome/Chromium/Edge; None = find it
    "cdp_port": 9333,               # local port of the downloader's own browser window
    "notify": True,                 # desktop notifications
    "ntfy_topic": "",               # optional: also push to this ntfy.sh topic (phone)
    "path_aliases": [],             # optional: [["/mnt/share", "H:"]] to also print paths as another PC sees them
}


def path() -> Path:
    return paths.config_dir() / "settings.json"


def exists() -> bool:
    return path().is_file()


def load() -> dict:
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(path().read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"(ignoring unreadable settings file {path()}: {e})")
    return s


def save(values: dict):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
    cur.update(values)
    tmp = p.with_suffix(".part")
    tmp.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    os.replace(tmp, p)


S = load()


def output_dir() -> Path:
    env = os.environ.get("JOURNAL_DL_OUTPUT") or os.environ.get("OVID_ARCHIVE_ROOT")
    if env:
        return Path(env)
    return Path(S["output"]) if S.get("output") else paths.default_output()


def proxied(host: str) -> str:
    """'www.tandfonline.com' -> 'https://www-tandfonline-com.proxy.example.edu' (EZproxy host naming)."""
    proxy = (S.get("proxy") or "").strip()
    return f"https://{host.replace('.', '-')}.{proxy}" if proxy else f"https://{host}"


def login_hints() -> tuple:
    hints = list(S.get("login_hosts") or [])
    if S.get("proxy"):
        hints.append(f"{S['proxy']}/login")
    return tuple(hints)
