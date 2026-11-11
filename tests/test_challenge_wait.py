# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""A 'verify you are human' page: wait for it to clear (or for the user), never crash, never get past it."""
import pytest

from journal_dl import notify, sites, tandf


class Tab:
    """Shows Cloudflare's 'Just a moment...' for a number of title() calls, then the real page."""
    def __init__(self, checks):
        self.left, self.closed = checks, False

    def title(self):
        self.left -= 1
        return "Just a moment..." if self.left >= 0 else "Search results | Taylor & Francis Online"

    def bring_to_front(self):
        pass

    def is_closed(self):
        return self.closed


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(sites.time, "sleep", lambda s: None)
    monkeypatch.setattr(notify, "send", lambda *a, **k: None)


def test_clears_by_itself():
    assert sites.wait_out_challenge(Tab(2), "Taylor & Francis", self_s=5, log=lambda *a: None)


def test_without_a_terminal_it_gives_up(monkeypatch):
    monkeypatch.setattr(sites.sys.stdin, "isatty", lambda: False, raising=False)
    assert not sites.wait_out_challenge(Tab(10**9), "T&F", self_s=0, wait_s=0, log=lambda *a: None)


def test_in_a_terminal_it_waits_for_the_user(monkeypatch):
    monkeypatch.setattr(sites.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.delenv("JOURNAL_DL_BACKGROUND", raising=False)
    said = []
    clock = iter(range(0, 10**6))
    monkeypatch.setattr(sites.time, "monotonic", lambda: next(clock))
    assert sites.wait_out_challenge(Tab(5), "T&F", self_s=0, wait_s=60, log=said.append)
    assert any("complete it yourself" in s for s in said)


def test_search_waits_then_searches_again(monkeypatch):
    site = sites.SITES["tandf"]
    calls = []

    def search_journals(tab, text):
        calls.append(text)
        if len(calls) == 1:
            raise tandf.ChallengeRequired("https://www.tandfonline.com/action/doSearch")
        return [{"title": "Personnel Psychology"}]
    monkeypatch.setattr(site.m, "search_journals", search_journals)
    monkeypatch.setattr(sites, "wait_out_challenge", lambda tab, label, **k: True)
    assert site.search(object(), "personnel") == ["Personnel Psychology"] and len(calls) == 2


def test_search_gives_up_cleanly(monkeypatch):
    site = sites.SITES["tandf"]

    def search_journals(tab, text):
        raise tandf.ChallengeRequired("x")
    monkeypatch.setattr(site.m, "search_journals", search_journals)
    monkeypatch.setattr(sites, "wait_out_challenge", lambda tab, label, **k: False)
    with pytest.raises(SystemExit, match="verify you are human"):
        site.search(object(), "personnel")
