# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Shared download engine for every site (Ovid, Wiley, Taylor & Francis).

A run goes:  open journal -> list issues (only the years needed) -> select issues
             -> read the selected issues' contents -> plan + time estimate (+ confirm)
             -> download with pacing and a live progress line -> reports + summary.
Site subclasses implement: _open, _list, _discover, _download_issue, _fetch, wait_for_signin.
"""
import json
import os
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import files, paths
from .pacing import Pacer, estimate, fmt, fmt_estimate, load_default
from .store import Store
from .validate import check_pdf, identity_hint

MIN_FREE_BYTES = 5 * 1024**3        # pause when the archive drive drops below this
AUTH_WAIT_S = 30 * 60
EXACT_PLAN_MAX = 15                 # read up to this many issues' contents before asking; more -> rough estimate
PENDING = ("pending", "retry_wait", "auth_required", "downloading")
CHALLENGE_MSG = ("{label} is showing a 'verify you are human' check. journal-dl never tries to get past these: "
                 "open the browser window, complete the check yourself, then run the same command again "
                 "(a slower --speed makes these less likely)")


class Paused(RuntimeError):
    pass


class Cancelled(Paused):
    """The user chose nothing / said no: not an unfinished run."""


def sleep_i(seconds):
    """Interruptible sleep (Ctrl+C works at once)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(min(1.0, end - time.monotonic()))


def _retry_after_value(v):
    if not v:
        return None
    try:
        return max(0.0, float(v))
    except ValueError:
        from email.utils import parsedate_to_datetime
        try:
            return max(0.0, parsedate_to_datetime(v).timestamp() - time.time())
        except Exception:
            return None


def _retry_after(resp):
    return _retry_after_value((resp.headers or {}).get("retry-after"))


def _in_years(year, years):
    if not years:
        return True
    try:
        y = int(year)
    except ValueError:
        return True
    return years[0] <= y <= years[1]


# ---------------------------------------------------------------- run lock (all OSes)
class RunLock:
    """One run per site at a time. Uses fcntl on Linux/macOS and msvcrt on Windows."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.f.close()
            raise SystemExit("Another download for this site is already running (only one per site at a time). "
                             "Wait for it to finish, or stop it with Ctrl+C in its window.")
        return self

    def __exit__(self, *a):
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f, fcntl.LOCK_UN)
        finally:
            self.f.close()


# ---------------------------------------------------------------- duplicates across sites
def find_existing_copy(doi, root: Path, exclude: Path):
    """A valid PDF of this DOI already saved by another site's downloader, or None."""
    if not doi:
        return None
    for db in sorted(paths.data_dir().glob("*.sqlite")):
        if db.resolve() == Path(exclude).resolve() or "backup" in db.name:
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
            row = con.execute("""SELECT s.path FROM assets s JOIN articles a ON a.id=s.article_id
                                 WHERE lower(a.doi)=lower(?) AND s.validation='valid'""", (doi,)).fetchone()
            con.close()
        except sqlite3.Error:
            continue
        if row and (root / row[0]).is_file():
            return root / row[0]
    return None


# ---------------------------------------------------------------- plan / progress / summary
@dataclass
class Plan:
    issues: list                        # [(issue dict, items, pending, exact)]
    pending: int
    exact: bool
    estimate: tuple = (0, 0, 0)


@dataclass
class Stats:
    downloaded: int = 0
    copied: int = 0
    adopted: int = 0
    failed: int = 0
    denied: int = 0
    no_pdf: int = 0
    issues: set = field(default_factory=set)


class Progress:
    def __init__(self):
        self.total, self.done, self.label, self.per_item = 0, 0, "", 10.0

    def count_done(self):
        return f"[{self.done}/{self.total}]" if self.total else ""

    def line(self, left):
        rest = max(0, self.total - self.done)
        parts = [f"[{self.done}/{self.total}]" if self.total else "", self.label, f"next in {fmt(left)}"]
        if rest:
            parts.append(f"about {fmt(left + (rest - 1) * self.per_item)} left")
        return "  ".join(p for p in parts if p)


