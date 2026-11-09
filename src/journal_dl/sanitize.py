# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Strip authentication material from anything written to logs/reports."""
import re
from urllib.parse import urlsplit, urlunsplit

_SECRET_HEADERS = {"cookie", "set-cookie", "authorization", "proxy-authorization"}


def url(u: str | None) -> str | None:
    """Keep scheme, host and path; drop query string and fragment (they carry sessions/signatures)."""
    if not u:
        return u
    p = urlsplit(u)
    # Ovid/EZproxy sometimes embed session ids in the path as ;jsessionid=...
    path = re.sub(r";(jsessionid|sid)=[^/;?]*", "", p.path, flags=re.I)
    # Ovid full-text PDF paths carry a one-time token segment: /ovftpdfs/<TOKEN>/...
    path = re.sub(r"(/ovftpdfs/)[^/]+", r"\1<token>", path)
    return urlunsplit((p.scheme, p.netloc, path, "", ""))


def ovid_an(u: str | None) -> str | None:
    """Ovid accession number from a full-text PDF path (e.g. 00132576-202112000-00001)."""
    m = re.search(r"/(\d{8}-\d{9}-\d{5})\.pdf", u or "")
    return m.group(1) if m else None


def headers(h: dict[str, str]) -> dict[str, str]:
    return {k: ("<redacted>" if k.lower() in _SECRET_HEADERS else v) for k, v in h.items()}


_SAFE_ID_PARAMS = {"an", "doi", "d", "issn", "volume", "issue", "page", "journal", "jid", "articleid", "aid"}
_SECRET_HINT = re.compile(r"sess|token|sig|key|auth|ticket|ezproxy|login|pass", re.I)


def id_params(u: str | None) -> dict[str, str]:
    """Identifier-looking query parameters worth keeping as stable source ids.
    Values are kept only for a safe list; everything session-like is dropped."""
    from urllib.parse import parse_qsl
    if not u:
        return {}
    out = {}
    for k, v in parse_qsl(urlsplit(u).query, keep_blank_values=False):
        if _SECRET_HINT.search(k):
            continue
        if k.lower() in _SAFE_ID_PARAMS:
            out[k] = v
    return out
