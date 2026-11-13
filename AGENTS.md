# journal-dl: notes for AI assistants

Project-specific rules. Read [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md) first: it has the run steps, the PDF
checks, the "Rules the code keeps" and a code map.

## Ground rules (never change these)

From [CONTRIBUTING.md](CONTRIBUTING.md) and [LEGAL.md](LEGAL.md):
- The user signs in themselves. journal-dl never handles passwords.
- No getting past CAPTCHAs, bot checks or paywalls, and no automatic answers to cookie or consent banners. When a
  site shows a check, wait for the user or stop.
- Only follow links and requests the site's own pages make. No guessed URLs and no bulk-download routes.
- Polite defaults: pacing is on, and whole-journal downloads ask first.

## Code

- `src/journal_dl/`: one module per site (`wiley.py`, `tandf.py`, `ovid.py`), plus a thin `*_dl.py` entry point for
  each. `frontend.py` is the `journal-dl` command, `engine.py` / `runner.py` / `site_runner.py` run a download, and
  `multisite.py` spreads one journal across sites.
- The browser is the user's own Chrome window driven by Playwright (`browser.py`). On Linux that can be Flatpak Chrome.
  PDFs are fetched inside the page, never with Playwright's HTTP client (Cloudflare tells them apart).
- State is a SQLite database per site. A crash must never make a job look finished.

## Tests

- `pip install -e ".[test]"`, then `pytest -q`. Tests run offline, without a browser. Keep it that way: use the
  HTML fixtures in `tests/fixtures/`, and run `sanitize.py` over any page saved from a real site before adding it
  (it removes cookies, session URLs and proxy links).
- Windows paths and Python 3.10 have both broken tests before. CI runs Linux, macOS and Windows × 3.10 and 3.13.
  macOS runners can queue for 20+ minutes.

## Releases

A release has these steps:
1. a commit titled `journal-dl X.Y.Z` that bumps `pyproject.toml` and `src/journal_dl/__init__.py`, and dates the
   CHANGELOG section
2. tag `vX.Y.Z` on that commit
3. a GitHub release titled `journal-dl X.Y.Z`, with that CHANGELOG section as its body

Users install from `main.zip` with uv, so anything pushed to `main` reaches anyone who reinstalls.
