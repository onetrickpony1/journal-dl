# journal-dl

A personal research tool that automates **your own** signed-in browser session to save the article PDFs you are
already entitled to read on **Wiley Online Library**, **Taylor & Francis Online** and **Ovid**, into a tidy
folder.

> **Legal notice.** journal-dl gives no access to any content. You may only use it for content you are
> authorised to access, within your institution's licence terms, each site's terms of use and the law.
> **You alone are responsible for your use.** The software comes with **no warranty**, and the authors accept
> **no liability** for any use of it. Using it means you accept the [Legal Notice and Terms of Use](LEGAL.md).

```
journal-dl "Personnel Psychology" 2026
```

```
Journal: Personnel Psychology  (Wiley)
Files:   ~/Documents/Journal Downloads/Personnel Psychology

   Vol 79 No 3 - Autumn 2026              7 items                  7 to download
   Vol 79 No 2 - Summer 2026              9 items                  9 to download
   Vol 79 No 1 - Spring 2026              8 items                  8 to download

Plan: 24 PDF(s) from 3 issue(s), about 25 min (14 min to 35 min) at speed [normal].
Start? [Y/n]
   [3/24]  Vol 79 No 1 - Spring 2026  next in 8s  about 22 min left
```

## Features

- **One command for three sites.** `journal-dl` finds the journal on whichever site has it. If more than one
  site has it, it asks which to use. `wiley-dl`, `tandf-dl` and `ovid-dl` do the same for one site each, with
  the same options.
- **Time estimate before starting**, and a live progress line with the time left.
- **Safe to stop at any point.** Press Ctrl+C, then run the same command again or use `--resume`. Nothing is
  downloaded twice.
- **Tidy folders:** `<Journal>/<year>/Vol 79 No 1 - Spring 2026/01 - <Title> - <Surname>.pdf`
- **Every PDF is checked** (real PDF, complete, readable) before it is kept, and `--verify` re-checks them all.
- **Paced like a person.** Speed presets (fast, normal, careful, slow), random delays, breaks, hourly and daily
  limits, allowed hours, and automatic slow-down when a site pushes back.
- **Only new issues:** `--new`, or follow journals and run `--update` (by hand or every week with `--schedule`).
- **Background runs** with desktop notifications when a run ends, stops or needs you to sign in again. Phone
  notifications through ntfy are optional.
- **Step-by-step guide** (`--easy`) that remembers your last answers, and a desktop icon for it.
- **Checks:** `--doctor` tests the browser, sign-ins, the archive folder and free disk space. A file already
  saved from another site (same DOI) is copied rather than downloaded again.
- **Linux, macOS and Windows.**

## Legal notice and responsible use

**Read [LEGAL.md](LEGAL.md) before using journal-dl.** By installing, running, copying, modifying or distributing it,
you agree to that notice. In short:

- **It is a client-side automation tool, not an access service.** It runs on your computer and drives your own
  browser session, which you sign in to yourself. It hosts, shares and distributes no content, holds no
  subscriptions or credentials, and never sees your password.
- **You alone are responsible** for following your institution's licence agreements, each website's terms of
  use, and all applicable law (copyright, database rights, contract, computer misuse, data protection).
- **Many institutional licences forbid systematic, automated or bulk downloading** (for example whole
  journals or volumes) and the use of robots or scripts. Breaches can lead a publisher to **cut off access for
  your whole institution**, and can have disciplinary or legal consequences for you. **Check your library's
  terms first; if in doubt, don't.**
- **Never share or redistribute** downloaded articles with anyone not entitled to them, and don't use them to
  build datasets or train models unless your licence allows it.
- **No circumvention.** journal-dl does not bypass paywalls, authentication, CAPTCHAs, bot checks, rate limits
  or DRM. When a site shows one of these, it stops. It never answers cookie or consent banners.
- **Features are not permissions.** The existence of a feature (whole-journal runs, background runs, schedules,
  speed presets) does not mean you may use it. Defaults and examples are technical illustrations, not legal
  advice or a promise of compliance.
- **No warranty, no liability, indemnity.** The software is provided "as is". To the maximum extent the law
  allows, the authors are not liable for any loss, damage, claim, suspended access or other consequence of your
  use, and you agree to indemnify them against third-party claims arising from it.
- **Not affiliated** with Wiley, Taylor & Francis, Wolters Kluwer (Ovid), OCLC (EZproxy), Google or any library.
  Names are used only to say which services the tool works with.
- **Not legal advice.** Ask your library or a lawyer about your own situation.

## Install

One line, no admin rights needed. It installs everything journal-dl needs: its own Python if yours is missing
or too old, the packages, and a private Chromium if you have no Chrome, Chromium or Edge. It also offers a
desktop icon.

**Windows** (PowerShell):
```
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/onetrickpony1/journal-dl/main/install.ps1 | iex"
```

**macOS and Linux** (Terminal):
```
curl -LsSf https://raw.githubusercontent.com/onetrickpony1/journal-dl/main/install.sh | sh
```

