# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Command line shared by journal-dl, ovid-dl, wiley-dl and tandf-dl.

Every command takes the same options. journal-dl also takes --site and, without it, finds the
journal on whichever site has it; a journal on several sites is downloaded alternating between them
at random, issue by issue (multisite.py), unless one site is chosen. Differences that come from the sites themselves:
- Taylor & Francis gives no months for its issues, so YYYY-MM is refused there (use -p or --issue).
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

from . import __version__, browser, files, notify, pacing, settings, signin, state, system
from .selection import make_confirm, parse_when
from .sites import ORDER, SITES, tidy_tabs

EXIT_NOT_FOUND, EXIT_PAUSED, EXIT_PAGE, EXIT_CTRL_C = 1, 2, 3, 130


def _interactive():
    return sys.stdin.isatty() and not os.environ.get("JOURNAL_DL_BACKGROUND")


def _yes(prompt, default=True):
    try:
        ans = input(prompt).strip().lower()
    except EOFError:
        return default
    return default if not ans else ans in ("y", "yes", "j", "ja")


# ---------------------------------------------------------------- parser
def epilog(site):
    prog = site.prog if site else "journal-dl"
    j = site.example_journal if site else "Personnel Psychology"
    y = site.example_year if site else 2026
    issue = site.example_issue if site else "Spring 2026"
    month = (f'  {prog} "{j}" {y}-{site.example_month:02d}  one month\'s issue\n'
             if site and site.has_months else "")
    find = "find journal names on all sites" if not site else "find journal names"
    return f"""examples:
  {prog} --easy                          step-by-step guide (start here)
  {prog} "{j}" {y}           one year
{month}  {prog} "{j}" {y - 2}-{y} -p   pick issues from a list
  {prog} "{j}" --issue "{issue}"
  {prog} "{j}" --new        only issues newer than what you have
  {prog} "{j}"              whole journal (asks first; -y skips)
  {prog} -s "{site.example_search if site else 'organizational'}"       {find}
  {prog} --status                        what has been downloaded
  {prog} --resume                        continue the last unfinished run
  {prog} --doctor                        check that everything is ready

Before downloading it shows how many PDFs and how long it will take at your speed setting.
Stop any time with Ctrl+C; run the same command again (or --resume) to continue."""


