# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

from pathlib import Path

from pypdf import PdfWriter

from journal_dl import sanitize
from journal_dl.validate import check_pdf


def make_pdf(path: Path):
    w = PdfWriter()
    w.add_blank_page(200, 200)
    with open(path, "wb") as f:
        w.write(f)


def test_valid_pdf(tmp_path):
    p = tmp_path / "a.pdf"; make_pdf(p)
    c = check_pdf(p)
    assert c.ok and c.pages == 1 and len(c.sha256) == 64


def test_pypdf_warnings_quiet():
    # issue #12: pypdf's "fontTools is required..." warnings were printed on every download
    import logging
    import journal_dl.validate  # noqa: F401  (sets the level on import)
    log = logging.getLogger("pypdf._cmap")
    assert not log.isEnabledFor(logging.WARNING)
    assert log.isEnabledFor(logging.ERROR)


def test_html_masquerading_rejected(tmp_path):
    p = tmp_path / "a.pdf"; p.write_text("<!DOCTYPE html><html>Session expired</html>")
    c = check_pdf(p)
    assert not c.ok and "HTML" in c.reason


def test_truncated_rejected(tmp_path):
    p = tmp_path / "a.pdf"; make_pdf(p)
    p.write_bytes(p.read_bytes()[:-60])
    assert not check_pdf(p).ok


def test_empty_rejected(tmp_path):
    p = tmp_path / "a.pdf"; p.write_bytes(b"")
    assert not check_pdf(p).ok


def test_url_sanitized():
    u = "https://ovidsp.ovid.com/ovidweb.cgi;jsessionid=ABC?T=JS&SESSION=xyz&AN=00132576-202112000-00001#x"
    assert sanitize.url(u) == "https://ovidsp.ovid.com/ovidweb.cgi"
    ids = sanitize.id_params(u)
    assert ids == {"AN": "00132576-202112000-00001"}


def test_ovid_pdf_token_redacted():
    u = "https://x.proxy.example.edu/ovftpdfs/FPACKPHMLGMCON00/fs046/ovft/live/gv023/00132576/00132576-202112000-00001.pdf"
    assert "FPACK" not in sanitize.url(u)
    assert sanitize.ovid_an(u) == "00132576-202112000-00001"


def test_issue_heading_regex():
    from journal_dl.ovid import HEADING_RE
    for text, want in [
        ("Volume 20(4)\xa0pgs. 217-621 December 2021\nISSN", "Volume 20(4) pgs. 217-621 December 2021"),
        ("Volume 111(11) pgs. 1564-1619 November 2026\nISSN", "Volume 111(11) pgs. 1564-1619 November 2026"),
        ("Volume 16(Supplement 1) pgs. 1-40 Spring 2017\n", "Volume 16(Supplement 1) pgs. 1-40 Spring 2017"),
    ]:
        assert " ".join(HEADING_RE.search(text.replace("\xa0", " ")).group(0).split()) == want
