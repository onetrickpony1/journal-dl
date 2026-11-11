# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""PDFs are fetched by the browser itself (a page's fetch()), not by Playwright's own HTTP client."""
import http.server
import os
import threading

import pytest
from playwright.sync_api import sync_playwright

from journal_dl import browser

PDF = b"%PDF-1.4\n" + os.urandom(300_000) + b"\n%%EOF\n"     # binary, larger than one 32 KB chunk


def launch_chromium(p):
    try:
        return p.chromium.launch(channel="chrome", headless=True)
    except Exception:
        return p.chromium.launch(channel="chromium", headless=True)


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/pdf"):
            ok = "session=1" in (self.headers.get("Cookie") or "")      # the page's cookies come along
            body, ctype, status = (PDF, "application/pdf", 200) if ok else (b"<html>no</html>", "text/html", 403)
        else:
            body, ctype, status = b"<html><body>home</body></html>", "text/html", 200
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if self.path == "/":
            self.send_header("Set-Cookie", "session=1; Path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def base():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()


def test_fetch_in_page_returns_the_exact_bytes_with_the_sessions_cookies(base):
    with sync_playwright() as p:
        b = launch_chromium(p)
        ctx = b.new_context()
        tab = browser.site_tab(ctx, base)                      # opens the site once (sets the cookie)
        assert browser.site_tab(ctx, base) is tab              # and reuses that tab afterwards
        status, headers, body, url = browser.fetch_in_page(tab, base + "/pdf/1")
        b.close()
    assert status == 200 and headers["content-type"] == "application/pdf"
    assert body == PDF and url == base + "/pdf/1"