def build_parser(site=None):
    prog = site.prog if site else "journal-dl"
    where = f"from {site.label}" if site else "from Wiley, Taylor & Francis or Ovid"
    ap = argparse.ArgumentParser(prog=prog, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=epilog(site),
                                 description=f"Download article PDFs of a journal {where}, "
                                             "using your own library sign-in.")
    months = ", 2026-11 for one month" if (site is None or site.has_months) else ""
    ap.add_argument("journal", nargs="?", help="journal name (exact, or enough to match only one)")
    ap.add_argument("when", nargs="?", metavar="years", help=f"2021, 2018-2021{months} (default: all years)")

    g = ap.add_argument_group("what to download")
    g.add_argument("-s", "--search", metavar="TEXT", help="search journal names")
    g.add_argument("--issue", help=f'issue(s) by date or number, e.g. "{site.example_issue if site else "Spring 2026"}" '
                                   'or "79(2)"')
    g.add_argument("-p", "--pick", action="store_true", help="choose issues from a numbered list")
    g.add_argument("--new", action="store_true", help="only issues newer than the newest one you have")
    g.add_argument("-y", "--yes", action="store_true", help="don't ask before starting (needed for whole journals "
                                                            "in scripts)")
    g.add_argument("--dry-run", action="store_true", help="show what would be downloaded and how long it would take")
    g.add_argument("--max", type=int, metavar="N", help="stop after N PDFs")
    g.add_argument("-o", "--output", metavar="FOLDER", help=f"archive folder (now: {settings.output_dir()})")
    g.add_argument("--open", action="store_true", help="open the journal's folder when done (alone: the archive folder)")
    if site is None:
        g.add_argument("--site", choices=ORDER, help="use only this site (default: find the journal on any of them)")
        g.add_argument("--alternate", action="store_true",
                       help="look on every site again and, if the journal is on several, take each issue from "
                            "one of them at random (the default when found on several)")

    g = ap.add_argument_group("progress and files")
    g.add_argument("--status", action="store_true", help="what has been downloaded, and any unfinished run")
    g.add_argument("--resume", action="store_true", help="continue the last unfinished run")
    g.add_argument("--retry", action="store_true", help="try failed articles again")
    g.add_argument("--verify", action="store_true", help="re-check every saved PDF")

    g = ap.add_argument_group("convenience")
    g.add_argument("--easy", action="store_true", help="interactive step-by-step guide")
    g.add_argument("--background", action="store_true", help="run in the background (keeps going after the "
                                                             "terminal closes); see --log")
    g.add_argument("--log", action="store_true", help="show the latest background run's log")
    g.add_argument("--follow", action="store_true", help="follow this journal (for --update)")
    g.add_argument("--unfollow", action="store_true", help="stop following this journal")
    g.add_argument("--following", action="store_true", help="list followed journals")
    g.add_argument("--update", action="store_true", help="download new issues of every followed journal")
    g.add_argument("--schedule", choices=("weekly", "daily", "off"), help="run --update automatically")
    g.add_argument("--no-notify", action="store_true", help="no desktop notification for this run")

    g = ap.add_argument_group("setup and checks")
    g.add_argument("--doctor", action="store_true", help="check browser, sign-ins, archive folder, disk space")
    g.add_argument("--setup", action="store_true", help="set archive folder, library proxy and browser")
    g.add_argument("--browser", action="store_true", help="open the downloader's browser window (to sign in)")
    g.add_argument("--install-launcher", action="store_true", help="add a 'Journal Downloader' desktop icon")
    g.add_argument("--install-browser", action="store_true", help="download a private Chromium (only needed "
                                                                  "without Chrome, Chromium or Edge)")
    g = ap.add_argument_group("library access (default: your saved setting, else 'auto')")
    x = g.add_mutually_exclusive_group()
    x.add_argument("--direct", action="store_true", help="don't use the library proxy this run (on campus or VPN)")
    x.add_argument("--via-proxy", action="store_true", help="always go through the library proxy this run")
    pacing.add_arguments(ap)
    ap.add_argument("--version", action="version", version=f"{prog} {__version__}")
    return ap


# ---------------------------------------------------------------- the archive folder
def archive_root(a) -> Path:
    root = Path(a.output) if a.output else settings.output_dir()
    if not root.is_dir():
        # create it only when that is clearly safe: the default folder, or inside a folder that has
        # other things in it (an empty parent may be an unconnected network-drive mount point)
        if root == settings.paths.default_output() or (root.parent.is_dir() and any(root.parent.iterdir())):
            root.mkdir(parents=True, exist_ok=True)
        else:
            raise SystemExit(f"Archive folder not reachable: {root}\n"
                             "(Is the drive or network share connected? Change it with --setup or -o FOLDER.)")
    return root


# ---------------------------------------------------------------- finding the site
def resolve(a, journal) -> list:
    """-> the site(s) for a journal: --site, the per-site command, remembered, or looked up on every site.
    More than one site: download alternating between them."""
    if getattr(a, "site_obj", None):
        return [a.site_obj]
    if getattr(a, "site", None):
        return [SITES[a.site]]
    known = [n for n in state.known_sites(journal) if n in SITES]
    if known and not (getattr(a, "alternate", False) and len(known) < 2):
        return [SITES[n] for n in known]
    from playwright.sync_api import sync_playwright
    hits, near = [], {}
    with sync_playwright() as p:
        for name in ORDER:
            site = SITES[name]
            print(f"Looking for it on {site.label}...", end=" ", flush=True)
            try:
                ctx, tab = site.session(p)
                ok, res = site.pick(tab, journal)
            except (site.AdapterError, SystemExit) as e:
                print(f"could not check ({str(e)[:120]})")
                continue
            if ok:
                print(f"found: {res['title']}")
                hits.append((site, res))
            else:
                print("no")
                if res:
                    near[site.label] = res
    exact = [h for h in hits if state.key(h[1]["title"]) == state.key(journal)]
    hits = exact or hits                      # an exact title beats a near one ("Journal of X" vs "X")
    if not hits:
        print(f"\nNo site has a journal called {journal!r}.")
        for label, names in near.items():
            print(f"Close matches on {label}:\n  " + "\n  ".join(names[:10]))
        raise SystemExit(EXIT_NOT_FOUND)
    chosen = [h[0] for h in hits]
    if len(hits) > 1:
        print(f"\n{hits[0][1]['title']} is on {len(hits)} sites:")
        for n, (site, res) in enumerate(hits, 1):
            print(f"  {n}. only {site.label}" + ("  (publisher's own site)" if site.name != "ovid" else ""))
        print(f"  A. all {len(hits)}, each issue from one of them at random (spreads the load)")
        if _interactive() and not a.yes:
            ans = input(f"Which? [1-{len(hits)} or A, Enter = A] ").strip()
            if ans.isdigit() and 1 <= int(ans) <= len(hits):
                chosen = [hits[int(ans) - 1][0]]
    state.remember_sites(hits[0][1]["title"], [s.name for s in chosen])
    state.remember_sites(journal, [s.name for s in chosen])
    print(f"Using {' + '.join(s.label for s in chosen)}" + (", alternating" if len(chosen) > 1 else "")
          + ". (Next time it goes straight there; --site changes it.)\n")
    return chosen


