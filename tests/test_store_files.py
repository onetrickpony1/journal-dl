# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

from pathlib import Path

from journal_dl import files
from journal_dl.store import Store


def art(seq, an, doi=None, has_pdf=True):
    return {"sequence": seq, "provider_id": an, "title": f"T{seq}", "doi": doi, "pages": "1-2",
            "authors": "Smith, A; Jones, B", "content_type": "Article", "has_pdf": has_pdf}


def test_duplicate_listing_one_article(tmp_path):
    s = Store(tmp_path / "a.sqlite")
    j = s.upsert_journal("ovid:1", "J", "1")
    for k in ("A", "B"):
        s.upsert_issue(j["id"], {"key": k, "year": "2020", "volume": "1", "issue": k, "link_text": k,
                                 "link_title": k, "date_text": "", "page_range": ""}, 0)
    a1 = s.record_article(1, art(1, "AN-1", "10.1/x"), 1)
    a2 = s.record_article(2, art(5, "AN-1", "10.1/x"), 1)   # same article listed in two issues
    assert a1 == a2 and len(s.q("SELECT * FROM articles")) == 1
    assert len(s.q("SELECT * FROM issue_articles")) == 2
    # same DOI, different provider record -> kept separate, never overwritten
    a3 = s.record_article(1, art(2, "AN-2", "10.1/x"), 1)
    assert a3 != a1
    # DOI-less and no-PDF records are kept and visible
    a4 = s.record_article(1, art(3, "AN-3", None, has_pdf=False), 1)
    assert s.job(a4)["state"] == "no_pdf"


def test_leases_recovered(tmp_path):
    s = Store(tmp_path / "a.sqlite")
    j = s.upsert_journal("ovid:1", "J", "1")
    s.upsert_issue(j["id"], {"key": "A", "year": "2020", "volume": "1", "issue": "1", "link_text": "",
                             "link_title": "", "date_text": "", "page_range": ""}, 0)
    a = s.record_article(1, art(1, "AN-1"), 1)
    s.set_job(a, "downloading")
    s.recover_leases()
    assert s.job(a)["state"] == "pending"


def test_backup_copy(tmp_path):
    s = Store(tmp_path / "a.sqlite")
    s.backup_to(tmp_path / "share" / "b.sqlite")
    assert (tmp_path / "share" / "b.sqlite").stat().st_size > 0


def test_names_readable_and_windows_safe():
    assert files.clean("CON") == "CON_"
    assert files.clean('Is There a Link?.') == "Is There a Link"
    assert files.clean("Title: A <bad> \"name\"/x*") == "Title - A bad name-x"
    assert files.journal_dir(Path("/r"), "Addictive Disorders & Their Treatment", "1531-5754") == \
        Path("/r/Addictive Disorders & Their Treatment")
    i = {"year": "2021", "volume": "20", "issue": "3", "date_text": "September 2021"}
    assert files.issue_dir(Path("/r"), i) == Path("/r/2021/Vol 20 No 3 - September 2021")
    assert files.issue_folder_name({**i, "issue": "Supplement 1", "date_text": "Spring 2017"}) == "Vol 20 Supplement 1 - Spring 2017"
    assert files.issue_folder_name({**i, "issue": "3-4"}) == "Vol 20 No 3-4 - September 2021"
    n = files.article_filename(7, "O'Brien, K; X, Y", "What? A title: with/slashes.", "001-2")
    assert n == "07 - What A title - with-slashes - O'Brien.pdf"
    assert len(files.article_filename(1, "A, B", "word " * 80)) < 130


def test_old_bookkeeping_folder_is_merged(tmp_path):
    import os
    import time
    j = tmp_path / "Journal"
    old = j / ".ovid-dl"
    (old / "issues").mkdir(parents=True)
    (old / "issues" / "a.md").write_text("old a")
    (old / "archive-backup.sqlite").write_text("db")
    (old / "journal_report.md").write_text("older report")
    new = j / ".journal-dl"
    new.mkdir()
    (new / "journal_report.md").write_text("newer report")
    past = time.time() - 100
    os.utime(old / "journal_report.md", (past, past))
    d = files.meta_dir(j)
    assert d == new and not old.exists()
    assert (new / "issues" / "a.md").read_text() == "old a"
    assert (new / "ovid-backup.sqlite").read_text() == "db"
    assert (new / "journal_report.md").read_text() == "newer report"
