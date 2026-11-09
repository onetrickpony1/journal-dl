# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""SQLite store. Lives on the local disk: SQLite locking does not work on the CIFS share,
so the database is local and a backup copy is written next to the archive after each issue."""
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS journals(
        id INTEGER PRIMARY KEY, provider_key TEXT UNIQUE, title TEXT, issn TEXT,
        discovered_at REAL, issues_listed_at REAL)""",
    """CREATE TABLE IF NOT EXISTS issues(
        id INTEGER PRIMARY KEY, journal_id INTEGER REFERENCES journals, provider_key TEXT,
        year TEXT, volume TEXT, issue_label TEXT, link_text TEXT, link_title TEXT, date_text TEXT,
        page_range TEXT, list_order INTEGER,
        discovery_status TEXT DEFAULT 'pending', pages_traversed INTEGER DEFAULT 0,
        discovered_at REAL, UNIQUE(journal_id, provider_key))""",
    """CREATE TABLE IF NOT EXISTS articles(
        id INTEGER PRIMARY KEY, provider_id TEXT UNIQUE, doi TEXT, title TEXT, authors TEXT,
        content_type TEXT)""",
    """CREATE TABLE IF NOT EXISTS issue_articles(
        issue_id INTEGER REFERENCES issues, article_id INTEGER REFERENCES articles,
        sequence INTEGER, results_page INTEGER, page_label TEXT, has_pdf INTEGER,
        PRIMARY KEY(issue_id, article_id))""",
    """CREATE TABLE IF NOT EXISTS assets(
        article_id INTEGER PRIMARY KEY REFERENCES articles, path TEXT, sha256 TEXT, bytes INTEGER,
        pages INTEGER, validation TEXT, identity TEXT, source_hint TEXT, installed_at REAL)""",
    """CREATE TABLE IF NOT EXISTS jobs(
        article_id INTEGER PRIMARY KEY REFERENCES articles, state TEXT DEFAULT 'pending',
        attempts INTEGER DEFAULT 0, next_attempt REAL DEFAULT 0, last_error TEXT, updated_at REAL)""",
    """CREATE TABLE IF NOT EXISTS discovery_pages(
        issue_id INTEGER REFERENCES issues, ordinal INTEGER, signature TEXT, rows INTEGER,
        completed_at REAL, PRIMARY KEY(issue_id, ordinal))""",
    """CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY, at REAL, run TEXT, entity TEXT, action TEXT, status TEXT, details TEXT)""",
]


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        for s in SCHEMA:
            self.db.execute(s)
        self.run = time.strftime("%Y%m%d-%H%M%S")

    # --- helpers
    def tx(self):
        return _Tx(self.db)

    def q(self, sql, *a):
        return self.db.execute(sql, a).fetchall()

    def one(self, sql, *a):
        return self.db.execute(sql, a).fetchone()

    def event(self, entity, action, status, **details):
        self.db.execute("INSERT INTO events(at,run,entity,action,status,details) VALUES(?,?,?,?,?,?)",
                        (time.time(), self.run, entity, action, status, json.dumps(details)))

    # --- journals / issues
    def upsert_journal(self, key, title, issn):
        self.db.execute("""INSERT INTO journals(provider_key,title,issn,discovered_at) VALUES(?,?,?,?)
                           ON CONFLICT(provider_key) DO UPDATE SET title=excluded.title, issn=excluded.issn""",
                        (key, title, issn, time.time()))
        return self.one("SELECT * FROM journals WHERE provider_key=?", key)

    def upsert_issue(self, journal_id, i: dict, order: int):
        self.db.execute("""INSERT INTO issues(journal_id,provider_key,year,volume,issue_label,link_text,link_title,
                               date_text,page_range,list_order) VALUES(?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(journal_id,provider_key) DO UPDATE SET link_text=excluded.link_text,
                               link_title=excluded.link_title, page_range=excluded.page_range,
                               list_order=excluded.list_order""",
                        (journal_id, i["key"], i["year"], i["volume"], i["issue"], i["link_text"],
                         i["link_title"], i["date_text"], i["page_range"], order))

    # --- articles
    def record_article(self, issue_id, a: dict, results_page: int):
        """Insert or match an article by provider id; returns article id. Never overwrites a
        different record that only shares a DOI."""
        row = self.one("SELECT id FROM articles WHERE provider_id=?", a["provider_id"])
        if row:
            aid = row["id"]
            self.db.execute("UPDATE articles SET title=?, authors=?, content_type=?, doi=COALESCE(?,doi) WHERE id=?",
                            (a["title"], a["authors"], a["content_type"], a["doi"], aid))
        else:
            aid = self.db.execute("INSERT INTO articles(provider_id,doi,title,authors,content_type) VALUES(?,?,?,?,?)",
                                  (a["provider_id"], a["doi"], a["title"], a["authors"], a["content_type"])).lastrowid
        self.db.execute("""INSERT INTO issue_articles(issue_id,article_id,sequence,results_page,page_label,has_pdf)
                           VALUES(?,?,?,?,?,?) ON CONFLICT(issue_id,article_id) DO UPDATE SET
                           sequence=excluded.sequence, results_page=excluded.results_page,
                           page_label=excluded.page_label, has_pdf=excluded.has_pdf""",
                        (issue_id, aid, a["sequence"], results_page, a["pages"], int(a["has_pdf"])))
        state = "pending" if a["has_pdf"] else "no_pdf"
        self.db.execute("INSERT INTO jobs(article_id,state,updated_at) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                        (aid, state, time.time()))
        if a["has_pdf"]:  # a PDF control appeared later: reopen
            self.db.execute("UPDATE jobs SET state='pending' WHERE article_id=? AND state='no_pdf'", (aid,))
        return aid

    def job(self, aid):
        return self.one("SELECT * FROM jobs WHERE article_id=?", aid)

    def set_job(self, aid, state, error=None, attempts_inc=0, next_attempt=0):
        self.db.execute("""UPDATE jobs SET state=?, last_error=?, attempts=attempts+?, next_attempt=?, updated_at=?
                           WHERE article_id=?""", (state, error, attempts_inc, next_attempt, time.time(), aid))

    def install_asset(self, aid, path, chk, identity, source_hint):
        with self.tx():
            self.db.execute("""INSERT INTO assets(article_id,path,sha256,bytes,pages,validation,identity,source_hint,installed_at)
                               VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(article_id) DO UPDATE SET path=excluded.path,
                               sha256=excluded.sha256, bytes=excluded.bytes, pages=excluded.pages,
                               validation=excluded.validation, identity=excluded.identity,
                               source_hint=excluded.source_hint, installed_at=excluded.installed_at""",
                            (aid, path, chk.sha256, chk.bytes, chk.pages, chk.reason, identity, source_hint, time.time()))
            self.set_job(aid, "complete")

    def recover_leases(self):
        """Jobs left mid-flight by a crash go back to pending."""
        self.db.execute("UPDATE jobs SET state='pending' WHERE state IN ('resolving','downloading','validating')")

    def backup_to(self, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        # SQLite can't lock on CIFS: snapshot locally, then plain-copy to the share
        local = self.path.with_name(self.path.stem + ".backup.sqlite")
        local.unlink(missing_ok=True)
        bk = sqlite3.connect(local)
        self.db.backup(bk)
        bk.close()
        part = dest.with_name(dest.name + ".part")
        shutil.copyfile(local, part)
        os.replace(part, dest)


class _Tx:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.execute("BEGIN IMMEDIATE")

    def __exit__(self, et, *_):
        self.db.execute("ROLLBACK" if et else "COMMIT")