# ---------------------------------------------------------------- downloading
def download(site, a, journal, years=None, issue=None, month=None, pick=False, when_arg=None, pace=None,
             keys=None, new=False, yes=False):
    """site: one Site, or a list of them (several: alternate between them, issue by issue)."""
    from contextlib import ExitStack

    from playwright.sync_api import sync_playwright
    from .engine import Cancelled, Paused, RunLock, _browser_gone
    from .store import Store
    sites = list(site) if isinstance(site, (list, tuple)) else [site]
    if month:                     # a site that dates issues by month must name them, or no issue matches
        sites.sort(key=lambda s: not s.has_months)
    site = sites[0]
    root = archive_root(a)
    whole = not (years or issue or month or pick or keys or new)
    yes = yes or a.yes
    if whole and not yes and not _interactive():
        raise SystemExit("A whole-journal download needs confirmation: add -y, or give years (e.g. 2021).")
    pace = pace or pacing.from_args(a)
    if issue and not years:                      # "September 2021" -> only read 2021's issue list
        m = re.search(r"\b(1[89]\d\d|20\d\d)\b", issue)
        if m:
            years = (int(m.group(1)), int(m.group(1)))
    started = time.monotonic()
    with ExitStack() as stack:
        for s in sites:
            stack.enter_context(RunLock(s.db.with_suffix(".lock")))
        p = stack.enter_context(sync_playwright())
        opened = []                                  # [(site, ctx, journal match)]
        ctxs = []
        stack.callback(lambda: ctxs and tidy_tabs(ctxs[0]))     # before Playwright stops (LIFO)
        for s in sites:
            if len(sites) > 1:
                print(f"Opening {s.label}...")
            try:
                ctx, tab = s.session(p)
                ctxs.append(ctx)
                ok, res = s.pick(tab, journal)
            except (s.AdapterError, SystemExit) as e:
                if s is site and len(sites) == 1:
                    raise
                print(f"  {s.label} could not be used this time ({str(e)[:120]}); skipping it.")
                continue
            if ok:
                opened.append((s, ctx, res))
            elif len(sites) == 1:
                print(f"No {s.label} journal matches {journal!r} exactly.")
                if res:
                    print("Did you mean one of these?\n  " + "\n  ".join(res[:20]))
                raise SystemExit(EXIT_NOT_FOUND)
            else:
                print(f"  {s.label} has no journal matching {journal!r} exactly; skipping it.")
        if not opened:
            print(f"No site could open {journal!r}.")
            raise SystemExit(EXIT_NOT_FOUND)
        site, ctx, res = opened[0]
        if len(sites) == 1:
            state.remember_site(res["title"], site.name)
        jdir = root / files.clean(res["title"], 100)
        print(f"Journal: {res['title']}  ({' + '.join(s.label for s, _, _ in opened)}"
              + (", alternating at random per issue)" if len(opened) > 1 else ")"))
        print(f"Files:   {system.show_path(jdir)}")
        print("Speed:  ", pace.describe())
        stores = {}
        for s, _, _ in opened:
            stores[s.name] = Store(s.db)
            stores[s.name].recover_leases()
        st = stores[site.name]

        def plan_ok(plan):
            if yes or not _interactive():
                return True
            if whole:
                print("Note: downloading whole journals may break your library's e-journal terms of use.")
            return _yes("Start? [y/N] " if whole else "Start? [Y/n] ", default=not whole)

        select = make_confirm(years, issue, month, pick, journal, when_arg, keys=keys, prog=a.prog,
                              interactive=_interactive())

        def confirm(info, todo, all_issues):
            sel = select(info, todo, all_issues)
            if sel and pick and not a.dry_run:          # remember picked issues so --resume gets the same ones
                state.update(last_run=dict(state.load().get("last_run") or {}, keys=[i["key"] for i in sel]))
            return sel

        if len(opened) == 1:
            r = site.runner(ctx, st, root, discover_only=a.dry_run, max_downloads=a.max, pacing=pace,
                            confirm=confirm, plan_confirm=plan_ok, new_only=new)
        else:
            from .multisite import Alternator
            r = Alternator([(s.label, s.runner(c, stores[s.name], root, discover_only=a.dry_run, pacing=pace,
                                               new_only=new), m["id"]) for s, c, m in opened],
                           confirm=confirm, plan_confirm=plan_ok, discover_only=a.dry_run,
                           max_downloads=a.max, new_only=new)
        spec = {"site": site.name, "journal": res["title"], "years": list(years) if years else None,
                "month": month, "issue": issue, "keys": keys, "new": new, "max": a.max}
        if len(opened) > 1:
            spec["sites"] = [s.name for s, _, _ in opened]
        if not a.dry_run:
            state.start_run(spec)
            r.on_issue = lambda where, done, total: state.progress(where, done, total)
        reason, code = "", 0
        try:
            r.run_journal(res["id"], years=years, issue_hint=issue)
        except Cancelled:
            print("\nNothing downloaded.")
            state.end_run(True, "cancelled")
            return 0
        except Paused as e:
            reason, code = str(e), EXIT_PAUSED
            print(f"\nStopped: {e}\nEverything downloaded so far is kept; run the same command (or --resume) "
                  "to continue.")
        except tuple({s.AdapterError for s, _, _ in opened}) as e:
            st.event("run", "adapter", "error", error=str(e))
            bad = next((s for s, _, _ in opened if isinstance(e, s.AdapterError)), site)
            reason, code = f"the {bad.label} page was not as expected: {e}", EXIT_PAGE
            print(f"\nStopped ({reason}).")
        except KeyboardInterrupt:
            reason, code = "stopped with Ctrl+C", EXIT_CTRL_C
            print("\nStopped. Progress is saved; run the same command (or --resume) to continue.")
        except Exception as e:
            if not _browser_gone(e):
                raise
            reason, code = "the browser window was closed", EXIT_PAUSED
            print("\nThe browser window was closed during the run. Progress is saved: run the same command "
                  "(or --resume) to continue; the window reopens by itself.")
        if a.dry_run:
            return code
        if r.stats.downloaded or r.stats.copied or r.stats.failed or r.stats.denied:
            print(f"\nSummary: {r.summary()}")
        if r.journal_dir:
            print(f"Files:   {system.show_path(r.journal_dir)}")
            rep = files.meta_dir(r.journal_dir) / "journal_report.md"
            if rep.exists():
                print(f"Report:  {system.show_path(rep)}")
        if code == 0 and r.limit_reached():
            reason = f"stopped after --max {a.max}"
        state.end_run(code == 0 and not r.limit_reached(), reason)
        long_run = time.monotonic() - started > 120 or os.environ.get("JOURNAL_DL_BACKGROUND")
        if code == 0 and long_run:
            notify.send("Download finished", f"{res['title']}: {r.summary()}")
        elif code not in (0, EXIT_CTRL_C):
            notify.send("Download stopped", f"{res['title']}: {reason}", urgent=True)
        if a.open and r.journal_dir:
            system.open_folder(r.journal_dir)
        return code


