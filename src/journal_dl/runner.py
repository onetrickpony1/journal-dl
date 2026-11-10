# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Ovid runner: Ovid's page handling on top of the shared engine (engine.py).

Ovid issue addresses are session state, so the runner navigates by clicking and checks the issue
heading after every move; PDFs open in their own tab and are fetched again in the signed-in session.
"""
import time
from urllib.parse import urljoin

from . import files, ovid, sanitize
from .engine import AUTH_WAIT_S, BaseRunner, Paused, _in_years, _retry_after, sleep_i


class OvidRunner(BaseRunner):
    NAME = "ovid"
    LABEL = "Ovid"
    ITEM_S = 10.0
    PAGE_S = 4.0
    AuthRequired = ovid.AuthRequired

    # ---------------------------------------------------- session
    def ovid_page(self):
        pages = [p for p in self.ctx.pages if "ovid" in p.url and "ovidweb.cgi" in p.url]
        if not pages:
            raise Paused("the Ovid tab was closed: run the same command again to reopen it")
        return pages[-1]

    def wait_for_signin(self, why):
        from . import notify
        self.log(f"\n*** SIGN-IN NEEDED ({why}). Sign in again in the browser window; "
                 f"waiting up to {AUTH_WAIT_S // 60} min ***")
        notify.send("Sign-in needed", f"{self.LABEL}: sign in again in the downloader's browser window.")
        self.s.event("run", "auth", "auth_required", why=why)
        end = time.monotonic() + AUTH_WAIT_S
        while time.monotonic() < end:
            sleep_i(5)
            try:
                p = self.ovid_page()
                ovid.check_auth(p)
                if ovid.heading(p):
                    self.page = p
                    self.log("Signed in again, continuing.")
                    return
            except (Paused, ovid.AuthRequired):
                continue
        raise Paused("sign-in did not complete in time")

    # ---------------------------------------------------- engine hooks
    def _open(self, jid):
        self.page = self.ovid_page()
        ovid.wait_ready(self.page, 300)
        info = ovid.journal_info(self.page)
        y = (info.get("years") or "").split("-")
        info["last_year"] = int(y[1]) if len(y) > 1 and y[1].isdigit() else time.localtime().tm_year
        j = self.s.upsert_journal(f"ovid:{info['issn']}", info["title"], info["issn"])
        return info, j

    def _list(self, info, years):
        self.log("Reading the issue list" + (f" for {years[0]}-{years[1]}" if years else
                                             " (all years; can take a few minutes)") + "...")
        ovid.expand_all_years(self.page, log=self.log, years=years)
        issues = [i for i in ovid.list_issues(self.page) if _in_years(i["year"], years)]
        out = []
        for i in issues:     # e.g. "Publish Ahead of Print": not an issue; its articles move into issues later
            if not i["link_text"].startswith("Volume"):
                self.log(f"- {i['link_title']}: skipped (not a journal issue)")
                continue
            out.append(i)
        return out

    def _pages_for(self, per):
        return sum(2 for _, _, pending, _ in per if pending)

    def _discover(self, j, row, issue):
        self._walk(j, row, issue, download=False)

    def _download_issue(self, j, row, issue):
        self._walk(j, row, issue, download=True)

    def _walk(self, j, row, issue, download):
        p = self.page
        self.log(f"\n== {files.issue_folder_name(issue)}" + (f" (pages {issue['page_range']})" if issue["page_range"] else ""))
        self.pacer.wait_page()
        ovid.open_issue(p, issue)
        ovid.set_per_page(p, 50)          # Ovid remembers this, so it reloads at most once
        if not ovid.on_issue(p, issue):
            raise ovid.AdapterError("changing results-per-page left the issue")
        if ovid.current_results_page(p) != 1:
            ovid.go_results_page(p, 1)
        idir = self.issue_dir(issue)
        seen, k = set(), 1
        while True:
            rows = ovid.parse_rows(p)
            sig = ovid.page_signature(rows)
            if not rows:
                raise ovid.AdapterError(f"results page {k} has no article rows")
            if sig in seen:
                raise ovid.AdapterError(f"results page {k} repeats an earlier page ({sig})")
            seen.add(sig)
            with self.s.tx():
                ids = [self.s.record_article(row["id"], r, k) for r in rows]
                self.s.db.execute("""INSERT OR REPLACE INTO discovery_pages(issue_id,ordinal,signature,rows,completed_at)
                                     VALUES(?,?,?,?,?)""", (row["id"], k, sig, len(rows), time.time()))
                self.s.db.execute("UPDATE issues SET discovery_status='in_progress' WHERE id=?", (row["id"],))
            self.log(f"   results page {k}: {len(rows)} articles (#{rows[0]['sequence']}-{rows[-1]['sequence']})")
            if download:
                for aid, r in zip(ids, rows):
                    if self.limit_reached():
                        break
                    self.download(aid, r, idir)
                    if not (ovid.on_issue(p, issue) and ovid.current_results_page(p) == k):
                        raise ovid.AdapterError("issue tab moved during downloads")
            if self.limit_reached():
                return
            if not p.locator("a[aria-label='Next Page']").count():
                break
            self.pacer.wait_page()
            if not ovid.next_results_page(p):
                break
            k += 1
            if not ovid.on_issue(p, issue):
                raise ovid.AdapterError("Next Page left the issue")
        with self.s.tx():
            self.s.db.execute("UPDATE issues SET discovery_status='complete', pages_traversed=?, discovered_at=? WHERE id=?",
                              (k, time.time(), row["id"]))

    def _fetch(self, r):
        href = urljoin(self.page.url, r["pdf_href"])
        tab = self.ctx.new_page()
        pdf_resps = []
        tab.on("response", lambda resp: pdf_resps.append(resp)
               if "application/pdf" in (resp.headers.get("content-type") or "").lower() else None)
        try:
            resp = tab.goto(href, wait_until="load", timeout=60000)
            if resp is not None and resp.status in (429, 503):
                return {"state": "rate_limited", "msg": f"HTTP {resp.status}", "retry_after": _retry_after(resp)}
            deadline = time.monotonic() + 40
            while not pdf_resps and time.monotonic() < deadline:
                tab.wait_for_timeout(500)
            ovid.check_auth(tab)
            if not pdf_resps:
                body = tab.inner_text("body")[:4000].lower()
                if any(s in body for s in ("not subscribed", "access denied", "not available to you",
                                           "no access", "purchase this article")):
                    return {"state": "access_denied", "msg": "no access through your institution"}
                if "too many requests" in body:
                    return {"state": "rate_limited", "msg": "too many requests page"}
                return {"state": "retry", "msg": "no PDF arrived within 40 s"}
            pr = pdf_resps[-1]
            if pr.status in (429, 503):
                return {"state": "rate_limited", "msg": f"HTTP {pr.status}", "retry_after": _retry_after(pr)}
            try:
                data = pr.body()
            except Exception:
                data = b""
            if data.lstrip()[:5] != b"%PDF-":
                data = self.ctx.request.get(pr.url, timeout=120000).body()
            an = sanitize.ovid_an(pr.url)
        finally:
            tab.close()
        if an and an != r["provider_id"]:
            return {"state": "retry", "msg": f"PDF is for {an}, expected {r['provider_id']}"}
        return {"state": "ok", "data": data, "source": "ovid-pdf-refetch",
                "ident": "confirmed-accession" if an == r["provider_id"] else None}


Runner = OvidRunner      # older name
