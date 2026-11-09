# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Probe against a local fake issue page: download attribute, new-tab PDF, embedded viewer."""
import http.server
import json
import threading
from io import BytesIO
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter

from journal_dl import probe

FIX = Path(__file__).parent / "fixtures"


def pdf_bytes(text):
    w = PdfWriter(); w.add_blank_page(200, 200)
    w.add_metadata({"/Title": text})
    b = BytesIO(); w.write(b); return b.getvalue()


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path.startswith("/pdf/"):
            body, ctype = pdf_bytes(self.path), "application/pdf"
        elif self.path.startswith("/viewer/"):
            n = self.path.rsplit("/", 1)[1]
            body, ctype = f'<html><body><iframe src="/pdf/{n}"></iframe></body></html>'.encode(), "text/html"
        else:
            body, ctype = (FIX / "issue.html").read_bytes(), "text/html"
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


@pytest.fixture
def server():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()


def test_probe_three_channels(server, tmp_path):
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(accept_downloads=True)
        page = ctx.new_page(); page.goto(server + "/issue?SESSION=secret")
        rep = probe.run(ctx, page, tmp_path, count=3, delay_s=0, timeout_s=5)
        b.close()
    arts = rep["articles"]
    assert [a["validation"]["ok"] for a in arts] == [True, True, True], json.dumps(arts, indent=1)
    assert arts[0]["doi"] == "10.1097/ADT.0000000000000001"
    assert arts[0]["id_params"] == {"AN": "000-1"}
    assert arts[2]["doi"] is None  # DOI-less letter still handled
    print([a["channel"] for a in arts])
    blob = json.dumps(rep)
    assert "secret" not in blob  # no session material in report