# ---------------------------------------------------------------- commands
def cmd_search(sites, a, text, quiet=False):
    from playwright.sync_api import sync_playwright
    found = {}
    with sync_playwright() as p:
        ctx = None
        for site in sites:
            try:
                ctx, tab = site.session(p)
                found[site] = site.search(tab, text)
            except (site.AdapterError, getattr(site, "ChallengeRequired", site.AdapterError),
                    getattr(site, "AuthRequired", site.AdapterError), SystemExit) as e:
                print(f"{site.label}: could not search ({e})")
        if ctx is not None and not quiet:     # quiet: the guide downloads next and reuses the open tabs
            tidy_tabs(ctx)
    for site, names in ({} if quiet else found).items():
        if len(sites) > 1:
            print(f"\n{site.label}:" + ("" if names else " none"))
        elif not names:
            print(f"No {site.label} journals match that.")
        for n in names:
            print(("  " if len(sites) > 1 else "") + n)
    return found


def cmd_status(sites, a):
    from .engine import issue_summary
    from .store import Store
    any_rows = False
    for site in sites:
        if not site.db.exists():
            continue
        st = Store(site.db)
        for j in st.q("SELECT * FROM journals ORDER BY title"):
            issues = [(i, issue_summary(st, i["id"]))
                      for i in st.q("SELECT * FROM issues WHERE journal_id=? ORDER BY list_order", j["id"])]
            issues = [(i, s) for i, s in issues if s["records"]]
            if not issues:
                continue
            any_rows = True
            got = sum(s["validated_files"] for _, s in issues)
            of = sum(s["pdf_eligible"] for _, s in issues)
            print(f"\n{j['title']}  ({site.label}): {got}/{of} PDFs")
            for i, s in issues:
                extra = []
                if s["failed"]:
                    extra.append(f"{s['failed']} failed")
                if s["pending"]:
                    extra.append(f"{s['pending']} to do")
                if s["access_denied"]:
                    extra.append(f"{s['access_denied']} no access")
                print(f"  {files.issue_folder_name({'volume': i['volume'], 'issue': i['issue_label'], 'date_text': i['date_text']}):<36}"
                      f" {s['validated_files']:>3}/{s['pdf_eligible']:<3} " + ", ".join(extra))
    if not any_rows:
        print("Nothing downloaded yet.")
    lr = state.unfinished()
    if lr:
        print(f"\nUnfinished: {lr['journal']} ({' + '.join(SITES[n].label for n in lr.get('sites') or [lr['site']])})"
              + (f", stopped in {lr['where']}" if lr.get("where") else "")
              + (f" ({lr['done']}/{lr['total']})" if lr.get("total") else "")
              + (f": {lr['reason']}" if lr.get("reason") else "") + ".  Continue with --resume")
    print(f"\nArchive folder: {system.show_path(settings.output_dir() if not a.output else Path(a.output))}")


