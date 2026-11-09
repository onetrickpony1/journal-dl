# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Wiley Online Library adapter, for wiley-dl (through the institution's EZproxy when one is set).

Observed 2026-11-09 through a university EZproxy:
- Signed-in pages show the institution's name; no bot check.
- Journals are identified by their e-ISSN without hyphen: /journal/10991379.
- Years: /loi/<id> links to /loi/<id>/year/<yyyy>; that page lists issues as
  a[href=/toc/<id>/<yyyy>/<vol>/<iss>] "Volume 47, Issue 9" + "Pages: 1477-1711 November 2026".
- Early View is /toc/<id>/0/0 (not an issue; skipped).
- Issue page: every article on one page as .issue-item (title, authors, pages, DOI link,
  access label Free/Full/Open Access); a row can appear twice (de-duplicated by DOI).
- PDF: Wiley's own viewer (/doi/epdf/<doi>) loads /doi/pdfdirect/<doi>; fetched in the
  signed-in browser context it returns the PDF.
Unlike Ovid, all of these are stable addresses, so navigation is by URL.
"""
import os
import re
from urllib.parse import quote

from . import settings

BASE = os.environ.get("WILEY_DL_BASE") or settings.proxied("onlinelibrary.wiley.com")
NAME, LABEL, HOST_HINT, PROG = "wiley", "Wiley", "onlinelibrary", "wiley-dl"
HAS_MONTHS = True
EXAMPLE_JOURNAL, EXAMPLE_YEAR, EXAMPLE_MONTH = "Journal of Organizational Behavior", 2026, 10
EXAMPLE_ISSUE, EXAMPLE_SEARCH = "October 2026", "organizational behavior"
ITEM_S = 4.0                      # typical seconds one PDF download takes


def login_hints():
    return settings.login_hints()


class AdapterError(RuntimeError):
    pass


class AuthRequired(RuntimeError):
    pass


class ChallengeRequired(RuntimeError):
    """A bot check (CAPTCHA / 'verify you are human') is showing: never bypassed, the user handles it."""


def is_challenge(status, headers, body_start=b""):
    h = {k.lower(): v for k, v in (headers or {}).items()}
    if h.get("cf-mitigated") == "challenge":
        return True
    t = body_start[:20000].decode("utf-8", "ignore").lower() if isinstance(body_start, bytes) else str(body_start).lower()
    return status in (403, 503) and ("just a moment" in t or "verify you are human" in t or "cf-chl" in t)


def norm(s):
    return " ".join((s or "").replace("\xa0", " ").split())


def _norm_title(s):
    return re.sub(r"[^a-z0-9&]+", " ", norm(s).lower()).strip()


def title_matches(text, title):
    """Every word typed starts a word of the title ('org behav' matches 'Organizational Behavior').
    The sites' own search is broad (it matches article text too), so results are filtered by this."""
    have = _norm_title(title).split()
    return all(any(h.startswith(w) for h in have) for w in _norm_title(text).split() if w not in ("of", "the", "and", "&"))


def goto(page, path, settle=1200):
    url = path if path.startswith("http") else BASE + path
    resp = page.goto(url, wait_until="load", timeout=60000)
    page.wait_for_timeout(settle)
    check_auth(page)
    if resp is not None and is_challenge(resp.status, resp.headers, page.content()[:20000]):
        raise ChallengeRequired(url)
    if page.title().strip().lower().startswith("just a moment"):
        raise ChallengeRequired(url)
    if resp is not None and resp.status in (429, 503):
        raise RateLimited(resp.status, resp.headers.get("retry-after"))
    if resp is not None and resp.status >= 400:
        raise AdapterError(f"HTTP {resp.status} for {url.split('?')[0]}")
    return resp


class RateLimited(RuntimeError):
    def __init__(self, status, retry_after=None):
        super().__init__(f"HTTP {status}")
        self.retry_after = retry_after


