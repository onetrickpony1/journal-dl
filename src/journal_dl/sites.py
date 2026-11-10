# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""The three sites behind one interface, so every command works the same way on each.

    site.session(p)          -> (ctx, tab) signed in (waits for the user to sign in if needed)
    site.search(tab, text)   -> [journal titles]
    site.pick(tab, text)     -> (True, {"title", "id"}) or (False, [close matches])
    site.runner(ctx, store, root, **kw)
"""
import time
from urllib.parse import quote

from . import browser, ovid, paths, settings, signin, tandf, wiley

SIGNIN_WAIT_S = 30 * 60


class Site:
    name = label = prog = ""
    has_months = True
    example_journal = example_issue = example_search = ""
    example_year, example_month = 2026, 1
    AdapterError = RuntimeError

    @property
    def db(self):
        return paths.data_dir() / f"{self.name}.sqlite"


# ---------------------------------------------------------------- Ovid
OVID_HOST = "ovidsp.ovid.com"
OVID_START = "/ovidweb.cgi?T=JS&PAGE=main&NEWS=n"     # Ovid's start page; signs in by institution address


class OvidSite(Site):
    name, label, prog = "ovid", "Ovid", "ovid-dl"
    has_months = True
    example_journal, example_year, example_month = "Journal of Applied Psychology", 2026, 11
    example_issue, example_search = "November 2026", "applied psych"
    AdapterError = ovid.AdapterError

    @property
    def db(self):
        old = paths.data_dir() / "archive.sqlite"          # name used by the first versions
        return old if old.exists() else paths.data_dir() / "ovid.sqlite"

    @staticmethod
    def _tab(ctx):
        tabs = [t for t in ctx.pages if "ovidweb.cgi" in t.url]
        return tabs[-1] if tabs else None

    def session(self, p):
        ctx = browser.connect(p)
        signin.sign_in_once(ctx)
        tab = self._tab(ctx)
        if tab:
            try:
                if ovid.dismiss_timeout_notice(tab):     # the tab sat idle: make sure the session still works
                    tab.reload()
                    ovid.wait_ready(tab)
                ovid.check_auth(tab)
                return ctx, tab
            except ovid.AuthRequired:
                pass
        return ctx, self._through_library(ctx)

    def _through_library(self, ctx):
        """No Ovid tab yet: open Ovid through the library's journal search when one is set (any Ovid journal
        works as the door); else Ovid's own start page, through the proxy when there is one (Ovid recognises
        the institution by the proxy's or campus address); else wait for the user to open Ovid."""
        search, door = settings.S.get("library_journal_search"), settings.S.get("library_ovid_door")
        page = ctx.new_page()
        if search and door:
            page.goto(search + quote(door))
            try:
                link = page.get_by_text("Available Online").first
                link.wait_for(timeout=30000)
                link.click()
                print("Opening Ovid through the library; sign in in the browser window if asked "
                      "(waiting up to 30 min)...")
            except Exception:
                print("Open Ovid from your library's website in the browser window (waiting up to 30 min)...")
        else:
            route = "proxy" if signin.needed() else "direct"
            try:
                page.goto(settings.site_base(OVID_HOST, route) + OVID_START, wait_until="load", timeout=60000)
            except Exception:
                pass
            if not self._tab(ctx):
                print("Open Ovid through your library in the browser window, signing in if asked "
                      "(waiting up to 30 min). Tip: --setup can store your library's address.")
        end = time.monotonic() + SIGNIN_WAIT_S
        while time.monotonic() < end:
            time.sleep(2)
            tab = self._tab(ctx)          # watch every tab: the first one can be swapped for another
            if tab:
                try:
                    ovid.wait_ready(tab, 500)
                    if tab is not page and not page.is_closed():
                        page.close()
                    for t in ctx.pages:
                        if t.url == "about:blank" and len(ctx.pages) > 1:
                            t.close()
                    return tab
                except ovid.AuthRequired:
                    pass
        raise SystemExit("Ovid did not open (sign-in not completed?)")

    def search(self, tab, text):
        return ovid.journal_suggestions(tab, text)[0]

    def pick(self, tab, text):
        tab.bring_to_front()
        try:
            ok, res = ovid.open_journal(tab, text)
        except ovid.AuthRequired:              # an old tab whose Ovid session ran out: open a fresh one
            tab = self._through_library(tab.context)
            ok, res = ovid.open_journal(tab, text)
        if ok:
            res = dict(res, id=res["title"])
        return ok, res

    def signed_in(self, ctx):
        tab = self._tab(ctx)
        if not tab:
            return None
        try:
            ovid.check_auth(tab)
            return True
        except ovid.AuthRequired:
            return False

    def runner(self, ctx, store, root, **kw):
        from .runner import OvidRunner
        return OvidRunner(ctx, store, root, **kw)