def cmd_retry(sites):
    from .store import Store
    for site in sites:
        if site.db.exists():
            n = Store(site.db).db.execute("UPDATE jobs SET state='pending', attempts=0, last_error=NULL "
                                          "WHERE state IN ('failed','retry_wait')").rowcount
            print(f"{site.label}: {n} failed article(s) will be tried again on the next run.")


def cmd_verify(sites, a):
    from .store import Store
    from .validate import check_pdf
    root = Path(a.output) if a.output else settings.output_dir()
    total = bad = 0
    for site in sites:
        if not site.db.exists():
            continue
        st = Store(site.db)
        for s in st.q("SELECT * FROM assets"):
            total += 1
            f = root / s["path"]
            if not f.exists():
                print("MISSING", s["path"])
                bad += 1
                continue
            c = check_pdf(f)
            if not c.ok or c.sha256 != s["sha256"]:
                print("CHANGED/INVALID", s["path"], c.reason)
                bad += 1
    print(f"verified {total} files, {bad} problems")
    return 1 if bad else 0


def cmd_resume(a, site_filter=None):
    lr = state.unfinished()
    if not lr:
        print("Nothing to resume: the last run finished.")
        return 0
    if site_filter and lr["site"] != site_filter.name:
        print(f"The last unfinished run was on {SITES[lr['site']].label}: use "
              f"{SITES[lr['site']].prog} --resume or journal-dl --resume.")
        return 1
    run_sites = [SITES[n] for n in lr.get("sites") or [lr["site"]]]
    if site_filter:
        run_sites = [site_filter]
    print(f"Continuing: {lr['journal']} ({' + '.join(s.label for s in run_sites)})"
          + (f", from {lr['where']}" if lr.get("where") else ""))
    years = tuple(lr["years"]) if lr.get("years") else None
    return download(run_sites, a, lr["journal"], years, lr.get("issue"), lr.get("month"), keys=lr.get("keys"),
                    new=lr.get("new", False), yes=True)


