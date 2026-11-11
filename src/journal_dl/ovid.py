# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Ovid adapter: every Ovid-specific selector and rule lives here.

Observed 2026-11-09 on ovidsp (Journals > Table of Contents):
- Issue list: li.expandable per year, a.control toggles it (aria-expanded), issues are
  ul.issues > li > a.tlink ("Volume 20 (3)", title "Vol 20 September 2021") + span.journal-page-info.
- Issue heading text: "Volume 20(3) pgs. 151-215 September 2021".
- Article rows: table.toc-row; checkbox aria-label "Article N: <title>"; links carry
  Counter5=TOC_article|<AN>|ovft...; "PDF Full Text" link (PDFLink=...).
- Results pages: a[aria-label="Next Page"], a[aria-label="Current Page N"], select "Results Per Page".
- Issue URLs are session state, not addresses: navigate by clicking, then verify the heading.
"""
import re
from urllib.parse import unquote

HEADING_RE = re.compile(r"Volume\s+\S+\([^)]*\)[^\n]*?[A-Z][a-z]+\.?(?:/[A-Z][a-z]+)?\s+(?:\d{1,2},\s+)?\d{4}")
# Journals dated by year only (quarterlies such as the Journal of Personnel Psychology) have a heading like
# "Volume 25(4) pgs. 167-227 2026": no month; the year stands alone at the end of the line (so the end of a
# page range such as 1001-1999 can't pass for it).
HEADING_YEAR_RE = re.compile(r"^[ \t]*(Volume\s+\S+\([^)]*\)[^\n]*?\s(?:19|20)\d{2})[ \t]*$", re.M)
AN_RE = re.compile(r"Counter5=TOC_[a-z_]+%7c([0-9A-Za-z-]+)%7c|Counter5=TOC_[a-z_]+\|([0-9A-Za-z-]+)\|")
DOI_RE = re.compile(r"DOI:\s*(10\.\d{4,9}/\S+)", re.I)
PAGES_RE = re.compile(r"^pgs?\.\s*(.+)$", re.M)


def _login_hosts():
    from . import settings
    return tuple(settings.S.get("login_hosts") or ()) + ("/login",)


class AdapterError(RuntimeError):
    """Page did not look like what we expect: stop, never treat as empty."""


class AuthRequired(RuntimeError):
    pass


def norm(s: str | None) -> str:
    return " ".join((s or "").replace("\xa0", " ").split())


def check_auth(page):
    u = page.url
    if any(h in u for h in _login_hosts()) or page.title().strip().lower() in ("sign in", "login"):
        raise AuthRequired(f"sign-in page: {u.split('?')[0]}")
    if "ovid" in u:
        body = page.inner_text("body")[:3000].lower()
        if "session has expired" in body or "your session has timed out" in body or "please log in" in body:
            raise AuthRequired("Ovid session expired")


def dismiss_timeout_notice(page):
    """Close Ovid's own 'Your Ovid session is going to timeout in 15 minutes' notice: its overlay blocks
    every click. Only this notice is closed; cookie/consent banners are never touched."""
    try:
        box = page.locator("#alert-overlay-popup-box")
        if box.count() and box.first.is_visible() and "timeout" in box.first.inner_text().lower():
            box.first.locator(".wk-popup-header-close").first.click(timeout=5000)
            page.wait_for_timeout(500)
            return True
    except Exception:
        pass
    return False


def wait_ready(page, ms=1500):
    page.wait_for_load_state("load")
    page.wait_for_timeout(ms)
    dismiss_timeout_notice(page)
    check_auth(page)


# ---------------------------------------------------------------- journal & issue list
def journal_info(page):
    txt = page.inner_text("body")
    m = re.search(r"Journal Information\s*\n(?:.*\n)?\s*(.+?)\s*\((\d{4})-(\d{4})?\)\s*\n\s*ISSN:\s*([\dX-]+)", txt)
    if not m:
        title = norm(page.title().split(",", 1)[-1])
        issn = re.search(r"ISSN:\s*([\dX-]+)", txt)
        if not issn:
            raise AdapterError("not an Ovid journal table-of-contents page (no ISSN found)")
        return {"title": title, "issn": issn.group(1), "years": None}
    return {"title": norm(m.group(1)), "issn": m.group(4), "years": f"{m.group(2)}-{m.group(3) or ''}"}


YEARS_JS = r"""() => [...document.querySelectorAll('#journal_issue_list li.expandable')].map(y => {
    const c = y.querySelector(':scope > a.control');
    return {label: c ? c.getAttribute('aria-label') : '', expanded: c ? c.getAttribute('aria-expanded') : null,
            issues: [...y.querySelectorAll('ul.issues > li')].map(li => {
                const a = li.querySelector('a.tlink');
                const info = li.querySelector('.journal-page-info');
                return a ? {text: a.childNodes[0].textContent, title: a.title, info: info ? info.innerText : ''} : null;
            }).filter(Boolean)};
})"""


def _years(page):
    return page.evaluate(YEARS_JS)


def _label_year(label):
    m = re.match(r"\s*(\d{4})", label or "")
    return int(m.group(1)) if m else None


def expand_all_years(page, log=print, timeout_s=20, years=None):
    """Open year branches (only those inside `years`, if given). Each loads from the server, so wait
    until its issues appear and match the count in its label, e.g. '2019 (4)'."""
    import sys
    import time
    def wanted(label):
        y = _label_year(label)
        return years is None or y is None or years[0] <= y <= years[1]
    todo = [y for y in _years(page) if wanted(y["label"])]
    for n, y in enumerate(todo, 1):
        if y["issues"]:
            continue
        label = y["label"]
        if sys.stdout.isatty():
            print(f"\r   Reading issue list: {label:<12} ({n}/{len(todo)})", end="", flush=True)
        page.locator(f"#journal_issue_list li.expandable > a.control[aria-label='{label}']").first.click()
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            page.wait_for_timeout(400)
            cur = next((z for z in _years(page) if z["label"] == label), None)
            if cur and cur["issues"]:
                break
        else:
            raise AdapterError(f"year branch {label!r} did not load")
    if sys.stdout.isatty():
        print("\r" + " " * 60 + "\r", end="", flush=True)
    bad = []
    for y in _years(page):
        if not wanted(y["label"]):
            continue
        m = re.search(r"\((\d+)\)", y["label"] or "")
        if not y["issues"] or (m and int(m.group(1)) != len(y["issues"])):  # accordion: only one stays open
            bad.append(f"{y['label']}: {len(y['issues'])} issues shown")
    if bad:
        raise AdapterError("year branches incomplete: " + "; ".join(bad))


def list_issues(page):
    """All visible issues, newest first, with labels kept exactly as shown."""
    out = []
    for y in _years(page):
        year = norm(y["label"]).split(" ")[0]
        for it in y["issues"]:
            text, info = norm(it["text"]), norm(it["info"])
            m = re.match(r"Volume\s+(\S+)\s*\((.*)\)$", text)
            vol, iss = (m.group(1), m.group(2)) if m else (text, "")
            date_text, _, rng = info.partition(" - ")
            out.append({"year": year, "volume": vol, "issue": iss, "link_text": text,
                        "link_title": norm(it["title"]), "date_text": date_text,
                        "page_range": rng.replace("pg.", "").strip(),
                        "key": f"v{vol}|i{iss}|{date_text}"})
    if not out:
        raise AdapterError("issue list empty or not recognised")
    return out


def heading_in(text):
    """The issue heading in a TOC page's text: 'Volume 111(11) ... November 2026' or, for journals dated by
    year only, 'Volume 25(4) pgs. 167-227 2026'. None when there is none."""
    text = text.replace("\xa0", " ")
    m = HEADING_RE.search(text)
    if m:
        return norm(m.group(0))
    m = HEADING_YEAR_RE.search(text)
    return norm(m.group(1)) if m else None


def heading(page):
    return heading_in(page.inner_text("body"))


def expected_heading_prefix(issue):
    return f"Volume {issue['volume']}({issue['issue']})"


def on_issue(page, issue):
    h = heading(page) or ""
    return h.startswith(expected_heading_prefix(issue)) and issue["date_text"] in h


def open_issue(page, issue):
    dismiss_timeout_notice(page)
    if on_issue(page, issue):
        return
    yr = page.locator(f"#journal_issue_list li.expandable > a.control[aria-label^='{issue['year']} ']")
    if yr.count() and yr.first.get_attribute("aria-expanded") == "false":
        yr.first.click()
        page.wait_for_timeout(800)
    link = page.locator("#journal_issue_list ul.issues a.tlink", has_text=issue["link_text"])
    cand = [link.nth(i) for i in range(link.count())
            if norm(link.nth(i).get_attribute("title")) == issue["link_title"]]
    if not cand:
        raise AdapterError(f"issue link not found: {issue['link_text']} / {issue['link_title']}")
    cand[0].click()
    wait_ready(page)
    if not on_issue(page, issue):
        raise AdapterError(f"opened issue heading {heading(page)!r} != expected {issue['link_title']}")


# ---------------------------------------------------------------- results pages
def set_per_page(page, n=50):
    dismiss_timeout_notice(page)
    sel = page.locator("select[name='Results Per Page']")
    if not sel.count():
        return
    current = sel.first.evaluate("s => s.options[s.selectedIndex].text")
    if norm(current).startswith(str(n)):
        return
    opt = sel.first.evaluate(f"s => [...s.options].find(o => o.text.trim().startsWith('{n}'))?.value")
    if opt is None:
        return
    sel.first.select_option(opt)
    wait_ready(page)


def current_results_page(page):
    cur = page.locator("a[aria-label^='Current Page']")
    if not cur.count():
        return 1
    return int(re.search(r"\d+", cur.first.get_attribute("aria-label")).group(0))


def go_results_page(page, n):
    dismiss_timeout_notice(page)
    if current_results_page(page) == n:
        return
    link = page.locator(f"a[aria-label='Page {n}']")
    if not link.count():
        raise AdapterError(f"results page {n} link not shown")
    link.first.click()
    wait_ready(page)
    if current_results_page(page) != n:
        raise AdapterError(f"tried results page {n}, got {current_results_page(page)}")


def next_results_page(page):
    """Click Next Page; returns False when there is none."""
    dismiss_timeout_notice(page)
    nxt = page.locator("a[aria-label='Next Page']")
    if not nxt.count():
        return False
    before = current_results_page(page)
    nxt.first.click()
    wait_ready(page)
    if current_results_page(page) != before + 1:
        raise AdapterError(f"Next Page did not advance (still {current_results_page(page)})")
    return True


ROWS_JS = r"""() => [...document.querySelectorAll('table.toc-row')].map(r => {
    const cb = r.querySelector('input.bibrecord-checkbox');
    const links = [...r.querySelectorAll('a')].map(a => ({t: a.innerText.trim(), h: a.getAttribute('href') || ''}));
    const t = r.querySelector('a.citation_title + a, td.titles-record a.tlink:not(.citation_title)');
    return {aria: cb ? cb.getAttribute('aria-label') : null, text: r.innerText, links,
            title: t ? t.innerText.trim() : null};
})"""


def parse_rows(page):
    out = []
    for r in page.evaluate(ROWS_JS):
        seq_m = re.match(r"Article\s+(\d+):\s*(.*)", norm(r["aria"]))
        an = None
        for l in r["links"]:
            m = AN_RE.search(l["h"])
            if m:
                an = unquote(m.group(1) or m.group(2))
                break
        if not seq_m or not an:
            raise AdapterError(f"article row not recognised: {norm(r['text'])[:120]!r}")
        lines = [norm(x) for x in r["text"].split("\n") if norm(x)]
        doi = DOI_RE.search(r["text"])
        pages = PAGES_RE.search(r["text"])
        title = norm(r["title"]) or seq_m.group(2)
        # authors = line after DOI (or after pages when no DOI); content type = line before "PDF Full Text"/"Cite"
        authors = ctype = None
        anchor = next((i for i, x in enumerate(lines) if x.startswith("DOI:")), None)
        if anchor is None:
            anchor = next((i for i, x in enumerate(lines) if re.match(r"pgs?\.", x)), None)
        if anchor is not None and anchor + 1 < len(lines):
            nxt = lines[anchor + 1]
            if nxt not in ("PDF Full Text", "Cite", "Article"):
                authors = nxt
        stop = next((i for i, x in enumerate(lines) if x in ("PDF Full Text", "Cite")), None)
        if stop and stop - 1 >= 0 and lines[stop - 1] not in (authors, title) and not lines[stop - 1].startswith(("DOI:", "pg")):
            ctype = lines[stop - 1]
        out.append({
            "sequence": int(seq_m.group(1)), "provider_id": an, "title": title,
            "doi": doi.group(1).rstrip(".,;") if doi else None,
            "pages": pages.group(1) if pages else None, "authors": authors, "content_type": ctype,
            "has_pdf": any(l["t"] == "PDF Full Text" for l in r["links"]),
            "pdf_href": next((l["h"] for l in r["links"] if l["t"] == "PDF Full Text"), None),
        })
    return out


def page_signature(rows):
    return f"{rows[0]['provider_id']}..{rows[-1]['provider_id']}#{len(rows)}" if rows else "empty"


# ---------------------------------------------------------------- choosing a journal
def _norm_title(s):
    return re.sub(r"[^a-z0-9&]+", " ", norm(s).lower()).strip()


def goto_journals_page(page):
    dismiss_timeout_notice(page)
    page.get_by_role("link", name="Journals", exact=True).first.click()
    wait_ready(page)
    # Ovid remembers a folded sidebar ("Show" button) and folded panels; unfold both
    if page.locator("#titles-panel.closed").count():
        page.locator("#titles-panel-control").first.click()
        wait_ready(page)
    toggle = page.locator("a.ovid-vertical-widget-toggle-link[aria-label='Filter By Title']")
    if toggle.count() and toggle.first.get_attribute("aria-expanded") == "false":
        toggle.first.click()
        wait_ready(page)
    box = page.locator("#autocomplete-jn")
    box.first.wait_for(state="visible", timeout=15000)
    return box.first


def journal_suggestions(page, text):
    box = goto_journals_page(page)
    box.click()
    box.fill("")
    box.press_sequentially(text, delay=40)   # the suggestion list reacts to key presses
    opts = page.locator("ul.ui-autocomplete li")
    try:
        opts.first.wait_for(state="visible", timeout=8000)
    except Exception:
        return [], opts
    page.wait_for_timeout(800)
    return [norm(opts.nth(i).inner_text()) for i in range(opts.count())], opts


def open_journal(page, title):
    """Open exactly this journal; returns (True, info) or (False, close matches)."""
    names, opts = journal_suggestions(page, title)
    want = _norm_title(title)
    idx = next((i for i, n in enumerate(names) if _norm_title(n) == want), None)
    if idx is None and len(names) == 1:
        idx = 0                                 # only one journal matches: take it
    if idx is None:
        return False, names
    want = _norm_title(names[idx])
    opts.nth(idx).click()                      # fills the box with the exact title
    page.wait_for_timeout(500)
    page.locator("input.journal_srch_btn").first.click()
    wait_ready(page, 2500)
    if not heading(page):                      # a filtered list: click the exact title
        hit = page.evaluate("""t => {const a=[...document.querySelectorAll('a')].findIndex(a =>
                 a.innerText.trim().toLowerCase().replace(/[^a-z0-9&]+/g,' ').trim() === t); return a}""", want)
        if hit >= 0:
            page.locator("a").nth(hit).click()
            wait_ready(page, 2500)
    if not heading(page):
        raise AdapterError(f"journal page for {names[idx]!r} did not show an issue table of contents")
    info = journal_info(page)
    if _norm_title(info["title"]) != want:
        raise AdapterError(f"opened {info['title']!r}, not {title!r}")
    return True, info