# ---------------------------------------------------------------- reports
def issue_rows(store, issue_id):
    return store.q("""SELECT ia.sequence, ia.page_label, ia.has_pdf, ia.results_page, a.provider_id, a.doi, a.title,
                             a.authors, a.content_type, j.state, j.last_error, j.attempts,
                             s.path, s.sha256, s.bytes, s.pages, s.identity
                      FROM issue_articles ia JOIN articles a ON a.id=ia.article_id
                      JOIN jobs j ON j.article_id=a.id LEFT JOIN assets s ON s.article_id=a.id
                      WHERE ia.issue_id=? ORDER BY ia.sequence""", issue_id)


def issue_summary(store, issue_id):
    rows = issue_rows(store, issue_id)
    st = store.one("SELECT * FROM issues WHERE id=?", issue_id)
    c = lambda state: sum(1 for r in rows if r["state"] == state)
    eligible = sum(1 for r in rows if r["has_pdf"])
    done = c("complete")
    if st["discovery_status"] != "complete":
        outcome = "contents not read yet" if not rows else "contents partly read (counts provisional)"
    elif done == eligible:
        outcome = "all available PDFs downloaded"
    else:
        outcome = "partial download"
    return {"issue": st["link_title"], "volume": st["volume"], "issue_label": st["issue_label"],
            "date": st["date_text"], "discovery": st["discovery_status"], "results_pages": st["pages_traversed"],
            "records": len(rows), "pdf_eligible": eligible, "validated_files": done,
            "no_pdf": c("no_pdf"), "access_denied": c("access_denied"), "failed": c("failed"),
            "pending": sum(1 for r in rows if r["state"] in PENDING),
            "identity_unconfirmed": sum(1 for r in rows if r["state"] == "complete" and r["identity"] == "unconfirmed"),
            "outcome": outcome}


def write_issue_files(store, issue_id, issue, idir: Path, source="journal-dl"):
    summ = issue_summary(store, issue_id)
    arts = [dict(r) for r in issue_rows(store, issue_id)]
    for a in arts:
        a["file"] = Path(a.pop("path")).name if a.get("path") else None
    man = {"source": source, "issue": {k: v for k, v in issue.items() if k != "pdf_href"},
           "summary": summ, "articles": arts,
           "note": "Individual article PDFs as listed in the online table of contents; "
                   "not a publisher-original issue PDF."}
    meta = files.meta_dir(idir.parent.parent) / "issues"
    _atomic_write(meta / f"{idir.name}.json", json.dumps(man, indent=2, ensure_ascii=False))
    lines = [f"# {idir.name}" + (f" (pages {issue.get('page_range')})" if issue.get("page_range") else ""), "",
             f"**Outcome:** {summ['outcome']}", "", "| | |", "|---|---|"] + \
            [f"| {k} | {v} |" for k, v in summ.items() if k not in ("issue", "outcome")]
    problems = [a for a in arts if a["state"] != "complete"]
    if problems:
        lines += ["", "## Not downloaded", ""] + [
            f"- #{a['sequence']} {a['title']} — {a['state']}" + (f" ({a['last_error']})" if a["last_error"] else "")
            for a in problems]
    _atomic_write(meta / f"{idir.name}.md", "\n".join(lines) + "\n")


