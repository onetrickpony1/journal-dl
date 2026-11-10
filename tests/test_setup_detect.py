# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""--setup finding the library's proxy and sign-in page from the addresses the browser visited."""
from journal_dl import settings
from journal_dl.settings import detect_access, login_host_from_url, proxy_from_url


def test_proxy_from_hostname_style_address():
    assert proxy_from_url("https://onlinelibrary-wiley-com.proxy.uba.uva.nl/doi/10.1111/peps.1") == "proxy.uba.uva.nl"
    assert proxy_from_url("https://www-tandfonline-com.ezproxy.lib.example.edu/toc/x/1/1") == "ezproxy.lib.example.edu"
    assert proxy_from_url("https://ovidsp-dc1-ovid-com.proxy.example.ac.uk/ovidweb.cgi") == "proxy.example.ac.uk"


def test_proxy_from_path_style_login():
    assert proxy_from_url("https://proxy.example.edu/login?url=https://onlinelibrary.wiley.com/") == "proxy.example.edu"


def test_ordinary_addresses_are_not_proxies():
    for u in ("https://onlinelibrary.wiley.com/doi/10.1/x", "https://www.tandfonline.com/", "about:blank",
              "https://lib-guides.example.edu/", "https://www.my-site.example.org/", "chrome://newtab/",
              "https://login.uva.nl/adfs/ls/?SAMLRequest=x"):
        assert proxy_from_url(u) is None, u


def test_login_hosts():
    assert login_host_from_url("https://login.uva.nl/adfs/ls/?SAMLRequest=abc") == "login.uva.nl"
    assert login_host_from_url("https://idp.example.edu/idp/profile/SAML2/Redirect/SSO") == "idp.example.edu"
    assert login_host_from_url("https://onlinelibrary.wiley.com/action/showLogin") is None    # the publisher's own
    assert login_host_from_url("https://www.example.edu/library") is None


def test_detect_from_a_visit():
    seen = ["about:blank", "https://www.uva.nl/en/library", "https://proxy.uba.uva.nl/login?url=https://onlinelibrary.wiley.com/doi/x",
            "https://login.uva.nl/adfs/ls/?SAMLRequest=abc", "https://login.uva.nl/adfs/ls/?SAMLRequest=abc",
            "https://onlinelibrary-wiley-com.proxy.uba.uva.nl/doi/x", "https://onlinelibrary-wiley-com.proxy.uba.uva.nl/doi/x"]
    assert detect_access(seen) == ("proxy.uba.uva.nl", ["login.uva.nl"])
    assert detect_access(["https://onlinelibrary.wiley.com/"]) == (None, [])


def test_detected_proxy_matches_how_journal_dl_builds_addresses(monkeypatch):
    monkeypatch.setitem(settings.S, "proxy", "proxy.uba.uva.nl")
    assert proxy_from_url(settings.proxied("onlinelibrary.wiley.com") + "/doi/x") == "proxy.uba.uva.nl"
