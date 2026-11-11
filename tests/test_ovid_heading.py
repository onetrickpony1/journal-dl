# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Ovid issue headings, including journals dated by year only."""
from journal_dl import ovid

# What Ovid's table of contents shows for the Journal of Personnel Psychology (a quarterly dated by year
# only): the issue list in the sidebar first, then the heading of the open issue.
JPP = """Publish Ahead of Print
November 4, 2026
Volume 25 (4)
Curently selected

2026 - pg. 167-227
Volume 25 (3)
2026 - pg. 113-166
Volume 25 (2)
2026 - pg. 53-104
Volume 25 (1)
2026 - pg. 1-44
▶ 2025 (4)
▶ 2024 (4)
‹ Previous Issue | Next Issue ›

Journal of Personnel Psychology
Volume 25(4) pgs. 167-227 2026
ISSN: 1866-5888
"""


def test_year_only_heading_is_found_not_the_sidebar():
    assert ovid.heading_in(JPP) == "Volume 25(4) pgs. 167-227 2026"


def test_year_only_issue_counts_as_open():
    issue = {"volume": "25", "issue": "4", "date_text": "2026"}
    h = ovid.heading_in(JPP)
    assert h.startswith(ovid.expected_heading_prefix(issue)) and issue["date_text"] in h
    other = {"volume": "25", "issue": "3", "date_text": "2026"}
    assert not h.startswith(ovid.expected_heading_prefix(other))


def test_month_headings_unchanged():
    assert ovid.heading_in("x\nVolume 111(11) November 2026\ny") == "Volume 111(11) November 2026"
    assert ovid.heading_in("Volume 41(3) Fall 2025") == "Volume 41(3) Fall 2025"
    assert ovid.heading_in("Volume 7(1) pgs. 1-90 Jan-Mar 2026") == "Volume 7(1) pgs. 1-90 Jan-Mar 2026"


def test_no_heading():
    assert ovid.heading_in("Volume 25 (3)\n2026 - pg. 113-166\n") is None       # sidebar entry only
    assert ovid.heading_in("Volume 25(4) pgs. 1001-1999") is None                 # page numbers aren't a year
