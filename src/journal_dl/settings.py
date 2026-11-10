# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""User settings (settings.json in the config folder): archive folder, library proxy, browser.

Set them with `journal-dl --setup`. Example for an institution that uses an EZproxy:

    {"output": "D:/Journals", "proxy": "proxy.library.example.edu",
     "login_hosts": ["login.example.edu"], "institution_name": "Example University"}
"""
import json
import os
from pathlib import Path

from . import paths

DEFAULTS = {
    "output": None,                 # None -> <Documents>/Journal Downloads
    "proxy": "",                    # EZproxy host, e.g. "proxy.library.example.edu"; "" = no proxy (campus / VPN)
    "access": "auto",               # with a proxy set: "auto" = go direct when the publisher already recognises
                                    # your institution (campus / VPN), else the proxy; "proxy" / "direct" = always
    "login_hosts": [],              # the institution's sign-in host(s), to notice when a session has expired
    "institution_name": "",         # shown by Wiley when signed in ("" = don't check)
    "library_journal_search": "",   # library catalogue journal-search URL ending in the query text (for Ovid)
    "library_ovid_door": "",        # a journal the catalogue opens on Ovid (any one works)
    "chrome": None,                 # path to Chrome/Chromium/Edge; None = find it
    "cdp_port": 9333,               # local port of the downloader's own browser window
    "notify": True,                 # desktop notifications
    "ntfy_topic": "",               # optional: also push to this ntfy.sh topic (phone)
    "path_aliases": [],             # optional: [["/mnt/share", "H:"]] to also print paths as another PC sees them
}


def path() -> Path:
    return paths.config_dir() / "settings.json"


def exists() -> bool:
    return path().is_file()


def load() -> dict:
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(path().read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"(ignoring unreadable settings file {path()}: {e})")
    return s


def save(values: dict):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
    cur.update(values)
    tmp = p.with_suffix(".part")
    tmp.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    os.replace(tmp, p)


S = load()


def output_dir() -> Path:
    env = os.environ.get("JOURNAL_DL_OUTPUT") or os.environ.get("OVID_ARCHIVE_ROOT")
    if env:
        return Path(env)
    return Path(S["output"]) if S.get("output") else paths.default_output()


ACCESS_MODES = ("auto", "proxy", "direct")
_access_override = None             # --direct / --via-proxy for this run


def set_access_override(mode):
    global _access_override
    _access_override = mode


def access_mode() -> str:
    """How to reach the publishers this run: 'auto', 'proxy' or 'direct' ('direct' when no proxy is set)."""
    if not (S.get("proxy") or "").strip():
        return "direct"
    mode = _access_override or S.get("access") or "auto"
    return mode if mode in ACCESS_MODES else "auto"


def site_base(host: str, route: str) -> str:
    """Base address of a publisher site for route 'direct' or 'proxy'."""
    return f"https://{host}" if route == "direct" else proxied(host)


def proxied(host: str) -> str:
    """'www.tandfonline.com' -> 'https://www-tandfonline-com.proxy.example.edu' (EZproxy host naming)."""
    proxy = (S.get("proxy") or "").strip()
    return f"https://{host.replace('.', '-')}.{proxy}" if proxy else f"https://{host}"


def login_hints() -> tuple:
    hints = list(S.get("login_hosts") or [])
    if S.get("proxy"):
        hints.append(f"{S['proxy']}/login")
    return tuple(hints)


# ---------------------------------------------------------------- finding the library's proxy (--setup)
# Publisher sites a library typically sends you to; their EZproxy names look like www-tandfonline-com.<proxy>.
PUBLISHER_DOMAINS = ("wiley.com", "tandfonline.com", "ovid.com", "sciencedirect.com", "elsevier.com",
                     "springer.com", "nature.com", "sagepub.com", "jstor.org", "oup.com", "academic.oup.com",
                     "cambridge.org", "apa.org", "ebscohost.com", "proquest.com", "emerald.com", "lww.com")
_TLDS = {"com", "org", "net", "edu", "gov", "ac", "co", "info"}
_LOGIN_WORDS = ("login", "signin", "sso", "idp", "adfs", "shibboleth", "wayf", "auth", "cas")


def _is_publisher(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in PUBLISHER_DOMAINS)


def proxy_from_url(url: str):
    """The EZproxy host in a proxied address, or None:
    https://onlinelibrary-wiley-com.proxy.uba.uva.nl/doi/... -> 'proxy.uba.uva.nl'
    https://proxy.example.edu/login?url=https://... -> 'proxy.example.edu'."""
    from urllib.parse import urlsplit
    u = urlsplit(url or "")
    host = (u.hostname or "").lower()
    if not host or u.scheme not in ("http", "https"):
        return None
    if u.path.rstrip("/").endswith("/login") and "url=" in u.query:
        return host
    first, _, rest = host.partition(".")
    if "-" not in first or "." not in rest or _is_publisher(host):
        return None
    dotted = first.replace("--", "\0").replace("-", ".").replace("\0", "-")   # EZproxy writes '-' as '--'
    if _is_publisher(dotted) or dotted.rsplit(".", 1)[-1] in _TLDS:
        return rest
    return None


def login_host_from_url(url: str, proxy: str = ""):
    """The host of an institution sign-in page (login.example.edu, idp.example.edu/adfs/...), or None."""
    from urllib.parse import urlsplit
    u = urlsplit(url or "")
    host = (u.hostname or "").lower()
    if not host or _is_publisher(host) or (proxy and host.endswith(proxy)) or proxy_from_url(url):
        return None
    words = host.replace("-", ".").split(".") + u.path.lower().strip("/").split("/")[:2]
    return host if any(w.startswith(_LOGIN_WORDS) for w in words) else None


def detect_access(urls) -> tuple:
    """(proxy host or None, [sign-in hosts]) from the addresses seen while the user opened an article
    through the library. The most frequent proxy wins; sign-in hosts keep the order they were seen in."""
    counts = {}
    for u in urls:
        p = proxy_from_url(u)
        if p:
            counts[p] = counts.get(p, 0) + 1
    proxy = max(counts, key=counts.get) if counts else None
    logins = []
    for u in urls:
        h = login_host_from_url(u, proxy or "")
        if h and h not in logins:
            logins.append(h)
    return proxy, logins
