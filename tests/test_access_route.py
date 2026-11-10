# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Choosing between the library proxy and direct access (campus / VPN)."""
import pytest

from journal_dl import settings, site_runner, sites, tandf, wiley
from journal_dl.engine import Paused

PROXY = "proxy.library.example.edu"


@pytest.fixture
def with_proxy(monkeypatch):
    monkeypatch.setitem(settings.S, "proxy", PROXY)
    monkeypatch.setitem(settings.S, "access", "auto")
    monkeypatch.setattr(settings, "_access_override", None)


class FakeSiteModule:
    """Stands in for wiley / tandf: records page loads; 'recognised' says what the publisher shows."""
    LABEL, HOST = "Fake", "www.fake.example"

    def __init__(self, recognised=True, can_recognize=True, goto_error=None):
        self.ROUTE, self.BASE = "proxy", settings.proxied(self.HOST)
        self._recognised, self._can, self._error, self.loads = recognised, can_recognize, goto_error, []

    def use_route(self, route):
        self.ROUTE, self.BASE = route, settings.site_base(self.HOST, route)

    def can_recognize(self):
        return self._can

    def goto(self, page, path):
        self.loads.append(self.BASE + path)
        if self._error:
            raise self._error
        page.url = self.BASE + path

    def recognized(self, page):
        return self._recognised


class FakePage:
    url = "about:blank"

    def close(self):
        pass


def site_with(mod):
    s = sites.PublisherSite.__new__(sites.PublisherSite)
    s.m = mod
    return s


# ---------------------------------------------------------------- settings
def test_access_mode(monkeypatch, with_proxy):
    assert settings.access_mode() == "auto"
    monkeypatch.setitem(settings.S, "access", "proxy")
    assert settings.access_mode() == "proxy"
    monkeypatch.setitem(settings.S, "access", "nonsense")
    assert settings.access_mode() == "auto"
    settings.set_access_override("direct")
    assert settings.access_mode() == "direct"
    monkeypatch.setitem(settings.S, "proxy", "")
    settings.set_access_override("proxy")
    assert settings.access_mode() == "direct"          # no proxy set: nothing else is possible


def test_site_base(with_proxy):
    assert settings.site_base("www.tandfonline.com", "direct") == "https://www.tandfonline.com"
    assert settings.site_base("www.tandfonline.com", "proxy") == f"https://www-tandfonline-com.{PROXY}"


@pytest.mark.parametrize("mod, env", [(wiley, "WILEY_DL_BASE"), (tandf, "TANDF_DL_BASE")])
def test_adapter_use_route(monkeypatch, with_proxy, mod, env):
    monkeypatch.setattr(mod, "_FORCED_BASE", None)
    monkeypatch.setattr(mod, "BASE", mod.BASE)
    monkeypatch.setattr(mod, "ROUTE", mod.ROUTE)
    mod.use_route("direct")
    assert (mod.BASE, mod.ROUTE) == (f"https://{mod.HOST}", "direct")
    mod.use_route("proxy")
    assert mod.BASE.endswith(PROXY) and mod.ROUTE == "proxy"
    monkeypatch.setattr(mod, "_FORCED_BASE", "https://test.invalid")     # a forced base is never changed
    monkeypatch.setattr(mod, "BASE", "https://test.invalid")
    mod.use_route("direct")
    assert mod.BASE == "https://test.invalid"


def test_wiley_recognition_needs_institution_name(monkeypatch):
    page = type("P", (), {"evaluate": lambda self, js: "Welcome, Example University Library"})()
    monkeypatch.setitem(settings.S, "institution_name", "")
    assert not wiley.can_recognize() and not wiley.recognized(page)
    monkeypatch.setitem(settings.S, "institution_name", "Example University")
    assert wiley.can_recognize() and wiley.recognized(page)


# ---------------------------------------------------------------- route choice at the start of a run
def test_auto_goes_direct_when_recognised(with_proxy):
    m = FakeSiteModule(recognised=True)
    assert site_with(m).choose_route(FakePage(), quiet=True) == "direct"
    assert m.ROUTE == "direct" and m.loads == ["https://www.fake.example/"]


def test_auto_uses_proxy_when_not_recognised(with_proxy):
    m = FakeSiteModule(recognised=False)
    assert site_with(m).choose_route(FakePage(), quiet=True) == "proxy"
    assert m.ROUTE == "proxy"


def test_auto_uses_proxy_when_direct_check_fails(with_proxy):
    m = FakeSiteModule(goto_error=RuntimeError("bot check"))
    assert site_with(m).choose_route(FakePage(), quiet=True) == "proxy"


def test_auto_skips_check_when_site_cannot_tell(with_proxy):
    m = FakeSiteModule(can_recognize=False)
    assert site_with(m).choose_route(FakePage(), quiet=True) == "proxy"
    assert m.loads == []


@pytest.mark.parametrize("mode", ["proxy", "direct"])
def test_fixed_mode_never_checks(with_proxy, mode):
    settings.set_access_override(mode)
    m = FakeSiteModule(recognised=(mode == "proxy"))
    assert site_with(m).choose_route(FakePage(), quiet=True) == mode
    assert m.loads == []


def test_forced_base_is_left_alone(with_proxy):
    m = FakeSiteModule()
    m.ROUTE = "custom"
    assert site_with(m).choose_route(FakePage(), quiet=True) == "custom"
    assert m.loads == []


# ---------------------------------------------------------------- losing direct access mid-run
class FakeCtx:
    def new_page(self):
        return FakePage()


def runner_for(mod, status=403):
    r = site_runner.SiteRunner.__new__(site_runner.SiteRunner)
    mod.ChallengeRequired = type("ChallengeRequired", (Exception,), {})
    mod.AuthRequired = type("AuthRequired", (Exception,), {})
    mod.is_challenge = lambda *a: False
    mod.login_hints = lambda: ()
    mod.NAME = "fake"
    mod.fetch_pdf = lambda ctx, doi: (status, {"content-type": "text/html"}, b"<html>check access</html>",
                                      "https://www.fake.example/doi/x")
    r.site, r.ctx, r.LABEL = mod, FakeCtx(), mod.LABEL
    r.pacer = type("NoPacer", (), {"wait_page": lambda self: None})()
    r._recognized_at = float("-inf")
    return r


def test_direct_run_pauses_when_institution_no_longer_recognised(monkeypatch, with_proxy):
    monkeypatch.setattr(site_runner.notify, "send", lambda *a, **k: None)
    m = FakeSiteModule(recognised=False)
    m.use_route("direct")
    with pytest.raises(Paused, match="--resume"):
        runner_for(m)._fetch({"doi": "10.1/x"})


def test_direct_run_still_recognised_is_real_no_access(with_proxy):
    m = FakeSiteModule(recognised=True)
    m.use_route("direct")
    r = runner_for(m)
    assert r._fetch({"doi": "10.1/x"})["state"] == "access_denied"
    assert r._fetch({"doi": "10.1/y"})["state"] == "access_denied"
    assert len(m.loads) == 1                       # rechecked at most every RECHECK_S


def test_proxy_run_never_rechecks(with_proxy):
    m = FakeSiteModule(recognised=False)            # route stays "proxy"
    assert runner_for(m)._fetch({"doi": "10.1/x"})["state"] == "access_denied"
    assert m.loads == []
