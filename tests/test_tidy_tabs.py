# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Issue #13: tabs journal-dl no longer needs are closed when a command is done."""
import http.server
import threading

import pytest
from playwright.sync_api import sync_playwright

from journal_dl import browser, sites


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = b"<html><body>page</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def base():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()


@pytest.fixture
def ctx():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            b = p.chromium.launch(channel="chromium", headless=True)
        yield b.new_context()
        b.close()


def tab(ctx, url, ours=False):
    pg = browser.new_tab(ctx) if ours else ctx.new_page()
    if url != "about:blank":
        pg.goto(url)
    return pg


def test_leftovers_closed_ovid_and_users_tabs_kept(ctx, base):
    blank = tab(ctx, "about:blank")                              # the window's first tab
    users = tab(ctx, base + "/news")                             # opened by the user
    old_wiley = tab(ctx, base + "/onlinelibrary/journal/1")      # left by an earlier run
    tf = tab(ctx, base + "/tandfonline/toc/x")
    ovid = tab(ctx, base + "/ovidweb.cgi?T=JS")
    door = tab(ctx, base + "/library/search", ours=True)        # opened by this run
    assert sites.tidy_tabs(ctx) == 4
    assert [p for p in ctx.pages if not p.is_closed()] == [users, ovid]
    assert all(p.is_closed() for p in (blank, old_wiley, tf, door))


def test_last_tab_never_closed(ctx, base):
    tab(ctx, base + "/onlinelibrary/journal/1")
    last = tab(ctx, base + "/tandfonline/toc/x", ours=True)
    assert sites.tidy_tabs(ctx) == 1
    assert ctx.pages == [last]


def test_nothing_to_do(ctx, base):
    users = tab(ctx, base + "/news")
    assert sites.tidy_tabs(ctx) == 0 and ctx.pages == [users]
