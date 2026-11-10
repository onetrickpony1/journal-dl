# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Alternating between sites: a journal that is on two or more sites is downloaded issue by issue,
each issue from a site chosen at random among those that have it.

    - Issues are matched across sites by volume and issue number ("79(2)", "3/4" = "3-4").
    - The first site (the publisher's own, in sites.ORDER) names the journal folder and the issue folders,
      so the archive looks the same whichever site an issue came from.
    - An issue a site has already started stays with that site (no half-and-half issues), and an issue
      that is complete on any site is skipped.
    - Each site keeps its own database, pacing and hourly/daily PDF limits; --max counts all sites together.
The Alternator has the same surface as a runner (run_journal, stats, summary, journal_dir, ...), so
frontend.download uses it in place of one.
"""
import random
import re
import time

from . import files
from .engine import EXACT_PLAN_MAX, Cancelled, Plan, Progress, Stats, _browser_gone
from .pacing import estimate


def match_key(issue) -> str:
    """'Volume 79', '2' -> '79|2'; combined issues '3/4', '3 - 4' -> '3-4'; 'Issue 02' -> '2'."""
    def norm(x):
        t = (x or "").lower().replace("–", "-").replace("/", "-")
        t = re.sub(r"\b(volume|vol|issue|no|number)\b\.?", " ", t)
        t = re.sub(r"\s*-\s*", "-", t.strip())
        t = re.sub(r"\s+", " ", t)
        return re.sub(r"\b0+(\d)", r"\1", t)
    return f"{norm(issue.get('volume'))}|{norm(issue.get('issue'))}"


class Alternator:
    def __init__(self, runners, log=print, rng=None, confirm=None, plan_confirm=None, discover_only=False,
                 max_downloads=None, new_only=False):
        """runners: [(site label, runner, journal id on that site)], the preferred site first."""
        self.runners = runners
        self.log, self.rng = log, rng or random.Random()
        self.confirm, self.plan_confirm = confirm, plan_confirm
        self.discover_only, self.max_downloads, self.new_only = discover_only, max_downloads, new_only
        self.stats, self.progress = Stats(), Progress()
        for _, r, _ in runners:                 # one count, one progress line and one --max for every site
            r.stats, r.progress = self.stats, self.progress
            r.pacer.status = self.progress.line
            r.max_downloads = max_downloads
        self.journal_dir = None
        self._on_issue = None

    # ---- the runner surface frontend.download uses
    @property
    def on_issue(self):
        return self._on_issue

    @on_issue.setter
    def on_issue(self, f):
        self._on_issue = f
        for _, r, _ in self.runners:
            r.on_issue = f

    @property
    def downloads(self):
        return self.stats.downloaded

    def limit_reached(self):
        return self.max_downloads is not None and self.stats.downloaded >= self.max_downloads

    def summary(self):
        return self.runners[0][1].summary()

    # ---- the run
    def run_journal(self, jid=None, years=None, issue_hint=None):
        started = []
        try:
            for entry in self.runners:
                entry[1].begin()
                started.append(entry)
            self._run(years, issue_hint)
        finally:
            for _, r, _ in started:
                r.end()

    def _drop(self, n, e):
        label = self.runners[n][0]
        self.log(f"{label}: could not be used this time ({str(e)[:160]}); continuing without it.")
        del self.runners[n]

    def _run(self, years, issue_hint):
        label0, primary, jid0 = self.runners[0]
        info0, j0 = primary.open_journal(jid0)
        self.journal_dir = primary.journal_dir
        opened = [(label0, primary, info0, j0)]
        for label, r, jid in self.runners[1:]:
            try:
                info, j = r.open_journal(jid, title=info0["title"])
            except Exception as e:
                if _browser_gone(e):
                    raise
                self.log(f"{label}: could not open the journal ({str(e)[:160]}); continuing without it.")
                continue
            opened.append((label, r, info, j))
        for label, r, info, _ in opened:
            self.log(f"Covers:  {info.get('years') or '?'} on {label}"
                     + (f"  (ISSN {info['issn']})" if info.get("issn") else ""))

        newest = [y for y in (r.newest_year_downloaded(j) for _, r, _, j in opened) if y]
        listed = []                              # [(label, runner, journal row, issues)]
        for n, (label, r, info, j) in enumerate(opened):
            yrs = r.years_for(info, j, years, issue_hint, newest_have=max(newest) if newest else None)
            try:
                listed.append((label, r, j, r.list_issues(info, j, yrs)))
            except Exception as e:
                if n == 0 or _browser_gone(e):
                    raise
                self.log(f"{label}: could not read the issue list ({str(e)[:160]}); continuing without it.")
        if len(listed) < 2:
            self.log("Only one site is usable this time: downloading everything from it.")

        canon, where = self._match(listed)
        self.log(f"{len(canon)} issue(s) in all; "
                 + ", ".join(f"{label} has {len(iss)}" for label, _, _, iss in listed) + ".")

        todo = canon
        if self.new_only:
            todo = self._newer_than_downloaded(canon, where)
            if not todo:
                self.log("No new issues since your last download.")
                return
        if self.confirm:
            chosen = self.confirm(info0, todo, canon)
            if not chosen:
                raise Cancelled("nothing selected; nothing downloaded")
            if isinstance(chosen, list):
                todo = chosen

        plan_items = []                          # [(canonical issue, (label, runner, j, site issue), row)]
        for c in todo:
            pick = self._assign(where[c["key"]])
            if pick:
                plan_items.append((c, *pick))
        for c, (label, r, j, i), row in plan_items:
            if i is not c:                       # save into the folder the preferred site would use
                r.folder_issue[i["key"]] = c

        unread = [x for x in plan_items if x[2]["discovery_status"] != "complete"]
        exact = self.discover_only or len(unread) <= EXACT_PLAN_MAX
        if exact and unread:
            self.log(f"Reading the contents of {len(unread)} issue(s)...")
        rows = {}
        for c, (label, r, j, i), row in plan_items:
            if exact and row["discovery_status"] != "complete":
                r._retrying(r._discover, j, row, i)
                row = r.issue_row(j, i)
            rows[c["key"]] = row
        plan = self._plan(plan_items, rows)
        primary._announce(plan)
        self._announce_sites(plan_items, rows)
        if self.discover_only:
            self._finish(listed)
            return
        if plan.exact and plan.pending == 0:
            self.log("Nothing to download: everything selected is already saved.")
            self._finish(listed)
            return
        if self.plan_confirm and not self.plan_confirm(plan):
            raise Cancelled("cancelled; nothing downloaded")

        primary.start_progress(plan)
        for c, (label, r, j, i), _ in plan_items:
            row = r.issue_row(j, i)
            if row["discovery_status"] == "complete" and not r._pending(row["id"]):
                continue
            self.log(f"\n-- {files.issue_folder_name(c)}: from {label}")
            r.download_issue(j, row, i)
            if self.limit_reached():
                self.log(f"Reached --max {self.max_downloads} downloads, stopping.")
                break
        self._finish(listed)

    # ---- pieces
    def _match(self, listed):
        """-> (canonical issues newest first, {canonical key: [(label, runner, j, that site's issue)]})."""
        canon, where, by_match = [], {}, {}
        for label, r, j, issues in listed:
            for i in issues:
                mk = match_key(i)
                c = by_match.get(mk)
                if c is None:                    # first site to list it names it
                    c = by_match[mk] = i
                    canon.append(i)
                    where[i["key"]] = []
                if not any(x[1] is r for x in where[c["key"]]):
                    where[c["key"]].append((label, r, j, i))
        def year(i):
            return int(i["year"]) if str(i.get("year", "")).isdigit() else 0
        canon.sort(key=year, reverse=True)       # stable: the preferred site's order within a year
        return canon, where

    def _newer_than_downloaded(self, canon, where):
        def has_download(c):
            for _, r, j, i in where[c["key"]]:
                row = r.issue_row(j, i)
                if r.s.one("""SELECT 1 FROM issue_articles ia JOIN jobs jb ON jb.article_id=ia.article_id
                              WHERE ia.issue_id=? AND jb.state='complete' LIMIT 1""", row["id"]):
                    return True
            return False
        out = []
        for c in canon:                          # newest first
            if has_download(c):
                return out
            out.append(c)
        return canon[:1]                         # nothing downloaded yet: only the newest issue

    def _assign(self, candidates):
        """The site to get an issue from, or None when it is already complete on one of them."""
        state = []
        for entry in candidates:
            _, r, j, i = entry
            row = r.issue_row(j, i)
            done = r.s.one("""SELECT COUNT(*) n FROM issue_articles ia JOIN jobs jb ON jb.article_id=ia.article_id
                              WHERE ia.issue_id=? AND jb.state='complete'""", row["id"])["n"]
            pending = r._pending(row["id"])
            if row["discovery_status"] == "complete" and done and not pending:
                return None                      # finished on this site
            state.append((entry, row, done))
        started = [x for x in state if x[2]]
        entry, row, _ = started[0] if started else self.rng.choice(state)
        return entry, row

    def _plan(self, plan_items, rows):
        known = [x[1][1]._items(rows[x[0]["key"]]["id"]) for x in plan_items
                 if rows[x[0]["key"]]["discovery_status"] == "complete"]
        avg = round(sum(known) / len(known)) if known else 12
        per, pending, exact = [], 0, True
        for c, (label, r, j, i), _ in plan_items:
            row = rows[c["key"]]
            if row["discovery_status"] == "complete":
                n, p = r._items(row["id"]), r._pending(row["id"])
                per.append((c, n, p, True))
            else:
                n = p = avg
                per.append((c, n, p, False))
                exact = False
            pending += p
        primary = self.runners[0][1]
        item_s = sum(r.ITEM_S for _, r, _ in self.runners) / len(self.runners)
        page_s = sum(r.PAGE_S for _, r, _ in self.runners) / len(self.runners)
        est = estimate(primary.pacer.p, min(pending, self.max_downloads or pending), 0, item_s=item_s,
                       page_s=page_s, done_recently=len(primary._times_since(time.time() - 86400)))
        return Plan(per, pending, exact, est)

    def _announce_sites(self, plan_items, rows):
        counts = {}
        for c, (label, r, j, i), _ in plan_items:
            row = rows[c["key"]]
            if row["discovery_status"] != "complete" or r._pending(row["id"]):
                counts[label] = counts.get(label, 0) + 1
        if counts:
            self.log("Alternating sites (chosen at random per issue): "
                     + ", ".join(f"{n} issue(s) from {label}" for label, n in counts.items()) + ".")

    def _finish(self, listed):
        for label, r, j, _ in listed:
            r._finish(j, self.journal_dir, report=f"journal_report-{r.NAME}")