Then open a new terminal window. To update, run the same line again. To uninstall: `uv tool uninstall journal-dl`.

<details><summary>What the installer does, and other ways to install</summary>

The installer ([install.ps1](install.ps1), [install.sh](install.sh)) installs [uv](https://docs.astral.sh/uv/),
a Python manager, if it's missing. uv then installs journal-dl in an isolated environment with its own
Python 3.12 if needed, and puts `journal-dl`, `ovid-dl`, `wiley-dl` and `tandf-dl` on your PATH. If no browser
is found, it runs `journal-dl --install-browser`. Read the scripts first if you like: they are short.

With Python 3.10+ already installed you can also use `pipx install` or `pip install` with
`https://github.com/onetrickpony1/journal-dl/archive/refs/heads/main.zip`.

On Linux without Chrome or Chromium, the private Chromium may need a few system libraries; installing Chromium
from your distribution is the easiest fix.
</details>

## First run

```
journal-dl --setup      # archive folder + your library's proxy address (once)
journal-dl --easy       # the guide: pick a journal, years, speed, issues
```

A browser window opens. Sign in to your library there when asked; the sign-in is kept for later runs.
`journal-dl --doctor` checks that everything is ready.

**Library proxy.** Off campus, most libraries give access through an EZproxy address. Open any journal through
your library's website and look at the address bar: on `onlinelibrary-wiley-com.proxy.library.example.edu`,
the proxy is `proxy.library.example.edu`. On campus or on VPN, leave it empty.

## Everyday use

| Command | What it does |
|---|---|
| `journal-dl "Journal name" 2026` | one year (`2018-2021` for a range, `2026-11` for one month) |
| `journal-dl "Journal name" 2024-2026 -p` | pick issues from a numbered list |
| `journal-dl "Journal name" --issue "79(2)"` | one issue by number or date (`"Spring 2026"`) |
| `journal-dl "Journal name" --new` | only issues newer than the newest one you have |
| `journal-dl "Journal name"` | whole journal (asks first) |
| `journal-dl -s "organizational"` | search journal names on all sites |
| `journal-dl --status` | what has been downloaded, and any unfinished run |
| `journal-dl --resume` | continue the last unfinished run |
| `journal-dl "Journal name" 2026 --background` | keep running after the terminal closes (`--log` shows progress) |
| `journal-dl "Journal name" --follow` then `--update` | fetch new issues of followed journals |
| `journal-dl --schedule weekly` | run `--update` every Monday morning |
| `journal-dl --open` | open the archive folder |
| `journal-dl --install-launcher` | add a "Journal Downloader" desktop icon |

Add `--dry-run` to any download to see the plan and time estimate without downloading.
The full list of options is in [docs/USAGE.md](docs/USAGE.md).

### Speed

```
journal-dl "Journal name" 2026 --speed careful
journal-dl --speed slow --hours 22:00-07:00 --save-speed      # make it the default
journal-dl "Journal name" 2026 --delay 20-60 --break-every 10-20 --break-for 5m-10m --max-per-hour 60
```

| Preset | Between PDFs | Breaks | Limits |
|---|---|---|---|
| fast | 3-6 s | none | none |
| normal (default) | 5-12 s | 1-3 min every 25-40 | none |
| careful | 10-25 s | 3-8 min every 15-30 | 120/hour |
| slow | 30-90 s | 5-15 min every 10-20 | 40/hour, 300/day |

### Differences between the sites

All four commands take the same options, but the sites themselves differ in a few ways:
- **Taylor & Francis** gives no month for its issues, so `2026-11` is refused there. Use the year with `-p`, or
  `--issue "34(2)"`.
- **Ovid** is reached through your library catalogue. Set it up with `--setup`, or open Ovid yourself in the
  browser window the first time.
- **Ovid** issue pages are read by clicking through them, so Ovid runs are slower than Wiley or T&F runs.

## Where things go

- **PDFs:** the archive folder (default `Documents/Journal Downloads`).
- **Per journal:** a hidden `.journal-dl/` folder with a report (`journal_report.md`), one summary per issue,
  a database backup and any rejected downloads (`quarantine/`).
- **Settings and progress:** see [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Documentation

- [docs/USAGE.md](docs/USAGE.md): every option, the guide, background runs, following journals, exit codes
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md): settings file, folders on each OS, notifications, environment variables
- [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md): how downloads are found, checked and resumed; notes on each site; adding a site
- [LEGAL.md](LEGAL.md): legal notice, terms of use, disclaimer
- [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md)

## License

GNU General Public License v3.0 or later (GPL-3.0-or-later). See [LICENSE](LICENSE). You may use, study,
share and modify journal-dl; if you distribute it or a modified version, you must do so under the same licence
and make the source available. Use is subject to the [Legal Notice and Terms of Use](LEGAL.md): no warranty,
no liability, and you alone are responsible for lawful use. Not affiliated with Wiley, Taylor & Francis,
Wolters Kluwer (Ovid) or any library.
