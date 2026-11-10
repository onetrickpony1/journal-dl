# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""One sign-in for every site, and sign-in checks that see text a menu or cookie notice hides."""
import pytest

from journal_dl import notify, settings, signin, tandf

PROXY = "proxy.uba.uva.nl"


class Tab:
    """Goes to the sign-in page first; 'signs in' after a few polls."""
    def __init__(self, signed_in_after):
        self.url, self.polls, self.after, self.closed = "about:blank", 0, signed_in_after, False

    def goto(self, url, **kw):
        self.url = url if self.after == 0 else "https://login.uva.nl/adfs/ls/?SAMLRequest=x"

    def wait_for_timeout(self, ms):
        self.polls += 1
        if self.polls >= self.after:
            self.url = f"https://onlinelibrary-wiley-com.{PROXY}/"

    def bring_to_front(self):
        pass

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True


class Ctx:
    def __init__(self, tab):
        self.tab = tab

    def new_page(self):
        return self.tab


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setitem(settings.S, "proxy", PROXY)
    monkeypatch.setitem(settings.S, "login_hosts", ["login.uva.nl"])
    monkeypatch.setitem(settings.S, "access", "auto")
    monkeypatch.setattr(signin, "_done", False)
    monkeypatch.setattr(notify, "send", lambda *a, **k: None)


def test_already_signed_in_asks_nothing(proxy):
    said = []
    assert signin.sign_in_once(Ctx(Tab(0)), log=said.append)
    assert said == []


def test_one_sign_in_then_never_again(proxy):
    said, tab = [], Tab(3)
    assert signin.sign_in_once(Ctx(tab), log=said.append)
    assert any("Sign in once" in s for s in said) and tab.closed
    said.clear()
    assert signin.sign_in_once(Ctx(Tab(99)), log=said.append)      # second site of the same run: no question
    assert said == []


def test_gives_up_after_the_wait(proxy):
    assert not signin.sign_in_once(Ctx(Tab(10**9)), log=lambda *a: None, wait_s=0)


def test_no_proxy_or_direct_means_no_sign_in(proxy, monkeypatch):
    monkeypatch.setitem(settings.S, "access", "direct")
    assert not signin.needed() and signin.sign_in_once(Ctx(Tab(10**9)))
    monkeypatch.setitem(settings.S, "access", "auto")
    monkeypatch.setitem(settings.S, "proxy", "")
    assert not signin.needed()


def test_proxy_login_page_is_not_signed_in(proxy):
    assert not signin._through_proxy(f"https://{PROXY}/login?url=https://onlinelibrary.wiley.com/", PROXY)
    assert signin._through_proxy(f"https://www-tandfonline-com.{PROXY}/toc/x/1/1", PROXY)


def test_tandf_sees_hidden_access_line():
    # T&F keeps "Access provided by ..." in a closed menu: invisible to inner_text, present in the page
    page = type("P", (), {"evaluate": lambda self, js: "Log in ... Access provided by UVA Universiteitsbibliotheek SZ",
                          "inner_text": lambda self, sel: "Log in"})()
    assert tandf.signed_in(page)
