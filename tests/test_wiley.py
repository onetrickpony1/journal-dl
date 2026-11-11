# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Offline check of the Wiley issue-page reader against a small copy of the observed markup."""
from playwright.sync_api import sync_playwright

from journal_dl import wiley


def launch_chromium(p):
    """Installed Chrome when there is one (/opt/google/chrome), else Playwright's own Chromium."""
    try:
        return p.chromium.launch(channel="chrome", headless=True)
    except Exception:
        return p.chromium.launch(channel="chromium", headless=True)   # the full build --install-browser gets

TOC = """<html><body><div class="issue-items-container bulkDownloadWrapper">
<h3 class="toc__heading section__header to-section">ISSUE INFORMATION</h3>
<div class="issue-item"><span class="doi-access-wrapper">Free Access</span>
  <a class="issue-item__title" href="/doi/10.1002/job.1"><h2>Issue Information</h2></a>
  <a href="/doi/epdf/10.1002/job.1">PDF</a></div>
<h3 class="toc__heading section__header to-section">RESEARCH ARTICLE</h3>
<div class="issue-item"><h4 class="toc__heading section__header">A Special Section</h4>
  <div class="issue-item"><span class="doi-access-wrapper">Full Access</span>
    <a class="issue-item__title" href="/doi/10.1002/job.2"><h2>First Study: Teams</h2></a>
    <div class="loa"><span class="author-style">Anna B. Smith</span><span class="author-style">Anna B. Smith</span>
      <span class="author-style">Jo Lee</span></div> Pages: 10-20
    <a href="/doi/epdf/10.1002/job.2">PDF</a></div>
  <div class="issue-item"><span class="doi-access-wrapper">Open Access</span>
    <a class="issue-item__title" href="/doi/full/10.1002/job.3"><h2>Second Study</h2></a> Pages: 21-30
    <a href="/doi/epdf/10.1002/job.3">PDF</a></div>
</div>
<div class="issue-item"><span class="doi-access-wrapper">Full Access</span>
  <a class="issue-item__title" href="/doi/10.1002/job.2"><h2>First Study: Teams</h2></a></div>
</div></body></html>"""


class FakePage:
    """parse_issue calls goto(); serve the fixture instead of the network."""
    def __init__(self, page):
        self.page = page

    def __getattr__(self, k):
        return getattr(self.page, k)


def test_parse_issue(monkeypatch):
    monkeypatch.setattr(wiley, "goto", lambda page, path, settle=0: page.set_content(TOC))
    with sync_playwright() as p:
        b = launch_chromium(p)
        page = b.new_page()
        rows = wiley.parse_issue(page, {"toc": "/toc/x/2026/1/1"})
        b.close()
    assert [r["doi"] for r in rows] == ["10.1002/job.1", "10.1002/job.2", "10.1002/job.3"]   # wrapper + duplicate dropped
    assert [r["sequence"] for r in rows] == [1, 2, 3]
    assert [r["content_type"] for r in rows] == ["Issue Information", "Research Article", "Research Article"]
    assert rows[1]["authors"] == "Smith, Anna B.; Lee, Jo"
    assert rows[1]["pages"] == "10-20" and rows[1]["access"] == "Full Access" and rows[1]["has_pdf"]


def test_issn_and_names():
    assert wiley.issn("1099050x") == "1099-050X"
    assert wiley._surname_first("Simon B. de Jong") == "Jong, Simon B. de"


def test_issue_date_labels():
    d = wiley.issue_date
    assert d("Full Access Volume 79, Issue 3 Pages: 305-456 Autumn (Fall) 2026") == "Autumn 2026"
    assert d("Pages: 105-301 Summer 2026") == "Summer 2026"
    assert d("Pages: 1477-1711 November 2026") == "November 2026"
    assert d("Pages: 1-90 January/February 2026") == "January/February 2026"
    assert d("Pages: 1-90 Winter 2025/2026") == "Winter 2025/2026"
    assert d("Pages: 1-90") is None
