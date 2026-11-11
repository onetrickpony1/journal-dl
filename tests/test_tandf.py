# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Offline check of the Taylor & Francis readers against copies of the observed markup."""
from playwright.sync_api import sync_playwright

from journal_dl import tandf


def launch_chromium(p):
    """Installed Chrome when there is one (/opt/google/chrome), else Playwright's own Chromium."""
    try:
        return p.chromium.launch(channel="chrome", headless=True)
    except Exception:
        return p.chromium.launch(channel="chromium", headless=True)   # the full build --install-browser gets

TOC = """<html><body>
<div class="tocContent">
 <div class="articleEntry"><div class="tocArticleEntry include-metrics-panel"><span class="article-type">Editorial</span>
  <div class="art_title"><a href="/doi/full/10.1080/1.2025.1"><span>Learning: how it works</span></a></div>
  <div class="tocAuthors"><a href="/author/Kauffeld%2C+Simone">Simone Kauffeld</a> &amp; <a href="/author/Gra%C3%9Fmann%2C+Carolin">Carolin Graßmann</a></div>
  <div class="tocPageRange">Pages: 161-174</div><a class="pdf" href="/doi/epdf/10.1080/1.2025.1">PDF (566 KB)</a></div></div>
 <div class="articleEntry"><div class="tocArticleEntry"><span class="article-type">Research Article |</span>
  <div class="art_title"><a href="/doi/full/10.1080/1.2024.2"><span>A study</span></a></div>
  <div class="tocPageRange">Pages: 175-187</div><a href="/doi/epdf/10.1080/1.2024.2">PDF</a></div></div>
</div>
<div class="widget"><div class="article-list-container"><div class="articleEntry"><div class="tocArticleEntry">
  <div class="art_title"><a href="/doi/full/10.1080/1.2026.99">Latest article (side box)</a></div></div></div></div></div>
</body></html>"""

LOI = """<html><head><title>List of issues Journal X</title></head><body>
<button class="volume_link" id="vol_34_2025" aria-expanded="true">Volume 34 2025</button>
<ul><li><div class="issue-num"><a class="issue-link" href="/toc/abcd20/34/2?nav=tocList">Issue 2</a></div>
  <p class="meta"><span class="loiIssueCoverDateText"> 2025 </span><span class="loiIssuePages"> pages 161-314 </span></p></li>
<li><div class="issue-num"><a class="issue-link" href="/toc/abcd20/34/1-2?nav=tocList">Issue 1-2</a></div>
  <p class="meta"><span class="loiIssueCoverDateText"> 2025 </span><span class="loiIssuePages"> pages 1-160 </span></p></li></ul>
<button class="volume_link" id="vol_33_2024" aria-expanded="false">Volume 33 2024</button>
</body></html>"""


def _page(p, html):
    b = launch_chromium(p)
    pg = b.new_page()
    pg.set_content(html)
    return b, pg


def test_parse_issue_skips_side_boxes(monkeypatch):
    monkeypatch.setattr(tandf, "goto", lambda page, path, settle=0: page.set_content(TOC))
    with sync_playwright() as p:
        b, pg = _page(p, TOC)
        rows = tandf.parse_issue(pg, {"toc": "/toc/x/34/2"})
        b.close()
    assert [r["doi"] for r in rows] == ["10.1080/1.2025.1", "10.1080/1.2024.2"]
    assert rows[0]["authors"] == "Kauffeld, Simone; Graßmann, Carolin"
    assert [r["content_type"] for r in rows] == ["Editorial", "Research Article"]
    assert rows[0]["pages"] == "161-174" and all(r["has_pdf"] for r in rows)


def test_list_issues_from_open_volume(monkeypatch):
    monkeypatch.setattr(tandf, "goto", lambda page, path, settle=0: page.set_content(LOI))
    with sync_playwright() as p:
        b, pg = _page(p, "<html></html>")
        issues = tandf.list_issues(pg, "abcd20", 2025)
        b.close()
    assert [(i["volume"], i["issue"], i["page_range"]) for i in issues] == [("34", "2", "161-314"), ("34", "1-2", "1-160")]
    assert issues[0]["toc"] == "/toc/abcd20/34/2" and issues[0]["date_text"] == "2025"
