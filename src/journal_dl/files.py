# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Readable, Windows-safe archive layout (the archive lives on a Windows share):

    <root>/<Journal name>/<year>/Vol 20 No 3 - September 2021/01 - <Title> - <Surname>.pdf
    <root>/<Journal name>/.journal-dl/   reports, issue manifests, database backups, quarantine
    (shared by ovid-dl, wiley-dl and tandf-dl; older runs used ".ovid-dl", merged in automatically)
"""
import os
import re
import unicodedata
from pathlib import Path

RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
META = ".journal-dl"
OLD_META = (".ovid-dl",)
OLD_NAMES = {"archive-backup.sqlite": "ovid-backup.sqlite"}


def clean(s: str | None, maxlen: int = 120) -> str:
    """Keep the real name (spaces, &, accents); drop only what Windows forbids."""
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"\s*:\s*", " - ", s)               # "Title: Subtitle" -> "Title - Subtitle"
    s = s.replace("/", "-").replace("\\", "-")
    s = re.sub(r'[<>"|?*\x00-\x1f]', "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > maxlen:
        s = s[:maxlen].rsplit(" ", 1)[0]
    s = s.rstrip(" .-")
    if s.upper() in RESERVED:
        s += "_"
    return s or "Untitled"


# kept for internal temp/quarantine names
def safe(s: str | None, maxlen: int = 80) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9-]+", "_", s).strip("_.")[:maxlen].rstrip("_.")
    return s or "untitled"


def journal_dir(root: Path, title: str, issn: str = "") -> Path:
    return root / clean(title, 100)


def meta_dir(jdir: Path) -> Path:
    new = jdir / META
    for name in OLD_META:
        old = jdir / name
        if old.is_dir():
            merge_meta(old, new)
    if os.name == "nt" and not new.exists():
        new.mkdir(parents=True, exist_ok=True)
        _hide(new)
    return new


def _hide(path: Path):
    """Windows doesn't hide dot-folders: set the Hidden attribute (bookkeeping, not articles)."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
    except Exception:
        pass


def merge_meta(old: Path, new: Path):
    """Move an old bookkeeping folder's files into the new one (newer copy wins), then remove it."""
    import os
    import shutil
    for src in sorted(old.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(old)
        rel = rel.with_name(OLD_NAMES.get(rel.name, rel.name))
        dst = new / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
            os.replace(src, dst)
        else:
            src.unlink()
    shutil.rmtree(old, ignore_errors=True)


def issue_folder_name(issue: dict) -> str:
    vol, iss, date = issue["volume"], (issue["issue"] or "").strip(), issue["date_text"]
    if not iss:
        num = f"Vol {vol}"
    elif iss.isdigit():
        num = f"Vol {vol} No {int(iss)}"
    elif re.fullmatch(r"\d+\s*[-/]\s*\d+", iss):     # combined issues, e.g. "3-4"
        joined = re.sub(r"\s*[-/]\s*", "-", iss)
        num = f"Vol {vol} No {joined}"
    else:
        num = f"Vol {vol} {iss}"                         # e.g. "Supplement 1"
    return clean(f"{num} - {date}" if date else num, 80)


def issue_dir(jdir: Path, issue: dict) -> Path:
    return jdir / clean(issue["year"], 10) / issue_folder_name(issue)


def first_surname(authors: str | None) -> str:
    if not authors:
        return ""
    return clean(authors.split(";")[0].split(",")[0], 30)


def article_filename(seq: int, authors: str | None, title: str | None, provider_id: str = "",
                     max_len: int = 110) -> str:
    name = f"{seq:02d} - {clean(title, max_len)}"
    sur = first_surname(authors)
    if sur:
        name += f" - {sur}"
    return name + ".pdf"


def room_for_name(folder: Path, windows: bool | None = None) -> int:
    """Longest title that keeps the whole path inside Windows' classic 260-character limit
    (other systems: the usual 110)."""
    if not (os.name == "nt" if windows is None else windows):
        return 110
    return max(30, min(110, 259 - len(str(folder)) - 1 - 45))      # 45 = number, surname, ".pdf", spare
