# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Choosing issues: years/months on the command line, --issue text, the numbered picker."""
import re
import sys

from . import files

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]


def parse_when(s):
    """'2021' | '2018-2021' | '2026-11' (one month) -> (years, month or None)."""
    if not s:
        return None, None
    s = s.strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", s)
    if m and 1 <= int(m.group(2)) <= 12:
        y = int(m.group(1))
        return (y, y), int(m.group(2))
    m = re.fullmatch(r"(\d{4})(?:\s*[-:]\s*(\d{4}))?", s)
    if not m:
        raise SystemExit(f"use 2021, 2018-2021 or 2026-11 (a month), not {s!r}")
    lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
    return (min(lo, hi), max(lo, hi)), None


def parse_years(s):
    return parse_when(s)[0]


def _words(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split()


def in_month(issue, month):
    """True when the issue's date names that month (full or 3-letter, e.g. 'Nov/Dec 2026')."""
    name = MONTHS[month - 1]
    return any(w == name or w == name[:3] for w in _words(issue["date_text"]))


def issue_matches(issue, text):
    """Loose match: 'November 2026', 'Nov 2026', '111(11)', 'Vol 111 November 2026', '2026-11'."""
    yrs, month = parse_when(text) if re.fullmatch(r"\d{4}-\d{1,2}", text.strip()) else (None, None)
    if month:
        return issue["year"] == str(yrs[0]) and in_month(issue, month)
    t = re.sub(r"\s+", "", text.lower())
    vi = re.sub(r"\s+", "", f"{issue['volume']}({issue['issue']})".lower())
    if t in (vi, "vol" + vi, "volume" + vi):
        return True
    have = set(_words(issue["link_title"]) + _words(issue["date_text"]))
    want = _words(text.replace("vol.", "vol "))
    for w in want:                                   # every word must be there (months may be abbreviated)
        if w in have or any(len(w) >= 3 and m.startswith(w) and m in have for m in MONTHS):
            continue
        return False
    return bool(want)


def describe(i):
    rng = f"(pages {i['page_range']})" if i["page_range"] else ""
    return f"{files.issue_folder_name(i):<36}{rng}"


def parse_pick(ans, n):
    """'3' | '1,4' | '2-5' | '1,3-4' | '' (all) -> sorted indexes, or None if invalid."""
    ans = ans.strip().lower()
    if ans in ("", "all", "a"):
        return list(range(n))
    out = set()
    for part in ans.replace(" ", "").split(","):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            return None
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if not (1 <= lo <= hi <= n):
            return None
        out.update(range(lo - 1, hi))
    return sorted(out)


def pick_issues(issues):
    print(f"\n{len(issues)} issues:")
    for n, i in enumerate(issues, 1):
        print(f"  {n:>3}. {describe(i)}")
    while True:
        try:
            ans = input("Which issues? e.g. 3  or  1,4  or  2-5  (Enter = all, q = quit): ")
        except EOFError:
            return []
        if ans.strip().lower() in ("q", "quit"):
            return []
        idx = parse_pick(ans, len(issues))
        if idx is not None:
            return [issues[k] for k in idx]
        print(f"  Please type numbers between 1 and {len(issues)}.")


def make_confirm(years=None, issue=None, month=None, pick=False, journal_arg=None, when_arg=None,
                 keys=None, prog="journal-dl", interactive=True):
    """Selection hook for the runner: narrows the listed issues to what was asked for.
    keys: exact issue keys (used to resume a run whose issues were picked from the list)."""
    def confirm(info, todo, all_issues):
        sel = todo
        if keys:
            sel = [i for i in sel if i["key"] in keys]
        if month:
            sel = [i for i in sel if in_month(i, month)]
        if issue:
            sel = [i for i in sel if issue_matches(i, issue)]
        if (month or issue or keys) and not sel:
            print(f"\nNo issue matches {issue or when_arg or 'the saved selection'!r}. Issues available:")
            for i in todo[:40]:
                print("   " + describe(i))
            return False
        if pick:
            if not (interactive and sys.stdin.isatty()):
                print("The issue picker needs a terminal: give years or --issue instead.")
                return False
            sel = pick_issues(sel)
            if not sel:
                return False
            if len(sel) == 1 and journal_arg:
                print(f'\nNext time you can type:\n  {prog} "{info["title"]}" --issue "{sel[0]["date_text"]}"')
        confirm.chosen = sel
        return sel
    confirm.chosen = None
    return confirm