def offer_resume(a, site_filter=None):
    lr = state.unfinished()
    if not lr or not _interactive() or (site_filter and lr["site"] != site_filter.name):
        return None
    where = f", stopped in {lr['where']}" if lr.get("where") else ""
    count = f" ({lr['done']}/{lr['total']})" if lr.get("total") else ""
    if _yes(f"Last time: {lr['journal']} ({SITES[lr['site']].label}){where}{count}. Continue? [Y/n] "):
        return cmd_resume(a, site_filter)
    state.end_run(True, "not resumed")
    return None


def cmd_update(sites, a):
    fl = [f for f in state.follows() if SITES.get(f["site"]) in sites]
    if not fl:
        print("No followed journals. Add one with:  journal-dl \"Journal name\" --follow")
        return 0
    worst = 0
    for f in fl:
        run_sites = [SITES[n] for n in f.get("sites") or [f["site"]] if SITES[n] in sites]
        if not run_sites:
            continue
        print(f"\n===== {f['title']} ({' + '.join(s.label for s in run_sites)}) =====")
        try:
            code = download(run_sites, a, f["title"], new=True, yes=True)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if not isinstance(e.code, int):
                print(e.code)
        worst = max(worst, code or 0)
    return worst


def cmd_follow(a, sites):
    site = sites[0]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx, tab = site.session(p)
        try:
            ok, res = site.pick(tab, a.journal)
        finally:
            tidy_tabs(ctx)
    if not ok:
        print(f"No {site.label} journal matches {a.journal!r} exactly."
              + ("\nDid you mean:\n  " + "\n  ".join(res[:10]) if res else ""))
        return EXIT_NOT_FOUND
    state.follow(site.name, res["title"], res.get("id"), sites=[s.name for s in sites])
    print(f"Following {res['title']} ({' + '.join(s.label for s in sites)}).\n"
          "  journal-dl --update               download its new issues (and other followed journals)\n"
          "  journal-dl --schedule weekly      do that automatically every Monday morning")
    return 0


def cmd_following():
    fl = state.follows()
    if not fl:
        print("No followed journals.")
    for f in fl:
        print(f"  {f['title']}  ({' + '.join(SITES[n].label for n in f.get('sites') or [f['site']])}, "
              f"since {f.get('since', '?')})")
    print(f"Automatic updates: {system.schedule_status()}")


# ---------------------------------------------------------------- guide
def ask_folder(a, ask=input):
    """The guide says where the PDFs go and offers to change it. A folder typed here is saved, like --setup's,
    until it is changed again ('default' goes back to Documents/Journal Downloads). Returns the folder."""
    if a.output or os.environ.get("JOURNAL_DL_OUTPUT") or os.environ.get("OVID_ARCHIVE_ROOT"):
        root = Path(a.output) if a.output else settings.output_dir()
        print(f"PDFs go to: {system.show_path(root)}" + ("" if a.output else "  (set by JOURNAL_DL_OUTPUT)"))
        return root
    cur = settings.output_dir()
    print(f"PDFs go to: {system.show_path(cur)}")
    while True:
        try:
            ans = ask("Enter = keep this folder, or type another one ('default' = "
                      f"{settings.paths.default_output()}): ").strip()
        except EOFError:
            ans = ""
        if not ans:
            return cur
        new = settings.paths.default_output() if ans.lower() == "default" else \
            Path(os.path.expandvars(ans.strip("'\""))).expanduser().resolve()
        if new == cur:
            return cur
        if new.exists() and not new.is_dir():
            print(f"  {new} is a file, not a folder.")
            continue
        if not new.exists():
            try:
                new.mkdir(parents=True)
                print(f"  created {new}")
            except OSError as e:
                print(f"  could not create {new}: {e}")
                continue
        value = None if new == settings.paths.default_output() else str(new)
        settings.save({"output": value})
        settings.S["output"] = value
        print(f"  Saved: from now on PDFs go to {system.show_path(new)} (change it here or with --setup).")
        if cur.is_dir() and any(cur.iterdir()):
            print(f"  Journals already downloaded stay in {cur}; move them over too, or journal-dl downloads\n"
                  "  those issues again when you continue or update them.")
        return new