def check_auth(page):
    if any(h in page.url for h in login_hints()) or page.title().strip().lower() in ("sign in", "login"):
        raise AuthRequired(f"sign-in page: {page.url.split('?')[0]}")


def signed_in(page):
    """True when Wiley shows the institution's name on this page (or, with no name set, when this is
    not a sign-in page)."""
    name = (settings.S.get("institution_name") or "").strip()
    try:
        if any(h in page.url for h in login_hints()):
            return False
        return name.lower() in page.inner_text("body")[:8000].lower() if name else True
    except Exception:
        return False


# ---------------------------------------------------------------- journals
def search_journals(page, text, limit=50):
    goto(page, f"/action/showPublications?PubType=journal&pageSize={limit}&AllField={quote(text)}")
    rows = page.evaluate(r"""() => {
        const out = [], seen = new Set();
        for (const a of document.querySelectorAll('a[href^="/journal/"]')) {
            const t = a.innerText.trim().replace(/\s+/g, ' ');
            const id = (a.getAttribute('href').match(/^\/journal\/([0-9xX]{8})/) || [])[1];
            if (t && id && !seen.has(id)) { seen.add(id); out.push({title: t, id}); }
        }
        return out; }""")
    return [r for r in rows if title_matches(text, r["title"])]


def pick_journal(page, text):
    """(True, {'title','id'}) for an exact title or a single match, else (False, candidates)."""
    rows = search_journals(page, text)
    exact = [r for r in rows if _norm_title(r["title"]) == _norm_title(text)]
    if exact:
        return True, exact[0]
    if len(rows) == 1:
        return True, rows[0]
    return False, [r["title"] for r in rows]


def issn(jid):
    j = jid.upper()
    return f"{j[:4]}-{j[4:]}"


def journal_info(page, jid):
    goto(page, f"/loi/{jid}")
    title = norm(page.title().split(":")[0].split(" - Wiley")[0])
    if not title or "List of Issues" not in page.title():
        raise AdapterError(f"/loi/{jid} is not a Wiley journal issue list")
    years = sorted({int(y) for y in re.findall(rf"/loi/{jid}/year/(\d{{4}})", page.content())})
    if not years:
        raise AdapterError("no years found on the journal's issue list")
    vol_years = {}
    for y, v in re.findall(r"(\d{4})\s*-\s*Volume\s+(\S+)", page.inner_text("body")):
        vol_years.setdefault(v, int(y))
    return {"title": title, "issn": issn(jid), "id": jid, "years": f"{years[0]}-{years[-1]}",
            "year_list": years, "vol_years": vol_years}


_PERIOD = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
           r"Spring|Summer|Autumn|Fall|Winter)")


def issue_date(text):
    """'Pages: 305-456 Autumn (Fall) 2026' -> 'Autumn 2026'; 'January/February 2026' kept as is."""
    m = re.search(rf"({_PERIOD}(?:\s*[/-]\s*{_PERIOD})?)(?:\s*\([A-Za-z]+\))?\s+(\d{{4}}(?:\s*/\s*\d{{2,4}})?)", text or "")
    if not m:
        return None
    period = re.sub(r"\s*([/-])\s*", r"\1", m.group(1))
    return f"{period} {m.group(2).replace(' ', '')}"