# ---------------------------------------------------------------- Wiley / Taylor & Francis
class PublisherSite(Site):
    route = None            # last route chosen (for --doctor)

    def __init__(self, mod):
        self.m = mod
        self.name, self.label, self.prog = mod.NAME, mod.LABEL, mod.PROG
        self.has_months = mod.HAS_MONTHS
        self.example_journal, self.example_year, self.example_month = (mod.EXAMPLE_JOURNAL, mod.EXAMPLE_YEAR,
                                                                       mod.EXAMPLE_MONTH)
        self.example_issue, self.example_search = mod.EXAMPLE_ISSUE, mod.EXAMPLE_SEARCH
        self.AdapterError = mod.AdapterError

    def _tab(self, ctx):
        tabs = [t for t in ctx.pages if self.m.HOST_HINT in t.url]
        return tabs[-1] if tabs else None

    def choose_route(self, tab, quiet=False):
        """Pick how to reach the site for this run: directly when the publisher already recognises the
        institution (on campus or VPN), else through the library proxy. Decided once, at the start, so a run
        never switches mid-way (a lost connection pauses instead; see SiteRunner). Returns the route."""
        m = self.m
        if m.ROUTE == "custom":
            return "custom"
        mode = settings.access_mode()
        if mode in ("proxy", "direct"):
            m.use_route(mode)
            return mode
        if not m.can_recognize():
            m.use_route("proxy")
            if not quiet:
                print(f"{m.LABEL}: using the library proxy (set your institution's name with --setup to "
                      "go direct automatically on campus or VPN).")
            return "proxy"
        m.use_route("direct")
        try:
            m.goto(tab, "/")
            ok = m.recognized(tab)
        except Exception:               # sign-in page, bot check, network: not recognised directly
            ok = False
        route = "direct" if ok else "proxy"
        m.use_route(route)
        if not quiet:
            print(f"{m.LABEL}: " + ("your institution is recognised directly (campus or VPN), so the library "
                                    "proxy is not needed." if ok else
                                    f"going through the library proxy ({settings.S.get('proxy')})."))
        return route

    def _on_site(self, tab):
        return tab.url.startswith(self.m.BASE)

    def session(self, p):
        m = self.m
        ctx = browser.connect(p)
        signin.sign_in_once(ctx)
        tab = self._tab(ctx) or ctx.new_page()
        self.choose_route(tab)
        if not self._on_site(tab):
            try:
                m.goto(tab, "/")
            except m.AuthRequired:
                pass
            except m.ChallengeRequired:
                raise SystemExit(f"{m.LABEL} is showing a 'verify you are human' check. Complete it yourself in "
                                 "the browser window, then run the command again.")
        if not m.signed_in(tab):
            print(f"Sign in to {m.LABEL} through your institution in the browser window if asked "
                  "(waiting up to 30 min)...")
            from . import notify
            notify.send("Sign-in needed", f"Sign in to {m.LABEL} in the downloader's browser window.")
            end = time.monotonic() + SIGNIN_WAIT_S
            last_reload = time.monotonic()
            while time.monotonic() < end:
                time.sleep(3)
                try:
                    if m.HOST_HINT in tab.url and m.signed_in(tab):
                        break
                    # look again now and then, not every few seconds: a reload would wipe what the user is
                    # doing on the page (a cookie notice, a sign-in form opened from the site)
                    if (m.HOST_HINT in tab.url and not any(h in tab.url for h in m.login_hints())
                            and time.monotonic() - last_reload > 60):
                        tab.reload()
                        last_reload = time.monotonic()
                except Exception:
                    pass
            else:
                raise SystemExit(f"Not signed in to {m.LABEL}.")
        return ctx, tab

    def search(self, tab, text):
        return [r["title"] for r in self.m.search_journals(tab, text)]

    def pick(self, tab, text):
        return self.m.pick_journal(tab, text)

    def signed_in(self, ctx):
        tab = ctx.new_page()
        try:
            self.route = self.choose_route(tab, quiet=True)
            if not self._on_site(tab):
                self.m.goto(tab, "/")
            return self.m.signed_in(tab)
        except self.m.AuthRequired:
            return False
        except Exception:
            return None
        finally:
            tab.close()

    def runner(self, ctx, store, root, **kw):
        from .site_runner import SiteRunner
        return SiteRunner(ctx, store, root, site=self.m, **kw)


SITES = {"wiley": PublisherSite(wiley), "tandf": PublisherSite(tandf), "ovid": OvidSite()}
ORDER = ("wiley", "tandf", "ovid")          # journal-dl tries publishers' own sites first


def get(name):
    return SITES[name]
