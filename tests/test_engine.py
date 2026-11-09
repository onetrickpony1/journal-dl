# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""The shared engine end to end with a fake site: no browser, no network."""
import io

import pytest
from pypdf import PdfWriter

from journal_dl import engine, files, pacing
from journal_dl.engine import BaseRunner, Paused, RunLock
from journal_dl.store import Store


def pdf_bytes(text="x"):
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.add_metadata({"/Title": text})
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


ISSUES = [  # newest first, like the sites list them
    {"year": "2026", "volume": "79", "issue": "2", "date_text": "Summer 2026", "page_range": "105-301",
     "link_text": "Volume 79, Issue 2", "link_title": "Vol 79 Summer 2026", "key": "v79|i2"},
    {"year": "2026", "volume": "79", "issue": "1", "date_text": "Spring 2026", "page_range": "1-104",
     "link_text": "Volume 79, Issue 1", "link_title": "Vol 79 Spring 2026", "key": "v79|i1"},
]
ARTICLES = {k: [{"sequence": n, "provider_id": f"10.1/{k}.{n}", "doi": f"10.1/{k}.{n}", "title": f"Paper {n} of {k}",
                 "authors": "Smith, Anna", "content_type": "Article", "pages": None, "has_pdf": True}
                for n in (1, 2, 3)] for k in ("v79|i1", "v79|i2")}


class FakeRunner(BaseRunner):
    NAME, LABEL = "fake", "Fake"

    class AuthRequired(Exception):
        pass

    def __init__(self, *a, fail=(), **kw):
        super().__init__(*a, **kw)
        self.fail = set(fail)
        self.fetched = []

    def wait_for_signin(self, why):
        raise Paused("no sign-in in tests")

    def _open(self, jid):
        info = {"title": "Test Journal", "issn": "1234-5678", "years": "2025-2026", "last_year": 2026}
        return info, self.s.upsert_journal("fake:1", info["title"], info["issn"])

    def _list(self, info, years):
        return [dict(i) for i in ISSUES]

    def _discover(self, j, row, issue):
        with self.s.tx():
            for r in ARTICLES[issue["key"]]:
                self.s.record_article(row["id"], r, 1)
            self.s.db.execute("UPDATE issues SET discovery_status='complete' WHERE id=?", (row["id"],))

    def _download_issue(self, j, row, issue):
        if row["discovery_status"] != "complete":
            self._discover(j, row, issue)
        idir = files.issue_dir(self.journal_dir, issue)
        for r in ARTICLES[issue["key"]]:
            if self.limit_reached():
                break
            aid = self.s.one("SELECT id FROM articles WHERE provider_id=?", r["provider_id"])["id"]
            self.download(aid, r, idir)

    def _fetch(self, r):
        self.fetched.append(r["doi"])
        if r["doi"] in self.fail:
            return {"state": "access_denied", "msg": "no access"}
        return {"state": "ok", "data": pdf_bytes(r["title"])}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JOURNAL_DL_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(engine.shutil, "disk_usage", lambda p: type("U", (), {"free": 100 * 1024**3})())
    fast = pacing.Pacing(delay=(0, 0), page_delay=(0, 0), break_every=(0, 0), preset="test")
    fast.validate = lambda: fast
    monkeypatch.setattr(pacing, "FLOOR_S", 0)
    monkeypatch.setattr(engine, "sleep_i", lambda s: None)
    root = tmp_path / "archive"
    root.mkdir()
    return tmp_path, root, fast


def make(env, db="fake.sqlite", **kw):
    tmp, root, fast = env
    st = Store(tmp / "data" / db)
    r = FakeRunner(None, st, root, log=lambda *a: None, pacing=fast, **kw)
    r.pacer.sleep = lambda s: None
    return r


def test_plan_estimate_and_download(env):
    plans = []
    r = make(env, plan_confirm=lambda p: plans.append(p) or True)
    r.run_journal("1")
    assert plans and plans[0].pending == 6 and plans[0].exact
    assert plans[0].estimate[1] > 0
    assert r.stats.downloaded == 6
    pdfs = sorted(p.relative_to(env[1]).as_posix() for p in env[1].rglob("*.pdf"))
    assert pdfs[0] == "Test Journal/2026/Vol 79 No 1 - Spring 2026/01 - Paper 1 of v79i1 - Smith.pdf"
    assert (env[1] / "Test Journal" / ".journal-dl" / "journal_report.md").exists()
    # second run: nothing to do, and it says so without asking
    asked = []
    r2 = make(env, plan_confirm=lambda p: asked.append(p) or True)
    r2.run_journal("1")
    assert r2.stats.downloaded == 0 and not asked


def test_cancel_at_plan_downloads_nothing(env):
    r = make(env, plan_confirm=lambda p: False)
    with pytest.raises(Paused):
        r.run_journal("1")
    assert not list(env[1].rglob("*.pdf"))


def test_max_and_resume(env):
    r = make(env, max_downloads=2)
    r.run_journal("1")
    assert r.stats.downloaded == 2
    r2 = make(env)
    r2.run_journal("1")
    assert r2.stats.downloaded == 4               # only the rest
    assert len(r.fetched) + len(r2.fetched) == 6


def test_no_access_is_recorded_not_retried(env):
    r = make(env, fail={"10.1/v79|i1.2"})
    r.run_journal("1")
    assert r.stats.denied == 1 and r.stats.downloaded == 5
    r2 = make(env)
    r2.run_journal("1")
    assert r2.fetched == []


def test_same_doi_from_another_site_is_copied(env):
    make(env, db="other.sqlite").run_journal("1")          # "other site" saved all six
    r = make(env, db="fake.sqlite")
    # pretend it is a different journal folder so files don't already exist
    r._open = lambda jid: ({"title": "Test Journal Copy", "issn": None, "years": "2026", "last_year": 2026},
                           r.s.upsert_journal("fake:2", "Test Journal Copy", None))
    r.run_journal("2")
    assert r.stats.copied == 6 and r.stats.downloaded == 0 and r.fetched == []


def test_new_only(env):
    r = make(env, confirm=lambda info, todo, all_: [todo[1]])       # download only the older issue
    r.run_journal("1")
    r2 = make(env, new_only=True)
    r2.run_journal("1")
    assert r2.stats.downloaded == 3                              # the newer one
    assert all("i2" in d for d in r2.fetched)
    r3 = make(env, new_only=True)
    r3.run_journal("1")
    assert r3.stats.downloaded == 0


def test_summary_and_runlock(env, tmp_path):
    r = make(env)
    r.run_journal("1")
    assert r.summary().startswith("6 downloaded")
    lock = tmp_path / "x.lock"
    with RunLock(lock):
        with pytest.raises(SystemExit):
            with RunLock(lock):
                pass


def test_estimate_respects_caps_and_hours():
    p = pacing.preset("normal")
    base = pacing.estimate(p, 100)
    capped = pacing.Pacing(**{**vars(p), "max_per_hour": 10})
    assert pacing.estimate(capped, 100)[1] >= 9 * 3600
    night = pacing.Pacing(**{**vars(p), "hours": (22 * 60, 6 * 60)})
    assert pacing.estimate(night, 100)[1] == pytest.approx(base[1] * 3, rel=0.01)
    assert pacing.fmt_long(3 * 3600 + 15 * 60) == "3 h 15 min"
