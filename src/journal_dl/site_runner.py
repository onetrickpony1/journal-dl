# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Runner for publisher sites with stable addresses (Wiley, Taylor & Francis) on the shared engine.
The site module (wiley.py, tandf.py) supplies the page reading."""
import time

from . import notify, wiley
from .engine import AUTH_WAIT_S, CHALLENGE_MSG, BaseRunner, Paused, _in_years, _retry_after_value, sleep_i


class SiteRunner(BaseRunner):
    ITEM_S = 4.0
    PAGE_S = 3.0

    def __init__(self, *a, site=wiley, **kw):
        super().__init__(*a, **kw)
        self.site = site
        self.NAME, self.LABEL = site.NAME, site.LABEL
        self.AuthRequired = site.AuthRequired
        self.ITEM_S = getattr(site, "ITEM_S", self.ITEM_S)

    # ---------------------------------------------------- helpers
    def _goto(self, fn, *a):
        """Run a page-reading step with pacing, sign-in recovery and throttle handling."""
        for attempt in range(4):
            self.pacer.wait_page()
            try:
                return fn(self.page, *a)
            except self.site.AuthRequired as e:
                self.wait_for_signin(str(e))
            except self.site.ChallengeRequired:
                notify.send("Check needed", f"{self.LABEL} wants a 'verify you are human' check.")
                raise Paused(CHALLENGE_MSG.format(label=self.LABEL))
            except self.site.RateLimited as e:
                self.pacer.on_throttle(_retry_after_value(e.retry_after))
                if attempt == 3:
                    raise Paused(f"{self.LABEL} keeps throttling; stopped to be safe. Try later or use --speed slow")
                sleep_i(self.pacer.retry_delay(attempt))
        raise Paused("could not load the page after signing in again")

    def wait_for_signin(self, why):
        self.log(f"\n*** SIGN-IN NEEDED ({why}). Sign in through your institution in the browser window; "
                 f"waiting up to {AUTH_WAIT_S // 60} min ***")
        notify.send("Sign-in needed", f"{self.LABEL}: sign in again in the downloader's browser window.")
        self.s.event("run", "auth", "auth_required", why=why)
        end = time.monotonic() + AUTH_WAIT_S
        while time.monotonic() < end:
            sleep_i(5)
            try:
                if self.site.HOST_HINT in self.page.url and self.site.signed_in(self.page):
                    self.log("Signed in again, continuing.")
                    return
            except Exception:
                pass
        raise Paused("sign-in did not complete in time")

    # ---------------------------------------------------- engine hooks
    def run_journal(self, jid, years=None, issue_hint=None):
        self.page = self.ctx.new_page()
        try:
            super().run_journal(jid, years, issue_hint)
        finally:
            try:
                self.page.close()
            except Exception:
                pass

    def _open(self, jid):
        info = self._goto(self.site.journal_info, jid)
        info["last_year"] = info["year_list"][-1]
        j = self.s.upsert_journal(f"{self.site.NAME}:{jid}", info["title"], info["issn"])
        self.jid = jid
        return info, j

    def _list(self, info, years):
        yrs = [y for y in reversed(info["year_list"]) if _in_years(str(y), years)]
        if not yrs:
            raise Paused(f"no issues in the years asked for (journal covers {info['years']})")
        self.log(f"Reading the issue list for {len(yrs)} year(s)...")
        issues, unreadable = [], []
        for n, y in enumerate(yrs, 1):
            if len(yrs) > 3:
                self.log(f"   {y} ({n}/{len(yrs)})")
            try:
                issues += self._goto(self.site.list_issues, self.jid, y)
            except self.site.AdapterError as e:
                if len(yrs) == 1:
                    raise
                unreadable.append(y)
                self.s.event(f"journal:{self.jid}", "list_issues", "unreadable", year=y, error=str(e))
                self.log(f"   {y}: could not read this year's issues ({e}); skipped")
        if unreadable:
            self.log(f"Note: issue lists for {', '.join(map(str, unreadable))} could not be read; "
                     "those years are not included (run again later to retry).")
        return issues

    def _pages_for(self, per):
        return sum(1 for _, _, pending, exact in per if pending and not exact)

    def _discover(self, j, row, issue):
        self.log(f"   reading {issue['link_title']}...")
        rows = self._goto(self.site.parse_issue, issue)
        with self.s.tx():
            for r in rows:
                self.s.record_article(row["id"], r, 1)
            self.s.db.execute("""INSERT OR REPLACE INTO discovery_pages(issue_id,ordinal,signature,rows,completed_at)
                                 VALUES(?,?,?,?,?)""", (row["id"], 1, f"{rows[0]['doi']}..{rows[-1]['doi']}#{len(rows)}",
                                                        len(rows), time.time()))
            self.s.db.execute("UPDATE issues SET discovery_status='complete', pages_traversed=1, discovered_at=? "
                              "WHERE id=?", (time.time(), row["id"]))

    def _download_issue(self, j, row, issue):
        from . import files
        if row["discovery_status"] != "complete":
            self._discover(j, row, issue)
        self.log(f"\n== {files.issue_folder_name(issue)}" + (f" (pages {issue['page_range']})" if issue.get("page_range") else ""))
        idir = files.issue_dir(self.journal_dir, issue)
        arts = self.s.q("""SELECT a.id aid, ia.sequence, a.authors, a.title, a.provider_id, a.doi, ia.has_pdf
                           FROM issue_articles ia JOIN articles a ON a.id=ia.article_id
                           WHERE ia.issue_id=? ORDER BY ia.sequence""", row["id"])
        for a in arts:
            if self.limit_reached():
                break
            self.download(a["aid"], dict(a), idir)

    def _fetch(self, r):
        try:
            status, headers, data, final_url = self.site.fetch_pdf(self.ctx, r["doi"])
        except self.site.ChallengeRequired:
            notify.send("Check needed", f"{self.LABEL} wants a 'verify you are human' check.")
            raise Paused(CHALLENGE_MSG.format(label=self.LABEL))
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        if self.site.is_challenge(status, headers, data[:20000]):
            raise Paused(CHALLENGE_MSG.format(label=self.LABEL))
        if any(h in final_url for h in self.site.login_hints()):
            raise self.site.AuthRequired("institution session expired")
        if status in (429, 503):
            return {"state": "rate_limited", "msg": f"HTTP {status}",
                    "retry_after": _retry_after_value(headers.get("retry-after"))}
        ctype = (headers.get("content-type") or "").lower()
        if status in (401, 403) or ("pdf" not in ctype and data.lstrip()[:5] != b"%PDF-"):
            text = data[:20000].decode("utf-8", "ignore").lower()
            if status in (401, 403) or any(s in text for s in ("purchase instant access", "access options",
                                                                     "you do not have access", "check access")):
                return {"state": "access_denied", "msg": "no access through your institution"}
            return {"state": "retry", "msg": f"HTTP {status}, got {ctype or 'unknown'} instead of a PDF"}
        return {"state": "ok", "data": data, "source": f"{self.site.NAME}-pdfdirect"}


WileyRunner = SiteRunner
