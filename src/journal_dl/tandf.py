# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Taylor & Francis Online adapter, for tandf-dl (through the institution's EZproxy when one is set).

Same publishing platform as Wiley (stable URLs, PDFs via /doi/pdfdirect/<doi>). Observed 2026-11-09
through a university EZproxy:
- Signed-in pages say "Access provided by <institution>".
- Journals have short codes: /journals/pewo20. Site search /action/doSearch?AllField=..&content=journal
  links to them.
- Issue list /loi/<code>: one button.volume_link#vol_<vol>_<yyyy> per volume; clicking loads
  li > a.issue-link[href=/toc/<code>/<vol>/<iss>] + span.loiIssueCoverDateText (year only, no month)
  + span.loiIssuePages ("pages 161-314").
- Issue page /toc/<code>/<vol>/<iss>: all items on one page as .tocArticleEntry with span.article-type,
  .art_title, authors as a[href^=/author/Surname,+First], .tocPageRange, a PDF link (/doi/epdf/).
- T&F's own PDF viewer loads /doi/pdfdirect/<doi>.
- A cookie-consent layer (#transcend-consent-manager-tcf-ui) intercepts mouse clicks; it is left
  untouched (no consent given or refused): volume buttons are triggered in-page instead.
- Pages carry Cloudflare bot management. A challenge page is never bypassed: the run stops
  and asks the user to complete it in the browser.
"""
import os
import re
from urllib.parse import quote, unquote

from . import settings
from .wiley import (AdapterError, AuthRequired, ChallengeRequired, RateLimited, _norm_title,  # noqa: F401
                    is_challenge, login_hints, norm, title_matches)

HOST = "www.tandfonline.com"
_FORCED_BASE = os.environ.get("TANDF_DL_BASE")
BASE = _FORCED_BASE or settings.proxied(HOST)
ROUTE = "custom" if _FORCED_BASE else ("proxy" if settings.S.get("proxy") else "direct")
NAME, LABEL, HOST_HINT, PROG = "tandf", "Taylor & Francis", "tandfonline", "tandf-dl"
HAS_MONTHS = False
EXAMPLE_JOURNAL, EXAMPLE_YEAR, EXAMPLE_MONTH = "European Journal of Work and Organizational Psychology", 2025, 1
EXAMPLE_ISSUE, EXAMPLE_SEARCH = "34(2)", "work and organizational"
ITEM_S = 9.0                      # the viewer tab makes each download slower than Wiley's


def use_route(route):
    """Reach T&F directly ('direct') or through the library proxy ('proxy'). TANDF_DL_BASE always wins."""
    global BASE, ROUTE
    if not _FORCED_BASE:
        BASE, ROUTE = settings.site_base(HOST, route), route


def can_recognize():
    return True


def goto(page, path, settle=1500):
    url = path if path.startswith("http") else BASE + path
    resp = page.goto(url, wait_until="load", timeout=60000)
    page.wait_for_timeout(settle)
    if any(h in page.url for h in login_hints()):
        raise AuthRequired(f"sign-in page: {page.url.split('?')[0]}")
    if page.title().strip().lower().startswith("just a moment") or \
            (resp is not None and is_challenge(resp.status, resp.headers, page.content()[:20000])):
        raise ChallengeRequired(url)
    if resp is not None and resp.status in (429, 503):
        raise RateLimited(resp.status, resp.headers.get("retry-after"))
    if resp is not None and resp.status >= 400:
        raise AdapterError(f"HTTP {resp.status} for {url.split('?')[0]}")
    return resp


def signed_in(page):
    try:
        return "Access provided by" in page.inner_text("body")[:8000]
    except Exception:
        return False


recognized = signed_in      # T&F names the institution ("Access provided by ...") only when it recognises it


# ---------------------------------------------------------------- journals
def search_journals(page, text, limit=50):
    goto(page, f"/action/doSearch?AllField={quote(text)}&content=journal&pageSize={limit}")
    rows = page.evaluate(r"""() => {
        const out = [], seen = new Set();
        for (const a of document.querySelectorAll('a[href^="/journals/"]')) {
            const t = a.innerText.trim().replace(/\s+/g, ' ');
            const id = (a.getAttribute('href').match(/^\/journals\/([a-z]+\d{2})\b/) || [])[1];
            if (t && id && !seen.has(id)) { seen.add(id); out.push({title: t, id}); }
        }
        return out; }""")
    return [r for r in rows if title_matches(text, r["title"])]


def pick_journal(page, text):
    rows = search_journals(page, text)
    exact = [r for r in rows if _norm_title(r["title"]) == _norm_title(text)]
    if exact:
        return True, exact[0]
    if len(rows) == 1:
        return True, rows[0]
    return False, [r["title"] for r in rows]


def journal_info(page, code):
    goto(page, f"/loi/{code}")
    m = re.match(r"\s*List of issues\s+(.+?)\s*$", page.title())
    if not m:
        raise AdapterError(f"/loi/{code} is not a Taylor & Francis issue list ({page.title()!r})")
    vols = page.evaluate(r"""() => [...document.querySelectorAll('button.volume_link')].map(b => b.id)""")
    years = sorted({int(y) for v in vols for y in re.findall(r"^vol_[^_]+_(\d{4})$", v)})
    if not years:
        raise AdapterError("no volumes found on the journal's issue list")
    issn = re.search(r"ISSN[^0-9]{0,30}(\d{4}-\d{3}[\dX])", page.inner_text("body"))   # only a labelled ISSN
    vol_years = {}
    for v in vols:
        mm = re.match(r"^vol_([^_]+)_(\d{4})$", v)
        if mm:
            vol_years.setdefault(mm.group(1), int(mm.group(2)))
    return {"title": norm(m.group(1)), "issn": issn.group(1) if issn else None, "id": code,
            "years": f"{years[0]}-{years[-1]}", "year_list": years, "vol_years": vol_years}


def list_issues(page, code, year):
    """Open the volume(s) of that year (in-page click; the consent layer is not touched)."""
    import time
    if f"/loi/{code}" not in page.url:
        goto(page, f"/loi/{code}")
    vols = page.evaluate(r"""(y) => [...document.querySelectorAll('button.volume_link')]
                                    .filter(b => b.id.endsWith('_' + y)).map(b => b.id)""", str(year))
    out = []
    for vid in vols:
        vol = vid.split("_")[1]
        if page.get_attribute(f"#{vid}", "aria-expanded") != "true":
            page.evaluate("(id) => document.getElementById(id).click()", vid)
        end = time.monotonic() + 20
        while time.monotonic() < end:
            page.wait_for_timeout(400)
            n = page.evaluate("(p) => document.querySelectorAll(`a.issue-link[href^='${p}']`).length",
                              f"/toc/{code}/{vol}/")
            if n:
                break
        else:
            raise AdapterError(f"volume {vol} ({year}) did not load its issues")
        rows = page.evaluate(r"""(p) => [...document.querySelectorAll(`a.issue-link[href^='${p}']`)].map(a => {
            const li = a.closest('li') || a.parentElement;
            const q = s => (li.querySelector(s) || {}).innerText || '';
            return {href: a.getAttribute('href'), text: a.innerText.trim(),
                    year: q('.loiIssueCoverDateText'), pages: q('.loiIssuePages'),
                    access: (li.querySelector('.part-tooltip') || {}).innerText || ''}; })""", f"/toc/{code}/{vol}/")
        seen = set()
        for r in rows:
            m = re.match(rf"/toc/{code}/([^/]+)/([^/?#]+)", r["href"])
            if not m or m.group(0) in seen:
                continue
            seen.add(m.group(0))
            iss = norm(re.sub(r"^Issue\s+", "", r["text"])) or m.group(2)
            y = norm(r["year"]) or str(year)
            pages = norm(r["pages"]).replace("pages", "").strip()
            out.append({"year": str(year), "volume": m.group(1), "issue": iss, "link_text": r["text"],
                        "link_title": f"Vol {m.group(1)} {y} Issue {iss}", "date_text": y,
                        "page_range": pages, "key": f"v{m.group(1)}|i{iss}|{year}",
                        "toc": m.group(0)})
    return out


# ---------------------------------------------------------------- issue contents
ROWS_JS = r"""() => {
    const out = [];
    for (const n of document.querySelectorAll('.tocContent .tocArticleEntry')) {   // not the side widgets
        if (n.querySelector('.tocArticleEntry')) continue;
        const t = n.querySelector('.art_title a, .art_title');
        const link = n.querySelector('.art_title a[href^="/doi/"]') || n.querySelector('a[href^="/doi/"]');
        const authors = [...new Set([...n.querySelectorAll('a[href^="/author/"]')]
                           .map(a => decodeURIComponent(a.getAttribute('href').slice(8)).replace(/\+/g, ' ')))];
        const pages = ((n.querySelector('.tocPageRange') || {}).innerText || '').replace(/Pages?:\s*/, '').trim();
        const pdf = [...n.querySelectorAll('a')].some(a => /\/doi\/(e?pdf|pdfdirect)\//.test(a.getAttribute('href') || ''));
        const acc = n.querySelector('.access-icon, [class*=accessIcon]');
        out.push({href: link ? link.getAttribute('href') : null, title: t ? t.innerText.trim() : '',
                  type: ((n.querySelector('.article-type') || {}).innerText || '').trim(),
                  authors, pages: pages || null, pdf,
                  access: acc ? (acc.getAttribute('aria-label') || acc.className) : ''});
    }
    return out; }"""


def parse_issue(page, issue):
    goto(page, issue["toc"])
    raw = page.evaluate(ROWS_JS)
    if not raw:
        raise AdapterError(f"no articles found on {issue['toc']} (page layout changed?)")
    out, seen = [], set()
    for r in raw:
        m = re.match(r"/doi/(?:abs/|full/|epdf/|pdf/)?(10\.[^?#]+)", r["href"] or "")
        if not m:
            raise AdapterError(f"article row without DOI: {norm(r['title'])[:80]!r}")
        doi = unquote(m.group(1))
        if doi in seen:
            continue
        seen.add(doi)
        out.append({"sequence": len(out) + 1, "provider_id": doi, "doi": doi, "title": norm(r["title"]),
                    "pages": r["pages"], "authors": "; ".join(norm(a) for a in r["authors"]) or None,
                    "content_type": norm(r["type"]).strip(" |") or None, "access": norm(r["access"]),
                    "has_pdf": bool(r["pdf"])})
    return out


def pdf_url(doi):
    return f"{BASE}/doi/epdf/{doi}"


def fetch_pdf(ctx, doi, timeout_s=45):
    """-> (status, headers, body, final_url).
    T&F's viewer (/doi/epdf/<doi>) requests /doi/pdfdirect/<doi>?hmac=... with a one-time signature it
    generates itself. We open that viewer in its own tab, take the request it makes, and fetch the same
    signed address in the signed-in session (with the viewer as referrer). No URL is constructed by us."""
    import time
    viewer = pdf_url(doi)
    tab = ctx.new_page()
    seen = []
    tab.on("request", lambda r: seen.append(r) if "/doi/pdfdirect/" in r.url else None)
    try:
        resp = tab.goto(viewer, wait_until="load", timeout=60000)
        if any(h in tab.url for h in login_hints()):
            raise AuthRequired("institution session expired")
        if tab.title().strip().lower().startswith("just a moment") or \
                (resp is not None and is_challenge(resp.status, resp.headers, tab.content()[:20000])):
            raise ChallengeRequired(viewer)
        if resp is not None and resp.status in (429, 503):
            return resp.status, resp.headers, b"", tab.url
        end = time.monotonic() + timeout_s
        while not seen and time.monotonic() < end:
            tab.wait_for_timeout(400)
        if not seen:
            body = tab.content().encode()[:20000]
            return (resp.status if resp else 0), {"content-type": "text/html"}, body, tab.url
        signed = seen[0].url
    finally:
        tab.close()
    r = ctx.request.get(signed, headers={"Referer": viewer}, timeout=120000)
    return r.status, r.headers, r.body(), r.url
