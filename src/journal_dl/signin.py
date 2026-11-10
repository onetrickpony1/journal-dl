# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""One institution sign-in for every site.

With a library proxy, every site goes through the same proxy, and the proxy's sign-in covers all of
them. So instead of each site waiting for its own sign-in, the first site of a run opens one proxied
page: when the proxy sends it to the institution's sign-in page, the user signs in there once, and
every site then works. Nothing is typed or clicked for the user; journal-dl only watches where the
tab ends up.
"""
import time
from urllib.parse import urlsplit

from . import settings

WAIT_S = 30 * 60
_done = False                   # once per run: the proxy's sign-in lasts much longer than a run


def _through_proxy(url: str, proxy: str) -> bool:
    """True on a site reached through the proxy (not the proxy's own login page, not a sign-in page)."""
    host = (urlsplit(url).hostname or "").lower()
    return host.endswith("." + proxy) and not any(h in url for h in settings.login_hints())


def needed() -> bool:
    return bool((settings.S.get("proxy") or "").strip()) and settings.access_mode() != "direct"


def sign_in_once(ctx, log=print, wait_s=WAIT_S) -> bool:
    """Make sure the library proxy is signed in, asking the user once if not. True when signed in
    (or when no proxy is used)."""
    global _done
    if _done or not needed():
        return True
    proxy = settings.S["proxy"].strip()
    tab = ctx.new_page()
    try:
        try:
            tab.goto(settings.proxied("onlinelibrary.wiley.com") + "/", wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        if not _through_proxy(tab.url, proxy):
            from . import notify
            log("\n*** Sign in once with your institution in the journal-dl browser window "
                f"(it covers every site; waiting up to {wait_s // 60} min) ***")
            notify.send("Sign in once", "Sign in with your institution in the journal-dl browser window.")
            try:
                tab.bring_to_front()
            except Exception:
                pass
            end = time.monotonic() + wait_s
            while not _through_proxy(tab.url, proxy):
                if time.monotonic() > end or tab.is_closed():
                    return False
                tab.wait_for_timeout(2000)
            log("Signed in.\n")
        _done = True
        return True
    finally:
        try:
            tab.close()
        except Exception:
            pass