def easy(a, site=None):
    from .speed_ui import ask_speed
    name = site.prog if site else "journal-dl"
    where = site.label if site else "Wiley, Taylor & Francis and Ovid"
    print(f"{name} guide: download journal articles from {where} with your library sign-in.\n")
    ask_folder(a)
    r = offer_resume(a, site)
    if r is not None:
        return r
    sites = [site] if site else [SITES[n] for n in ORDER]
    last = state.guide_defaults()
    options = []
    while True:
        hint = f" [Enter = {last['journal']}]" if last.get("journal") else ""
        text = input(f"Part of the journal name (e.g. '{(site or SITES['wiley']).example_search}'){hint}: ").strip()
        if not text and last.get("journal"):
            journal, chosen = last["journal"], SITES.get(last.get("site")) if not site else site
            if chosen:
                break
            text = journal
        if not text:
            return 0
        found = cmd_search(sites, a, text, quiet=True)
        options = [(s, n) for s in sites for n in found.get(s, [])][:40]
        if not options:
            print("Nothing found; try other words.")
            continue
        if len(options) == 1:
            chosen, journal = options[0]
            if not _yes(f"Found: {journal} ({chosen.label}). Is this the right journal? [Y/n] "):
                continue
            break
        print()
        for n, (s, j) in enumerate(options, 1):
            print(f"  {n:>2}. {j}" + (f"  ({s.label})" if len(sites) > 1 else ""))
        ans = input("Number of the journal (Enter to search again): ").strip()
        if ans.isdigit() and 1 <= int(ans) <= len(options):
            chosen, journal = options[int(ans) - 1]
            break
    while True:
        dflt = last.get("when") if last.get("journal") == journal else None
        hint = f"Enter = {dflt}" if dflt else "Enter = all years, slow for old journals"
        months = " or 2026-11" if chosen.has_months else ""
        yrs = input(f"Which year? e.g. 2026, 2018-2021{months}, or 'new' for issues newer than yours ({hint}): ").strip()
        yrs = yrs or (dflt or "")
        if yrs.lower() == "new":
            years = month = None
            break
        try:
            years, month = parse_when(yrs) if yrs else (None, None)
            if month and not chosen.has_months:
                raise SystemExit(f"{chosen.label} gives no months; give the year and pick issues from the list")
            break
        except SystemExit as e:
            print(f"  {e}")
    run_sites = [chosen]
    if not site:
        also = [s for s, n in options if s is not chosen and state.key(n) == state.key(journal)]
        if also and _yes(f"{journal} is also on {', '.join(s.label for s in also)}. Alternate between the sites at "
                         "random, issue by issue (spreads the load)? [Y/n] "):
            run_sites = sorted([chosen] + also, key=lambda s: ORDER.index(s.name))
    pace = ask_speed()
    state.remember_guide(journal=journal, site=chosen.name, when=yrs)
    if _interactive() and _yes("Follow this journal, so --update fetches its new issues later? [y/N] ", False):
        state.follow(run_sites[0].name, journal, sites=[s.name for s in run_sites])
    print(f"Reading the issue list from {' + '.join(s.label for s in run_sites)}...")
    return download(run_sites, a, journal, years, None, month=month, pick=yrs.lower() != "new",
                    when_arg=yrs, pace=pace, new=yrs.lower() == "new")


