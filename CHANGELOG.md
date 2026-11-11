# Changelog

## 1.1.1 — 2026-11-11

### Fixes
- **The private Chromium from `--install-browser` now starts during a run.** When the browser window
  wasn't already open, a run reported "Could not find Google Chrome, Chromium or Microsoft Edge" although
  `--doctor` found the private Chromium: its location was looked up with a second Playwright session, which
  Playwright doesn't allow inside the running one.
- **Flatpak browsers on Linux.** Google Chrome, Chromium and Edge installed from Flathub are found, and are
  started with access to the downloader's profile folder (without it the sandbox kept the profile private and
  every sign-in was lost on restart). `"chrome"` in the settings also takes `flatpak run com.google.Chrome`.
  Microsoft Edge installed as `microsoft-edge-stable` is found too.

## 1.1.0 — 2026-11-10

### Signing in and first run
- **One sign-in for every site.** With a library proxy, a run first checks the proxy's sign-in and, if needed,
  asks once (one notification, one sign-in page) instead of each site waiting for its own. `--browser` does
  the same, so you can sign in ahead of a scheduled run.
- **`--setup` finds your library's proxy itself.** You open one article through your library in the browser
  window; it reads the proxy and sign-in page from the addresses (no need to know `proxy.….edu`). `--browser`
  runs the setup first when there are no settings, and a `--background` run without settings stops and says
  to run `--setup` instead of waiting for a sign-in that can't work.
- **Library access `auto`** (new default when a proxy is set): at the start of each run journal-dl checks whether
  Wiley or Taylor & Francis already recognise your institution (on campus or VPN) and then goes direct instead
  of through the proxy. A run never switches route mid-way; if direct access is lost it pauses, and `--resume`
  checks again. New `access` setting, `--direct` / `--via-proxy`, and `--doctor` shows the route.
- **Ovid opens through the proxy** (or on campus) by itself; the library catalogue settings are now optional.

### Downloading
- **New speed preset `superslow`:** 5-15 min between PDFs, a 30-60 min break every 4-8, at most 6/hour and 50/day.
  The README now spells out what the hourly and daily limits count (PDFs per site, rolling window, all runs).
- **Alternating between sites.** A journal found on several sites is downloaded issue by issue from a randomly
  chosen one of them, into the same folders. An issue started on one site is finished there; one complete on
  any site is skipped. `--site` pins one site; `--alternate` looks again for a journal remembered on one.

### Fixes
- Taylor & Francis showed "not signed in" while signed in: its "Access provided by" line sits in a hidden
  menu, and a cookie notice hid the rest. Sign-in checks now read the whole page, and a site waiting for a
  sign-in reloads once a minute instead of every 3 seconds.
- Custom speed (`--easy`): a value typed with brackets, like the `[5s-12s]` the prompt shows, is now accepted
  (`[1m-5m]` was rejected as `'[1m'`).
- Custom speed (`--easy`): pressing Enter at "Only download between" with no hours set no longer repeats
  the question forever.

## 1.0.0 — 2026-11-09

First public version.

- `journal-dl` finds a journal on Wiley, Taylor & Francis or Ovid; `wiley-dl`, `tandf-dl` and `ovid-dl` take
  the same options for one site each.
- Plan and time estimate before every download; live progress line with the time left.
- Resume (`--resume`, or offered automatically), `--new`, follow + `--update`, `--schedule weekly|daily`.
- Background runs (`--background`, `--log`) and notifications (desktop; optional ntfy).
- `--doctor`, `--setup`, `--install-launcher`, `--open`.
- PDFs already saved from another site (same DOI) are copied instead of downloaded again.
- Speed presets and a full pacing model (ranges, spread, jitter, breaks, hourly/daily caps, hours, back-off).
- Licensed under the GNU GPL v3.0 or later; legal notice and terms of use (LEGAL.md), summarised in the README.
- One-line installers (install.ps1, install.sh): Python, packages, PATH, browser and desktop icon, no admin rights;
  `--install-browser` downloads a private Chromium when no Chrome/Chromium/Edge is installed.
- Linux, macOS and Windows: per-OS folders, run lock, browser discovery, launchers, schedules, path-length limits.
