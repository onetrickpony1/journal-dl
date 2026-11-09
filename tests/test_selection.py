# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

from journal_dl.selection import in_month, issue_matches, parse_pick, parse_when


def iss(vol, num, date, rng="1-9"):
    return {"volume": vol, "issue": num, "date_text": date, "year": date[-4:],
            "link_title": f"Vol {vol} {date}", "page_range": rng}


NOV = iss("111", "11", "November 2026")
NOVDEC = iss("40", "6", "Nov/Dec 2019")
SUPP = iss("16", "Supplement 1", "Spring 2017")


def test_parse_when():
    assert parse_when("2021") == ((2021, 2021), None)
    assert parse_when("2021-2018") == ((2018, 2021), None)
    assert parse_when("2026-11") == ((2026, 2026), 11)
    assert parse_when("2026-3") == ((2026, 2026), 3)
    assert parse_when(None) == (None, None)


def test_months():
    assert in_month(NOV, 11) and not in_month(NOV, 10)
    assert in_month(NOVDEC, 11) and in_month(NOVDEC, 12)


def test_issue_matching():
    for t in ("November 2026", "nov 2026", "111(11)", "Vol 111 (11)", "Vol 111 November 2026", "2026-11", "November"):
        assert issue_matches(NOV, t), t
    for t in ("October 2026", "111(10)", "2025-11", "December"):
        assert not issue_matches(NOV, t), t
    assert issue_matches(SUPP, "16(Supplement 1)") and issue_matches(SUPP, "Spring 2017")


def test_parse_pick():
    assert parse_pick("", 5) == [0, 1, 2, 3, 4]
    assert parse_pick("3", 5) == [2]
    assert parse_pick("1,4", 5) == [0, 3]
    assert parse_pick("2-4", 5) == [1, 2, 3]
    assert parse_pick("1, 3-4", 5) == [0, 2, 3]
    assert parse_pick("6", 5) is None and parse_pick("x", 5) is None and parse_pick("4-2", 5) is None
