# Contributing

Bug reports and fixes are welcome, especially for site layout changes and for macOS and Windows.

- **Setup:** `python -m venv .venv`, then `.venv/bin/pip install -e ".[test]"` and `.venv/bin/pytest -q`.
  Tests run offline, without a browser.
- **A site changed its pages?** journal-dl stops with exit code 3 and says what it expected. Please include
  that message and the site in the issue. Never include cookies, session URLs or your institution's proxy
  links: `sanitize.py` shows what to remove.
- **Adding a site:** see "Adding a site" in [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).

Please keep the project's ground rules in every change:
- the user signs in themselves; no handling of passwords;
- no getting past CAPTCHAs or bot checks, and no automatic answers to cookie or consent banners;
- only follow links and requests the site's own pages make; no guessed addresses and no bulk-download routes;
- polite defaults: pacing on, and a question before any whole-journal download.

**Contributions.** By submitting a contribution you confirm you have the right to do so, and you license it
under the GNU General Public License v3.0 or later, on the same "as is", no-warranty terms. Contributions must keep to [LEGAL.md](LEGAL.md):
pull requests that add circumvention of access controls, CAPTCHAs, bot checks or rate limits, or that help
redistribute content, will not be accepted.
