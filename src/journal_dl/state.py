# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Small remembered state (state.json in the config folder):

    last_run       what the last download was doing, so it can be resumed
    follows        journals followed for --update (new issues only)
    journal_sites  which site a journal was found on (journal-dl skips searching next time)
    guide          the guide's last answers, offered as defaults
"""
import json
import os
import re
import time

from . import paths


def _path():
    return paths.config_dir() / "state.json"


def load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def update(**values):
    """Read-modify-write (re-reads first, so separate runs don't wipe each other's keys)."""
    cur = load()
    cur.update(values)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"state.{os.getpid()}.part")
    tmp.write_text(json.dumps(cur, indent=2, ensure_ascii=False), encoding="utf-8")
    for attempt in range(5):          # Windows refuses to replace a file another process has open
        try:
            os.replace(tmp, p)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2)
    return cur


def key(title: str) -> str:
    return re.sub(r"[^a-z0-9&]+", " ", (title or "").lower()).strip()


# ---------------------------------------------------------------- last run
def start_run(spec: dict):
    update(last_run=dict(spec, started=time.time(), finished=False, where=None, done=0, total=None))


def progress(where=None, done=None, total=None):
    lr = load().get("last_run")
    if not lr:
        return
    if where is not None:
        lr["where"] = where
    if done is not None:
        lr["done"] = done
    if total is not None:
        lr["total"] = total
    update(last_run=lr)


def end_run(finished: bool, reason: str = ""):
    lr = load().get("last_run")
    if lr:
        lr.update(finished=finished, reason=reason, ended=time.time())
        update(last_run=lr)


def unfinished():
    lr = load().get("last_run")
    return lr if lr and not lr.get("finished") else None


# ---------------------------------------------------------------- follows / sites
def follows() -> list:
    return load().get("follows", [])


def follow(site: str, title: str, jid=None):
    fs = [f for f in follows() if not (f["site"] == site and key(f["title"]) == key(title))]
    fs.append({"site": site, "title": title, "id": jid, "since": time.strftime("%Y-%m-%d")})
    update(follows=fs)


def unfollow(title: str) -> int:
    fs = follows()
    keep = [f for f in fs if key(f["title"]) != key(title)]
    update(follows=keep)
    return len(fs) - len(keep)


def remember_site(title: str, site: str):
    js = load().get("journal_sites", {})
    js[key(title)] = site
    update(journal_sites=js)


def known_site(title: str):
    return load().get("journal_sites", {}).get(key(title))


def guide_defaults() -> dict:
    return load().get("guide", {})


def remember_guide(**values):
    g = guide_defaults()
    g.update(values)
    update(guide=g)