# ---------------------------------------------------------------- main
def run(site_name=None, argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    site = SITES[site_name] if site_name else None
    ap = build_parser(site)
    a = ap.parse_args(argv)
    a.prog = ap.prog
    a.site_obj = site
    notify.ENABLED = not a.no_notify
    settings.set_access_override("direct" if a.direct else "proxy" if a.via_proxy else None)
    sites = [site] if site else ([SITES[a.site]] if a.site else [SITES[n] for n in ORDER])
    try:
        code = _dispatch(ap, a, site, sites, argv)
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
        code = EXIT_CTRL_C
    raise SystemExit(code or 0)


def _dispatch(ap, a, site, sites, argv):
    from . import checks
    if a.show_speed or a.save_speed:
        try:
            p = pacing.from_args(a)
        except ValueError as e:
            raise SystemExit(f"{a.prog}: {e}")
        if a.save_speed:
            pacing.save_default(p)
            print(f"Saved as default ({pacing.CONFIG}):")
        print(p.describe())
        if not a.journal:
            return 0
    if a.setup:
        return checks.setup()
    if a.doctor:
        return checks.doctor(sites, a)
    if a.browser:
        if not settings.exists() and _interactive():
            print("First run: a few quick questions, so the window signs you in through your library "
                  "(change them later with --setup).\n")
            checks.setup()
            print()
        ok = browser.start(url="about:blank")
        if ok and signin.needed():
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                ok = signin.sign_in_once(browser.connect(p))
            print("Signed in through your library: downloads can start without you." if ok else
                  "Not signed in yet: the next run will ask again.")
            return 0 if ok else 1
        print("Browser window is open: sign in to your library there if needed." if ok else
              "The browser window did not start (see --doctor).")
        return 0 if ok else 1
    if a.install_browser:
        found = browser.find_chrome()
        if found and found != browser.bundled_chromium():
            print(f"A browser is already installed and will be used: {found}")
            return 0
        return 0 if browser.install_browser() else 1
    if a.install_launcher:
        system.install_launcher()
        return 0
    if a.schedule:
        return 0 if system.schedule(a.schedule) else 1
    if a.log:
        system.show_log()
        return 0
    if a.following:
        cmd_following()
        return 0
    if a.unfollow:
        if not a.journal:
            raise SystemExit("Which journal? e.g. --unfollow \"Personnel Psychology\"")
        n = state.unfollow(a.journal)
        print(f"Stopped following {a.journal}." if n else f"{a.journal} was not followed.")
        return 0
    if a.status:
        cmd_status(sites, a)
        return 0
    if a.verify:
        return cmd_verify(sites, a)
    if a.open and not a.journal:
        system.open_folder(Path(a.output) if a.output else settings.output_dir())
        return 0

    needs_web = a.easy or a.search or a.journal or a.update or a.resume
    if needs_web and not settings.exists():
        if _interactive():
            print("First run: a few quick questions (change them later with --setup).\n")
            checks.setup()
            print()
        elif a.background:
            raise SystemExit("journal-dl isn't set up yet: run  journal-dl --setup  in a terminal first "
                             "(it finds your library's proxy), then start the background run.")
        else:
            print(f"Note: journal-dl isn't set up yet ({settings.path()} is missing), so sites are opened "
                  "directly, without your library's proxy. Run  journal-dl --setup  once in a terminal.")

    if a.background:
        if a.easy or a.pick:
            raise SystemExit("--background can't ask questions: give years or --issue instead of -p / --easy.")
        if not (a.journal or a.update or a.resume):
            raise SystemExit("--background needs a journal, --update or --resume.")
        if a.journal and not (a.when or a.issue or a.new or a.yes):
            raise SystemExit("That would download the whole journal: add -y to confirm, or give years.")
        args = [x for x in (argv if argv is not None else sys.argv[1:]) if x != "--background"]
        if "-y" not in args and "--yes" not in args:
            args.append("-y")
        log = system.run_in_background(a.prog, args)
        print(f"Running in the background. You'll get a notification when it ends.\n"
              f"  progress: {a.prog} --log      (log file: {log})")
        return 0

    if a.easy:
        return easy(a, site or (SITES[a.site] if a.site else None))
    if a.search:
        cmd_search(sites, a, a.search)
        return 0
    if a.retry:
        cmd_retry(sites)
        if not a.journal:
            return 0
    if a.update:
        return cmd_update(sites, a)
    if a.resume:
        return cmd_resume(a, site)
    if not a.journal:
        if _interactive():
            r = offer_resume(a, site)
            if r is not None:
                return r
        ap.print_help()
        return 0

    targets = resolve(a, a.journal)
    if a.follow:
        return cmd_follow(a, targets)
    target = next((t for t in targets if t.has_months), targets[0])
    years, month = parse_when(a.when)
    if month and not target.has_months:
        raise SystemExit(f"{target.label} doesn't give months for its issues: use the year with -p to pick issues, "
                         f'or --issue "{target.example_issue}".')
    try:
        pace = pacing.from_args(a)
    except ValueError as e:
        raise SystemExit(f"{a.prog}: {e}")
    return download(targets, a, a.journal, years, a.issue, month=month, pick=a.pick, when_arg=a.when, pace=pace,
                    new=a.new)


def main(argv=None):
    run(None, argv)


if __name__ == "__main__":
    main()
