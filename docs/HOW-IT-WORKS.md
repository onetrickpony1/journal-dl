# How it works

## A run, step by step

1. **Browser.** Connect to the downloader's own Chrome window (start it if needed) and make sure the site is
   signed in. If it isn't, wait for you to sign in.
2. **Journal.** Find the exact title on the site (search, then an exact match or a single match).
3. **Issue list.** Read only the years needed: the years asked for, the year a `--issue "79(2)"` volume belongs
   to, or, for `--new`, from the newest year you have.
4. **Selection.** Narrow down to the month, `--issue`, picked issues or new issues.
5. **Contents and plan.** Read each selected issue's table of contents into the database, count what is still
   missing, estimate the time and ask to start.
6. **Download.** One PDF at a time, with pacing, checks and retries (below).
7. **Reports.** Write a summary per issue and per journal, back up the database next to the archive, and send
   a notification.

Everything is recorded in a SQLite database per site (journals, issues, articles, files, jobs, events).
A job is `pending`, `downloading`, `complete`, `failed`, `no_pdf` or `access_denied`. A crash leaves at most one
job `downloading`, and that job goes back to `pending` on the next start. This is what lets `--resume` and
re-running the same command carry on without downloading anything twice.

## Checking each PDF

Content type and file extension are never trusted. Bytes are written to a hidden `.part` file, then checked:
not empty, starts with `%PDF-`, ends with `%%EOF`, opens with pypdf, has pages. Its SHA-256 is recorded.
Only then is the file renamed into place, so an interrupted download never looks finished. Anything that fails
the check goes to `.journal-dl/quarantine/` and the article is retried, at most 3 attempts with growing waits.
A different valid file already at the same name is never overwritten: the new one is kept beside it.

Each file's identity is also checked: the DOI or title must appear on the PDF's first page, or (on Ovid) the
accession number in the PDF address must match the article. The result goes in the report
(`confirmed-doi`, `confirmed-title`, `confirmed-accession` or `unconfirmed`).

If another site's database already has a valid PDF with the same DOI, that file is copied instead of
downloading it again.

## Pacing

`pacing.py` decides every wait: the delay before each download (a range, spread uniformly, normally or
exponentially, plus jitter), delays between page loads, breaks, rolling hourly and daily limits counted from
the database across runs, an allowed daily time window, and AIMD back-off. On HTTP 429/503 it multiplies the
delay and honours `Retry-After`; successes gradually undo it. The same model produces the time estimate.

## The sites

| | Wiley | Taylor & Francis | Ovid |
|---|---|---|---|
| addresses | stable: `/loi/<eISSN>/year/<yyyy>`, `/toc/<eISSN>/<yyyy>/<vol>/<iss>` | stable: `/loi/<code>`, `/toc/<code>/<vol>/<iss>` | session state: navigation by clicking, checked against the issue heading |
| issue dates | month or season | year only | month |
| contents | one page per issue | one page per issue | 50 per results page, followed to the end |
| PDF | `/doi/pdfdirect/<doi>` in the signed-in session | the site's viewer requests a one-time signed `/doi/pdfdirect/<doi>?hmac=…`; journal-dl opens the viewer in its own tab and fetches that same request | each PDF opens in its own tab; the bytes are fetched again in the signed-in session (Chrome's viewer hides them) |
| notes | Early View is skipped | volume buttons are pressed in the page; the cookie layer is left alone | "Publish Ahead of Print" is skipped; Ovid's own session-timeout notice is closed when it blocks the page |

journal-dl only follows links and requests that the site's own pages make. It never guesses addresses to reach
content, and never looks for bulk or text-mining routes.

## Rules the code keeps

- No passwords: you sign in yourself in the browser window.
- No getting past bot checks (CAPTCHA, "verify you are human"), and no answering cookie or consent banners.
- Stop and say why when a page doesn't look as expected (exit code 3) rather than guessing, so a site
  redesign can't fill the archive with wrong files.
- Never write session tokens to logs or reports (`sanitize.py`).

## Adding a site

A site is a module like `wiley.py` or `tandf.py` with:

```
NAME, LABEL, PROG, HOST_HINT, HAS_MONTHS, EXAMPLE_*      # names and help text
AdapterError, AuthRequired, ChallengeRequired, RateLimited
goto(page, path), signed_in(page), login_hints()
search_journals(page, text) -> [{"title", "id"}]
pick_journal(page, text) -> (True, {"title", "id"}) | (False, [titles])
journal_info(page, id) -> {"title", "issn", "years", "year_list", "vol_years"}
list_issues(page, id, year) -> [{"year", "volume", "issue", "date_text", "page_range", "key", "toc", ...}]
parse_issue(page, issue) -> [{"sequence", "provider_id", "doi", "title", "authors", "pages", "has_pdf", ...}]
fetch_pdf(ctx, doi) -> (status, headers, body, final_url)
```

Register it in `sites.py` (`SITES`, `ORDER`) and add a `<name>_dl.py` entry point. The engine, pacing,
checks, reports and every command-line option then work for it. To see how a new site delivers PDFs, open an
issue in the browser window and run `python -m journal_dl.probe`.

## Code map

| | |
|---|---|
| `frontend.py` | command line shared by all commands; downloads, status, resume, guide, follow/update |
| `sites.py` | the three sites behind one interface |
| `engine.py` | run flow, plan and estimate, per-article download, checks, reports, run lock |
| `runner.py` / `site_runner.py` | Ovid's page handling / Wiley and T&F's |
| `ovid.py`, `wiley.py`, `tandf.py` | reading each site's pages |
| `pacing.py`, `speed_ui.py` | speed model and estimate / the guide's speed questions |
| `selection.py` | years, months, `--issue`, the picker |
| `store.py`, `validate.py`, `files.py`, `sanitize.py` | database, PDF checks, folder and file names, redaction |
| `settings.py`, `paths.py`, `state.py` | settings, per-OS folders, remembered state |
| `notify.py`, `system.py`, `checks.py`, `browser.py` | notifications, OS helpers (open, launcher, schedule, background), `--doctor`/`--setup`, the browser window |
