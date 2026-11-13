# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""PDF validation: MIME/extension alone is never enough."""
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

# pypdf logs a WARNING whenever it works around something in a PDF (e.g. "fontTools is required to
# fully parse the encoding of a CFF Type1 font..."). With no logging set up, Python prints these to
# stderr on every download. They are harmless here: check_pdf only needs the page count and a little
# page-1 text for the identity hint, and reports a PDF it can't read itself. Keep real errors.
logging.getLogger("pypdf").setLevel(logging.ERROR)


@dataclass
class PdfCheck:
    ok: bool
    reason: str
    bytes: int = 0
    sha256: str = ""
    pages: int = 0
    encrypted: bool = False
    first_page_text: str = ""


def check_pdf(path: Path) -> PdfCheck:
    data = path.read_bytes()
    n = len(data)
    if n == 0:
        return PdfCheck(False, "empty file")
    sha = hashlib.sha256(data).hexdigest()
    head = data[:1024].lstrip()
    if not head.startswith(b"%PDF-"):
        kind = "HTML" if b"<html" in data[:4096].lower() or b"<!doctype" in data[:4096].lower() else "non-PDF"
        return PdfCheck(False, f"{kind} content, no %PDF- signature", n, sha)
    if b"%%EOF" not in data[-2048:]:
        return PdfCheck(False, "no %%EOF trailer (truncated?)", n, sha)
    try:
        r = PdfReader(path)
        enc = r.is_encrypted
        if enc:
            try:
                r.decrypt("")
            except Exception:
                return PdfCheck(False, "encrypted, cannot open", n, sha, encrypted=True)
        pages = len(r.pages)
        if pages < 1:
            return PdfCheck(False, "zero pages", n, sha)
        try:
            text = (r.pages[0].extract_text() or "")[:2000]
        except Exception:
            text = ""
        return PdfCheck(True, "valid", n, sha, pages, enc, text)
    except Exception as e:  # pypdf raises many types
        return PdfCheck(False, f"unparseable: {type(e).__name__}: {e}", n, sha)


def identity_hint(check: PdfCheck, doi: str | None, title: str | None) -> str:
    """'confirmed' if the DOI or most title words appear on page 1, else 'unconfirmed'."""
    t = " ".join(check.first_page_text.lower().split())
    if doi and doi.lower() in t:
        return "confirmed-doi"
    if title:
        words = [w for w in "".join(c if c.isalnum() else " " for c in title.lower()).split() if len(w) > 3]
        if words and sum(w in t for w in words) / len(words) >= 0.7:
            return "confirmed-title"
    return "unconfirmed"
