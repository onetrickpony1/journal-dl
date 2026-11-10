# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""--doctor (is everything ready?) and --setup (archive folder, library proxy, browser)."""
import importlib.metadata as md
import shutil
import sys
import uuid
from pathlib import Path

from . import browser, engine, pacing, paths, settings, state, system

OK, WARN, BAD = "[ok]  ", "[!]   ", "[FAIL]"


def doctor(sites, a=None) -> int:
    problems = 0

    def line(mark, text):
        nonlocal problems
        if mark == BAD:
            problems += 1
        print(f"{mark} {text}")

    print("journal-dl check-up\n")
    v = sys.version_info
    line(OK if v >= (3, 10) else BAD, f"Python {v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 10) else " (needs 3.10+)"))
    for pkg in ("playwright", "pypdf"):
        try:
            line(OK, f"{pkg} {md.version(pkg)}")
        except md.PackageNotFoundError:
            line(BAD, f"{pkg} is not installed (pip install {pkg})")

    # settings
    line(OK if settings.exists() else WARN, f"settings: {settings.path()}" + ("" if settings.exists() else
                                                                            " (not created yet: run --setup)"))
    proxy = settings.S.get("proxy")
    line(OK if proxy else WARN, f"library proxy: {proxy} (access: {settings.access_mode()})" if proxy else
         "library proxy: none (works on campus or VPN only; set one with --setup)")

    # archive folder
    root = Path(a.output) if a and a.output else settings.output_dir()
    if root.is_dir():
        try:
            probe = root / f".journal-dl-write-test-{uuid.uuid4().hex[:6]}"
            probe.write_bytes(b"ok")
            probe.unlink()
            line(OK, f"archive folder: {system.show_path(root)}")
        except OSError as e:
            line(BAD, f"archive folder is not writable: {root} ({e})")
        free = shutil.disk_usage(root).free
        mark = OK if free > 20 * 1024**3 else (WARN if free > engine.MIN_FREE_BYTES else BAD)
        line(mark, f"free space there: {free / 1024**3:.0f} GB" +
             ("" if mark == OK else " (downloads pause below 5 GB)"))
    elif root == paths.default_output():
        line(WARN, f"archive folder: {root} (created on the first download)")
    else:
        line(BAD, f"archive folder not reachable: {root} (drive or share not connected? change with --setup)")

    # data / databases / locks
    d = paths.data_dir()
    line(OK, f"data folder: {d}")
    for site in sites:
        lock = site.db.with_suffix(".lock")
        busy = False
        if lock.exists():
            try:
                with engine.RunLock(lock):
                    pass
            except SystemExit:
                busy = True
        if busy:
            line(WARN, f"{site.label}: a download is running right now")

    # browser
    exe = browser.find_chrome()
    line(OK if exe else BAD, f"browser: {exe}" if exe else
         "no Chrome, Chromium or Edge found (install one, or run: journal-dl --install-browser)")
    if browser.alive():
        line(OK, f"browser window is open ({browser.cdp_url()})")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            ctx = p.chromium.connect_over_cdp(browser.cdp_url()).contexts[0]
            for site in sites:
                try:
                    s = site.signed_in(ctx)
                except Exception as e:
                    s = None
                    print(f"       ({site.label}: {str(e)[:80]})")
                route = getattr(site, "route", None)
                how = {"direct": " (directly: campus or VPN)", "proxy": " (through the library proxy)"}.get(route, "")
                if s is True:
                    line(OK, f"{site.label}: signed in{how}")
                elif s is False:
                    line(WARN, f"{site.label}: not signed in (it will ask you to sign in when needed)")
                else:
                    line(WARN, f"{site.label}: not open yet (opens through your library when needed)")
    else:
        line(WARN, "browser window not open (starts by itself; sign-ins are then checked)")

    # speed, follows, last run
    line(OK, f"speed: {pacing.load_default().describe()}")
    fl = state.follows()
    line(OK, f"followed journals: {len(fl)}; automatic updates: {system.schedule_status()}")
    lr = state.unfinished()
    if lr:
        line(WARN, f"unfinished run: {lr['journal']} (continue with --resume)")
    print("\nAll good." if not problems else f"\n{problems} problem(s) to fix.")
    return 1 if problems else 0


def _ask(label, cur):
    shown = cur if cur not in (None, "") else "none"
    v = input(f"{label} [{shown}]: ").strip()
    if not v:
        return cur
    return "" if v.lower() in ("none", "-") else v


def setup() -> int:
    s = settings.load()
    print("Press Enter to keep the value in [brackets]; type 'none' to clear one.\n")
    out = _ask("Archive folder (where PDFs go)", s.get("output") or str(paths.default_output()))
    print("\nLibrary access from off campus usually goes through an EZproxy address such as\n"
          "  proxy.library.example.edu  (look at the address bar after opening a journal through your library).")
    proxy = _ask("Library proxy host ('none' = on campus or VPN)", s.get("proxy"))
    access = s.get("access") or "auto"
    if (proxy or "").strip():
        print("\nOn campus or on VPN the proxy isn't needed. 'auto' checks at the start of each run whether the\n"
              "publisher already recognises your institution and then goes direct; 'proxy' or 'direct' = always.")
        while True:
            access = (_ask("Access (auto, proxy or direct)", access) or "auto").lower()
            if access in settings.ACCESS_MODES:
                break
            print("  type auto, proxy or direct")
    hosts = _ask("Sign-in page host(s), comma separated (e.g. login.example.edu)",
                 ", ".join(s.get("login_hosts") or []))
    inst = _ask("Your institution's name as Wiley shows it when signed in (also lets 'auto' go direct on "
                "Wiley; 'none' = don't check)",
                s.get("institution_name"))
    print("\nOvid is reached through the library catalogue. Optional:")
    lib = _ask("Library journal-search address ending in the search text", s.get("library_journal_search"))
    door = _ask("A journal your library sends to Ovid", s.get("library_ovid_door")) if lib else ""
    chrome = browser.find_chrome()
    if not chrome:
        chrome = _ask("Path to Chrome, Chromium or Edge (none found automatically)", s.get("chrome"))
    values = {"output": out, "proxy": (proxy or "").strip().removeprefix("https://").strip("/"), "access": access,
              "login_hosts": [h.strip() for h in (hosts or "").split(",") if h.strip()],
              "institution_name": inst or "", "library_journal_search": lib or "",
              "library_ovid_door": door or ""}
    if chrome and not browser.find_chrome():
        values["chrome"] = chrome
    settings.save(values)
    settings.S.update(values)
    out_p = Path(out)
    if not out_p.exists():
        try:
            out_p.mkdir(parents=True)
            print(f"created {out_p}")
        except OSError as e:
            print(f"(could not create {out_p}: {e})")
    print(f"\nSaved: {settings.path()}")
    return 0