def write_journal_report(store, journal_id, jdir: Path, name="journal_report"):
    j = store.one("SELECT * FROM journals WHERE id=?", journal_id)
    issues = store.q("SELECT * FROM issues WHERE journal_id=? ORDER BY list_order", journal_id)
    summ = [issue_summary(store, i["id"]) | {"year": i["year"]} for i in issues]
    tot = lambda k: sum(s[k] for s in summ)
    _atomic_write(files.meta_dir(jdir) / f"{name}.json",
                  json.dumps({"journal": dict(j), "issues": summ}, indent=2, ensure_ascii=False))
    lines = [f"# {j['title']}" + (f" (ISSN {j['issn']})" if j["issn"] else ""), "",
             f"Issues listed: {len(summ)} · contents read: {sum(s['discovery'] == 'complete' for s in summ)} · "
             f"articles: {tot('records')} · PDFs saved: {tot('validated_files')}/{tot('pdf_eligible')} · "
             f"no PDF: {tot('no_pdf')} · no access: {tot('access_denied')} · failed: {tot('failed')}", "",
             "| Year | Issue | Contents | Articles | PDFs | Outcome |", "|---|---|---|---|---|---|"]
    lines += [f"| {s['year']} | {s['volume']}({s['issue_label']}) {s['date'] or ''} | {s['discovery']} | {s['records']} | "
              f"{s['validated_files']}/{s['pdf_eligible']} | {s['outcome']} |" for s in summ if s["records"] or s["discovery"] != "pending"]
    _atomic_write(files.meta_dir(jdir) / f"{name}.md", "\n".join(lines) + "\n")


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- the runner
class BaseRunner:
    NAME = "site"
    LABEL = "Site"
    ITEM_S = 4.0                       # typical seconds a PDF download itself takes
    PAGE_S = 3.0                       # typical seconds a page load takes

    def __init__(self, ctx, store: Store, root: Path, log=print, discover_only=False, max_downloads=None,
                 confirm=None, pacing=None, plan_confirm=None, new_only=False):
        self.ctx, self.s, self.root, self.log = ctx, store, Path(root), log
        self.discover_only, self.max_downloads = discover_only, max_downloads
        self.confirm, self.plan_confirm, self.new_only = confirm, plan_confirm, new_only
        self.progress = Progress()
        self.pacer = Pacer(pacing or load_default(), times_since=self._times_since, log=log,
                           status=self.progress.line)
        self.stats = Stats()
        self.throttled = 0
        self.page = None
        self.journal_dir = None
        self.journal_title = None
        self.on_issue = None            # f(issue folder name, done, total): progress for resume
        self.folder_issue = {}          # issue key -> the issue as another site names it (alternating sites:
                                        # every site saves an issue into the same folder)

    @property
    def downloads(self):
        return self.stats.downloaded

    def _times_since(self, t):
        return [r[0] for r in self.s.q("SELECT installed_at FROM assets WHERE installed_at>=? "
                                       "AND source_hint NOT LIKE 'copied%' AND source_hint NOT LIKE 'adopted%' "
                                       "ORDER BY installed_at", t)]

    def check_disk(self):
        free = shutil.disk_usage(self.root).free
        if free < MIN_FREE_BYTES:
            raise Paused(f"low disk space on the archive drive: {free / 1024**3:.1f} GB free")

    def issue_dir(self, issue):
        return files.issue_dir(self.journal_dir, self.folder_issue.get(issue["key"], issue))

    def limit_reached(self):
        return self.max_downloads is not None and self.stats.downloaded >= self.max_downloads

    # ---------------------------------------------------- subclass hooks
    def _open(self, jid):                      # -> (info, journal row)
        raise NotImplementedError

    def _list(self, info, years):              # -> issues, newest first
        raise NotImplementedError

    def _discover(self, j, row, issue):        # read an issue's contents into the store
        raise NotImplementedError

    def _download_issue(self, j, row, issue):  # download the issue's pending items
        raise NotImplementedError

    def _fetch(self, r):                       # -> dict(state=..., data=..., msg=..., retry_after=..., ident=...)
        raise NotImplementedError

    def begin(self):                           # before the first page step (e.g. open a tab)
        pass

    def end(self):
        pass

    def _retrying(self, fn, *a):
        """Run a page step, waiting for a new sign-in if the session expired."""
        for _ in range(3):
            try:
                return fn(*a)
            except self.AuthRequired as e:
                self.wait_for_signin(str(e))
        return fn(*a)

    # ---------------------------------------------------- orchestration
    def open_journal(self, jid, title=None):
        """Open the journal; title: the folder name to use (default: the title this site shows)."""
        info, j = self._open(jid)
        self.journal_title = info["title"]
        self.jrow = j
        self.journal_dir = files.journal_dir(self.root, title or info["title"])
        return info, j

    def years_for(self, info, j, years=None, issue_hint=None, newest_have=None):
        """Which years' issue lists to read. newest_have: year of the newest issue with a download
        (default: from this site's database)."""
        if not years and issue_hint:
            m = re.match(r"\s*(?:vol(?:ume)?\.?\s*)?([\w.-]+)\s*\(", issue_hint, re.I)
            y = (info.get("vol_years") or {}).get(m.group(1)) if m else None
            if y:
                years = (y, y)
                self.log(f"Volume {m.group(1)} is {y}: reading only that year.")
        if self.new_only and not years:
            if newest_have is None:
                newest_have = self.newest_year_downloaded(j)
            last_year = info.get("last_year")
            if newest_have and last_year:
                years = (min(int(newest_have), int(last_year)), int(last_year))
            elif last_year:
                years = (int(last_year), int(last_year))
            if years:
                self.log(f"New issues only: checking {years[0]}" + (f"-{years[1]}" if years[1] != years[0] else ""))
        return years

    def newest_year_downloaded(self, j):
        r = self.s.one("""SELECT i.year FROM issues i JOIN issue_articles ia ON ia.issue_id=i.id
                          JOIN jobs jb ON jb.article_id=ia.article_id
                          WHERE i.journal_id=? AND jb.state='complete'
                          ORDER BY CAST(i.year AS INTEGER) DESC LIMIT 1""", j["id"])
        return int(r["year"]) if r and str(r["year"]).isdigit() else None

    def list_issues(self, info, j, years):
        issues = self._list(info, years)
        with self.s.tx():
            for n, i in enumerate(issues):
                self.s.upsert_issue(j["id"], i, n)
            self.s.db.execute("UPDATE journals SET issues_listed_at=? WHERE id=?", (time.time(), j["id"]))
        self.log(f"Found {len(issues)} issue(s)" + (f" in {years[0]}-{years[1]}" if years else "") + ".")
        return issues

    def issue_row(self, j, issue):
        return self.s.one("SELECT * FROM issues WHERE journal_id=? AND provider_key=?", j["id"], issue["key"])

    def run_journal(self, jid, years=None, issue_hint=None):
        self.begin()
        try:
            self._run_journal(jid, years, issue_hint)
        finally:
            self.end()

    def _run_journal(self, jid, years=None, issue_hint=None):
        info, j = self.open_journal(jid)
        jdir = self.journal_dir
        self.log("Covers:  " + (info.get("years") or "?") + (f"  (ISSN {info['issn']})" if info.get("issn") else ""))
        years = self.years_for(info, j, years, issue_hint)
        issues = self.list_issues(info, j, years)

        todo = issues
        if self.new_only:
            todo = self._newer_than_downloaded(j, issues)
            if not todo:
                self.log("No new issues since your last download.")
                return
        if self.confirm:
            chosen = self.confirm(info, todo, issues)
            if not chosen:
                raise Cancelled("nothing selected; nothing downloaded")
            if isinstance(chosen, list):
                todo = chosen
        rows = {i["key"]: self.issue_row(j, i) for i in todo}

        # read contents first (when few enough) so the estimate is exact
        unread = [i for i in todo if rows[i["key"]]["discovery_status"] != "complete"]
        exact = self.discover_only or len(unread) <= EXACT_PLAN_MAX
        if exact and unread:
            self.log(f"Reading the contents of {len(unread)} issue(s)...")
            for i in unread:
                self._retrying(self._discover, j, rows[i["key"]], i)
                rows[i["key"]] = self.s.one("SELECT * FROM issues WHERE id=?", rows[i["key"]]["id"])
        plan = self._plan(j, todo, rows, exact)
        self._announce(plan)
        if self.discover_only:
            self._finish(j, jdir)
            return
        if exact and plan.pending == 0:
            self.log("Nothing to download: everything selected is already saved.")
            self._finish(j, jdir)
            return
        if self.plan_confirm and not self.plan_confirm(plan):
            raise Cancelled("cancelled; nothing downloaded")

        self.start_progress(plan)
        for i in todo:
            row = rows[i["key"]]
            if row["discovery_status"] == "complete" and not self._pending(row["id"]):
                continue
            self.download_issue(j, row, i)
            if self.limit_reached():
                self.log(f"Reached --max {self.max_downloads} downloads, stopping.")
                break
        self._finish(j, jdir)

    def start_progress(self, plan):
        self.progress.total = min(plan.pending, self.max_downloads) if self.max_downloads else plan.pending
        self.progress.per_item = plan.estimate[1] / max(plan.pending, 1) if plan.pending else 10.0

    def download_issue(self, j, row, i):
        """One issue's pending PDFs, then its report and a database backup."""
        self.progress.label = files.issue_folder_name(self.folder_issue.get(i["key"], i))
        self.stats.issues.add(i["key"])
        if self.on_issue:
            self.on_issue(self.progress.label, self.progress.done, self.progress.total)
        self._retrying(self._download_issue, j, row, i)
        write_issue_files(self.s, row["id"], i, self.issue_dir(i), source=self.LABEL)
        self.s.backup_to(files.meta_dir(self.journal_dir) / f"{self.NAME}-backup.sqlite")

    def _finish(self, j, jdir, report="journal_report"):
        write_journal_report(self.s, j["id"], jdir, name=report)
        self.s.backup_to(files.meta_dir(jdir) / f"{self.NAME}-backup.sqlite")

    def _pending(self, issue_id):
        return self.s.one(f"""SELECT COUNT(*) n FROM issue_articles ia JOIN jobs USING(article_id)
                              WHERE ia.issue_id=? AND jobs.state IN ({','.join('?' * len(PENDING))})""",
                          issue_id, *PENDING)["n"]

    def _items(self, issue_id):
        return self.s.one("SELECT COUNT(*) n FROM issue_articles WHERE issue_id=?", issue_id)["n"]

    def _newer_than_downloaded(self, j, issues):
        """Issues listed above (newer than) the newest issue that has a downloaded PDF; only the newest
        issue when nothing has been downloaded from this journal yet."""
        have = {r["provider_key"] for r in self.s.q(
            """SELECT DISTINCT i.provider_key FROM issues i JOIN issue_articles ia ON ia.issue_id=i.id
               JOIN jobs jb ON jb.article_id=ia.article_id WHERE i.journal_id=? AND jb.state='complete'""", j["id"])}
        if not have:
            return issues[:1]
        out = []
        for i in issues:                       # newest first
            if i["key"] in have:
                break
            out.append(i)
        return out

    def _plan(self, j, todo, rows, exact):
        per = []
        known = [self._items(rows[i["key"]]["id"]) for i in todo if rows[i["key"]]["discovery_status"] == "complete"]
        avg = (sum(known) / len(known)) if known else 12
        pending = 0
        for i in todo:
            row = rows[i["key"]]
            if row["discovery_status"] == "complete":
                n, p = self._items(row["id"]), self._pending(row["id"])
                per.append((i, n, p, True))
            else:
                n = p = round(avg)
                per.append((i, n, p, False))
            pending += p
        recent = len(self._times_since(time.time() - 86400))
        pages = self._pages_for(per)
        est = estimate(self.pacer.p, min(pending, self.max_downloads or pending), pages,
                       item_s=self.ITEM_S, page_s=self.PAGE_S, done_recently=recent)
        return Plan(per, pending, all(x[3] for x in per), est)

    def _pages_for(self, per):
        return 0

    def _announce(self, plan):
        to_get = [x for x in plan.issues if x[2]]
        self.log("")
        for i, n, p, exact in plan.issues[:15]:
            what = f"{n} items" if exact else f"~{n} items (not read yet)"
            state = "already saved" if exact and not p else (f"{p} to download" if exact else "to download")
            self.log(f"   {files.issue_folder_name(i):<38} {what:<24} {state}")
        if len(plan.issues) > 15:
            self.log(f"   ... and {len(plan.issues) - 15} more issues")
        n = min(plan.pending, self.max_downloads) if self.max_downloads else plan.pending
        if self.discover_only:
            self.log(f"\n{plan.pending} PDF(s) would be downloaded"
                     + (f": {fmt_estimate(plan.estimate)} at this speed." if plan.pending else "."))
            return
        if n:
            rough = "" if plan.exact else " (rough: some issues not read yet)"
            self.log(f"\nPlan: {n} PDF(s) from {len(to_get)} issue(s), {fmt_estimate(plan.estimate)}{rough}"
                     f" at speed [{self.pacer.p.preset}].")

    # ---------------------------------------------------- one article
    def download(self, aid, r, adir: Path):
        job = self.s.job(aid)
        asset = self.s.one("SELECT * FROM assets WHERE article_id=?", aid)
        if job["state"] == "complete" and asset and (self.root / asset["path"]).exists() \
                and (self.root / asset["path"]).stat().st_size == asset["bytes"]:
            return
        if job["state"] in ("no_pdf", "access_denied") or not r["has_pdf"]:
            return
        if job["state"] == "failed" and job["attempts"] >= 3:
            return
        if self.limit_reached():
            return
        final = adir / files.article_filename(r["sequence"], r["authors"], r["title"],
                                              max_len=files.room_for_name(adir))
        if final.exists():                         # crash between rename and commit: adopt the file
            chk = check_pdf(final)
            if chk.ok:
                self.s.install_asset(aid, str(final.relative_to(self.root)), chk,
                                     identity_hint(chk, r["doi"], r["title"]), "adopted-existing-file")
                self.stats.adopted += 1
                self.log(f"   #{r['sequence']:>3} already in the folder: {final.name}")
                return
        other = find_existing_copy(r.get("doi"), self.root, self.s.path)
        if other:                                  # same article saved from another site: copy, don't download
            adir.mkdir(parents=True, exist_ok=True)
            tmp = adir / f".{files.safe(r['provider_id'])}.{os.getpid()}.part"
            shutil.copyfile(other, tmp)
            chk = check_pdf(tmp)
            if chk.ok:
                os.replace(tmp, final)
                self.s.install_asset(aid, str(final.relative_to(self.root)), chk,
                                     identity_hint(chk, r["doi"], r["title"]), f"copied-from:{other.name}")
                self.stats.copied += 1
                self.progress.done += 1
                self.log(f"   #{r['sequence']:>3} copied (already saved from another site): {final.name}")
                return
            tmp.unlink(missing_ok=True)
        self.check_disk()

        msg = ""
        for attempt in range(job["attempts"] % 3, 3):
            self.pacer.wait_download()
            self.s.set_job(aid, "downloading")
            try:
                res = self._fetch(r)
            except self.AuthRequired as e:
                self.s.set_job(aid, "auth_required")
                self.wait_for_signin(str(e))
                res = {"state": "retry", "msg": "signed in again"}
            except Paused:
                self.s.set_job(aid, "pending")
                raise
            except Exception as e:
                if _browser_gone(e):
                    self.s.set_job(aid, "pending")
                    raise
                res = {"state": "retry", "msg": f"{type(e).__name__}: {str(e)[:200]}"}
            state, msg = res["state"], res.get("msg", "")
            if state == "ok":
                installed = self._install(aid, r, adir, final, res)
                if installed:
                    self.pacer.on_success()
                    self.throttled = 0
                    self.stats.downloaded += 1
                    self.progress.done += 1
                    self.log(f"   {self.progress.count_done()} #{r['sequence']:>3} ok  {installed}")
                    return
                state, msg = "retry", res.get("msg") or "rejected"
            if state in ("access_denied", "no_pdf"):
                self.s.set_job(aid, state, msg)
                if state == "access_denied":
                    self.stats.denied += 1
                else:
                    self.stats.no_pdf += 1
                self.progress.done += 1
                self.log(f"   #{r['sequence']:>3} {'no access' if state == 'access_denied' else 'no PDF'}: {msg}")
                return
            self.s.set_job(aid, "retry_wait", msg, attempts_inc=1)
            self.s.event(f"article:{r['provider_id']}", "download", "retry", error=msg)
            if state == "rate_limited":
                self.pacer.on_throttle(res.get("retry_after"))
                self.throttled += 1
                if self.throttled >= 4:
                    raise Paused(f"{self.LABEL} keeps throttling; stopped to be safe. Try later or use --speed slow")
            else:
                self.pacer.on_error()
            if attempt < 2:
                d = self.pacer.retry_delay(attempt)
                if state == "rate_limited":
                    d = max(d, 300)
                self.log(f"   #{r['sequence']:>3} retry in {fmt(d)}: {msg}")
                sleep_i(d)
        self.s.set_job(aid, "failed", msg)
        self.stats.failed += 1
        self.progress.done += 1
        self.log(f"   #{r['sequence']:>3} FAILED after 3 attempts: {msg}")

    def _install(self, aid, r, adir, final, res):
        """Validate bytes and install atomically; returns a description, or None (res['msg'] says why)."""
        adir.mkdir(parents=True, exist_ok=True)
        tmp = adir / f".{files.safe(r['provider_id'])}.{os.getpid()}.part"
        tmp.write_bytes(res["data"])
        chk = check_pdf(tmp)
        if not chk.ok:
            q = files.meta_dir(self.journal_dir) / "quarantine"
            q.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, q / f"{files.safe(r['provider_id'])}-{int(time.time())}.bin")
            res["msg"] = f"rejected: {chk.reason}"
            return None
        ident = identity_hint(chk, r["doi"], r["title"])
        if ident == "unconfirmed" and res.get("ident"):
            ident = res["ident"]
        if final.exists():
            existing = check_pdf(final)
            if existing.ok and existing.sha256 == chk.sha256:
                tmp.unlink()
            elif existing.ok:                       # never silently overwrite a different valid file
                final = final.with_name(final.stem + f" (new {chk.sha256[:8]}).pdf")
                os.replace(tmp, final)
                self.s.event(f"article:{r['provider_id']}", "install", "kept-both", reason="different valid file existed")
            else:
                os.replace(tmp, final)
        else:
            os.replace(tmp, final)
        self.s.install_asset(aid, str(final.relative_to(self.root)), chk, ident, res.get("source", self.NAME))
        return f"{chk.pages}p {chk.bytes // 1024} KB {ident}  {final.name}"

    # ---------------------------------------------------- end of run
    def summary(self):
        st = self.stats
        parts = [f"{st.downloaded} downloaded"]
        if st.copied:
            parts.append(f"{st.copied} copied from another site")
        if st.adopted:
            parts.append(f"{st.adopted} already in folder")
        parts += [f"{st.failed} failed", f"{st.denied} no access"]
        if st.no_pdf:
            parts.append(f"{st.no_pdf} without PDF")
        return " · ".join(parts)


def _browser_gone(e) -> bool:
    t = str(e).lower()
    return any(k in t for k in ("target page, context or browser has been closed", "browser has been closed",
                                "connection closed", "browser closed", "target closed", "econnrefused"))