def list_issues(page, jid, year):
    goto(page, f"/loi/{jid}/year/{year}")
    rows = page.evaluate(r"""(prefix) => {
        const out = [], seen = new Set();
        for (const a of document.querySelectorAll(`a[href^="${prefix}"]`)) {
            const h = a.getAttribute('href'), t = a.innerText.trim().replace(/\s+/g, ' ');
            if (!t || seen.has(h)) continue;
            seen.add(h);
            // the issue's own card; older layouts: climb until the "Pages:" line (never past the list)
            let c = a.closest('.loi__issue, li.card');
            if (!c) {
                c = a.parentElement;
                for (let i = 0; i < 4 && c && !/Pages?:/.test(c.innerText) && !c.matches('ul, ol'); i++) c = c.parentElement;
            }
            out.push({href: h, text: t, ctx: c ? c.innerText.replace(/\s+/g, ' ') : ''});
        }
        return out; }""", f"/toc/{jid}/{year}/")
    out = []
    for r in rows:
        m = re.search(rf"/toc/{jid}/(\d{{4}})/([^/]+)/([^/?#]+)", r["href"])
        if not m or m.group(2) == "0":
            continue
        vol, iss = m.group(2), m.group(3)
        tm = re.match(r"Volume\s+(\S+),\s*Issue\s+(.+)$", r["text"])
        if tm:
            vol, iss = tm.group(1), tm.group(2)
        pages = re.search(r"Pages?:\s*([\w-]+(?:\s*-\s*[\w-]+)?)", r["ctx"])
        date_text = issue_date(r["ctx"]) or str(year)
        out.append({"year": str(year), "volume": vol, "issue": iss, "link_text": r["text"],
                    "link_title": f"Vol {vol} {date_text}", "date_text": date_text,
                    "page_range": pages.group(1).replace(" ", "") if pages else "",
                    "key": f"v{vol}|i{iss}|{date_text}", "toc": r["href"]})
    return out


# ---------------------------------------------------------------- issue contents
ROWS_JS = r"""() => {
    const out = [];
    let section = null;
    const nodes = document.querySelectorAll('h3.toc__heading, .issue-item');
    for (const n of nodes) {
        if (!n.classList.contains('issue-item')) {
            if (!n.closest('.issue-item')) section = n.innerText.trim();   // section heading, not an article title
            continue;
        }
        if (n.querySelector('.issue-item')) continue;     // a grouping box around real rows
        const link = n.querySelector('a[href^="/doi/"]');
        const title = n.querySelector('h2, h3, .issue-item__title');
        const acc = n.querySelector('.doi-access-wrapper, [class*=access-type]');
        const pages = (n.innerText.match(/Pages?:\s*([\w-]+(?:\s*-\s*[\w-]+)?)/) || [])[1] || null;
        const authors = [...new Set([...n.querySelectorAll('.loa .author-style, .comma__item .author-style, .loa a')]
                          .map(a => a.innerText.trim()).filter(Boolean))];
        const pdf = [...n.querySelectorAll('a')].some(a => /\/doi\/(e?pdf|pdfdirect)\//.test(a.getAttribute('href') || ''));
        out.push({href: link ? link.getAttribute('href') : null, title: title ? title.innerText.trim() : '',
                  access: acc ? acc.innerText.trim() : '', pages, authors, pdf, section});
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
        doi = m.group(1)
        if doi in seen:
            continue
        seen.add(doi)
        sec = norm(r["section"]).title() if r["section"] else None
        out.append({"sequence": len(out) + 1, "provider_id": doi, "doi": doi, "title": norm(r["title"]),
                    "pages": r["pages"], "authors": "; ".join(_surname_first(a) for a in r["authors"]) or None,
                    "content_type": sec, "access": r["access"],
                    "has_pdf": bool(r["pdf"])})
    return out


def _surname_first(name):
    """'Anna B. Smith' -> 'Smith, Anna B.' so file names use the surname like ovid-dl."""
    name = norm(name)
    if "," in name or " " not in name:
        return name
    first, last = name.rsplit(" ", 1)
    return f"{last}, {first}"


def pdf_url(doi):
    return f"{BASE}/doi/pdfdirect/{doi}?download=true"


def fetch_pdf(ctx, doi):
    """-> (status, headers, body, final_url). Wiley serves /doi/pdfdirect directly in the signed-in session."""
    resp = ctx.request.get(pdf_url(doi), timeout=120000)
    return resp.status, resp.headers, resp.body(), resp.url
