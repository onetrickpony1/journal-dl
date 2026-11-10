# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Alternating between sites, with two fake sites that list the same issues differently."""
import random


from journal_dl import state
from journal_dl.multisite import Alternator, match_key
from journal_dl.store import Store
from test_engine import ARTICLES, ISSUES, FakeRunner, env  # noqa: F401,F811  (env: fixture)

# the same two issues as another site shows them: other keys, other dates, "No. 02"-style numbers
OTHER = [dict(i, key="other-" + i["key"], issue=f"No. 0{i['issue']}", date_text=f"{i['year']}")
         for i in ISSUES]


class OtherRunner(FakeRunner):
    NAME, LABEL = "other", "Other"

    def _open(self, jid):
        info = {"title": "Test Journal (Other)", "issn": "1234-5678", "years": "2026", "last_year": 2026}
        return info, self.s.upsert_journal("other:1", info["title"], info["issn"])

    def _list(self, info, years):
        return [dict(i) for i in OTHER]

    def _discover(self, j, row, issue):
        super()._discover(j, row, dict(issue, key=issue["key"].removeprefix("other-")))

    def _download_issue(self, j, row, issue):
        if row["discovery_status"] != "complete":
            self._discover(j, row, issue)
        for r in ARTICLES[issue["key"].removeprefix("other-")]:
            aid = self.s.one("SELECT id FROM articles WHERE provider_id=?", r["provider_id"])["id"]
            self.download(aid, r, self.issue_dir(issue))


def pair(env, seed=1, **kw):
    tmp, root, fast = env
    runners = []
    for cls, db in ((FakeRunner, "fake.sqlite"), (OtherRunner, "other.sqlite")):
        r = cls(None, Store(tmp / "data" / db), root, log=lambda *a: None, pacing=fast)
        r.pacer.sleep = lambda s: None
        runners.append((cls.LABEL, r, "1"))
    return Alternator(runners, log=lambda *a: None, rng=random.Random(seed), **kw), runners


def test_match_key_normalises_numbers():
    assert match_key({"volume": "79", "issue": "2"}) == match_key({"volume": "Volume 79", "issue": "No. 02"})
    assert match_key({"volume": "12", "issue": "3/4"}) == match_key({"volume": "12", "issue": "3 - 4"})
    assert match_key({"volume": "12", "issue": "3"}) != match_key({"volume": "12", "issue": "4"})


def test_alternates_and_uses_one_folder_per_issue(env):
    seen = set()
    for seed in range(12):                      # over several runs both sites get used
        alt, runners = pair(env, seed=seed)
        alt.run_journal()
        seen |= {label for label, r, _ in runners if r.fetched}
        # every PDF is in the preferred site's folders, whichever site fetched it
        pdfs = sorted(p.relative_to(env[1]).as_posix() for p in env[1].rglob("*.pdf"))
        assert len(pdfs) == 6
        assert all(p.startswith(("Test Journal/2026/Vol 79 No 1 - Spring 2026/",
                                 "Test Journal/2026/Vol 79 No 2 - Summer 2026/")) for p in pdfs)
        # reset for the next seed
        for p in list(env[1].rglob("*.pdf")):
            p.unlink()
        for db in (env[0] / "data").glob("*.sqlite*"):
            db.unlink()
    assert seen == {"Fake", "Other"}


def test_each_issue_from_one_site_only(env):
    alt, runners = pair(env, seed=3)
    alt.run_journal()
    assert alt.stats.downloaded == 6
    issues_by_site = [{d.split(".")[1] for d in r.fetched} for _, r, _ in runners]
    assert not (issues_by_site[0] & issues_by_site[1])


def test_started_issue_stays_with_its_site_and_done_is_skipped(env):
    alt, runners = pair(env, seed=0, max_downloads=1)
    alt.run_journal()
    first = next(r for _, r, _ in runners if r.fetched)
    started_issue = first.fetched[0].split(".")[1]
    for seed in range(6):                       # whatever the dice say, the started issue stays put
        alt2, runners2 = pair(env, seed=seed, max_downloads=1)
        alt2.run_journal()
        for _, r, _ in runners2:
            for d in r.fetched:
                if d.split(".")[1] == started_issue:
                    assert type(r) is type(first)
    alt3, runners3 = pair(env)
    alt3.run_journal()
    alt4, runners4 = pair(env)
    alt4.run_journal()
    assert alt4.stats.downloaded == 0 and not any(r.fetched for _, r, _ in runners4)


def test_max_counts_all_sites(env):
    alt, runners = pair(env, seed=5, max_downloads=4)
    alt.run_journal()
    assert alt.stats.downloaded == 4
    assert sum(len(r.fetched) for _, r, _ in runners) == 4


def test_state_remembers_alternation(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_path", lambda: tmp_path / "state.json")
    state.remember_sites("Test Journal", ["wiley", "ovid"])
    assert state.known_sites("test journal") == ["wiley", "ovid"]
    assert state.known_site("Test Journal") == "wiley"
    state.remember_sites("Test Journal", ["tandf"])
    assert state.known_sites("Test Journal") == ["tandf"]
