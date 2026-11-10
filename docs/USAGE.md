# Usage

> Use only within your institution's licence terms, each site's terms of use and the law; you alone are
> responsible for your use. See [LEGAL.md](../LEGAL.md). Nothing here is legal advice.

```
journal-dl [options] ["Journal name"] [years]
wiley-dl | tandf-dl | ovid-dl  [same options]
```

`journal-dl` works with all three sites. `wiley-dl`, `tandf-dl` and `ovid-dl` each use one site, with exactly
the same options. The only extra options `journal-dl` has are `--site` and `--alternate`.

## Choosing what to download

| | |
|---|---|
| `"Journal name"` | the exact title, or enough words to match only one journal (`"personnel psych"`) |
| `2026` / `2018-2021` | years |
| `2026-11` | the issue(s) of one month (Wiley and Ovid; Taylor & Francis has no months) |
| `--issue "79(2)"` | one issue by volume(issue), or by its date: `"Spring 2026"`, `"November 2026"` |
| `-p`, `--pick` | choose issues from a numbered list (`3`, `1,4`, `2-5`, Enter = all) |
| `--new` | only issues newer than the newest issue you already have (only the latest issue if you have none) |
| no years | the whole journal: shows the plan and asks first (`-y` skips the question) |
| `--max N` | stop after N PDFs |
| `--dry-run` | read the issue lists and contents, show the plan and time estimate, download nothing |
| `-o FOLDER` | use another archive folder for this run |
| `--open` | open the journal's folder when done; on its own, open the archive folder |
| `--site wiley\|tandf\|ovid` | (`journal-dl` only) skip the lookup and use only this site |
| `--alternate` | (`journal-dl` only) look on every site again; if the journal is on several, alternate between them |

**Finding the journal (journal-dl).** The first time, journal-dl looks for the journal on Wiley, then
Taylor & Francis, then Ovid. An exact title beats a near one. If more than one site has the journal, it asks
which to use: one site, or `A` (the default, and what `-y` and background runs get) to alternate between all
of them. The answer is remembered, so the next run goes straight there. Use `--site` to pin one site, or
`--alternate` to look again for a journal that was remembered on a single site.

**Alternating between sites.** Each selected issue is downloaded from one site, chosen at random among the
sites that list it, which spreads the requests over several sites. Issues are matched by volume and issue
number. The publisher's own site names the folders, so the archive looks the same whichever site an issue
came from. An issue that was started on one site is finished there, and an issue that is complete on any
site is skipped. Each site keeps its own pacing and its own hourly/daily PDF count, so a
`50/day` limit allows up to 50 PDFs from each site; `--max` counts all sites together. `--resume`, `--follow` and `--update` remember the alternation. The guide
(`--easy`) offers it when the journal you choose is on other sites too.

**Before downloading**, each run reads the contents of the selected issues (up to 15 issues; for more it
estimates from the ones it has read). It then shows the number of PDFs and how long they will take at your
speed setting, counting delays, breaks, hourly and daily limits and allowed hours, and asks `Start? [Y/n]`.
`-y` skips the question; runs without a terminal (scheduled or in the background) don't ask.

## While it runs

- A progress line shows `[done/total]`, the issue, the countdown to the next download and the time left.
- **Ctrl+C** stops at once. Finished PDFs are kept, and a half-downloaded file is never left as a `.pdf`.
- If your sign-in runs out, it waits up to 30 minutes for you to sign in again in the browser window (you get
  a notification).
- If a site shows a "verify you are human" check, the run stops. Complete the check in the browser window,
  then run the same command again.
- If the browser window is closed, the run stops cleanly. Run it again and the window reopens.
- If the archive drive drops below 5 GB free, the run pauses.

## Afterwards

| | |
|---|---|
| `--status` | PDFs per journal and issue (failed, to do, no access) and any unfinished run |
| `--resume` | continue the last unfinished run (same journal and issues, including ones picked with `-p`) |
| `--retry` | failed articles are tried again on the next run (with a journal: right away) |
| `--verify` | re-check that every saved PDF is still there and unchanged |

Running a command with no options in a terminal also offers to continue an unfinished run.

## Convenience

| | |
|---|---|
| `--easy` | the guide: search, choose the journal and years, speed, follow, pick issues. Remembers your answers |
| `--background` | start the same download detached from the terminal; `--log` shows its progress |
| `--follow` / `--unfollow` / `--following` | keep a list of journals |
| `--update` | download new issues (`--new`) of every followed journal; in `wiley-dl` etc. only that site's journals |
| `--schedule weekly\|daily\|off` | run `--update` automatically: systemd user timer (Linux), launchd (macOS), Task Scheduler (Windows) |
| `--install-launcher` | a "Journal Downloader" icon on the desktop that opens the guide |
| `--no-notify` | no notification for this run |

Scheduled and background runs can't sign in for you. If the library session has expired, you get a
notification and the run waits 30 minutes for you to sign in.

## Setup and checks

| | |
|---|---|
| `--setup` | archive folder, library proxy, sign-in hosts, institution name, Ovid library route, browser. With no proxy set, it offers to find the proxy and sign-in page itself: you open one article through your library in the browser window, and it reads them from the addresses |
| `--doctor` | Python and packages, settings, archive folder (writable, free space), browser, sign-in on each site, speed, followed journals, unfinished run |
| `--browser` | open the downloader's browser window, e.g. to sign in before a scheduled run (the first time, it runs `--setup` first) |
| `--install-browser` | download a private Chromium (only needed when no Chrome, Chromium or Edge is installed) |

## Library access

| | |
|---|---|
| `--direct` | don't use the library proxy this run (on campus or VPN) |
| `--via-proxy` | always use the library proxy this run |

Without either, the `access` setting decides (default `auto`: direct when the publisher already recognises your
institution at the start of the run, else the proxy). See [CONFIGURATION.md](CONFIGURATION.md).

## Speed options

| | |
|---|---|
| `--speed fast\|normal\|careful\|slow\|superslow` | preset (see README) |
| `--delay T` | time between downloads: `10`, `5-15`, `30s-2m` |
| `--delay-mode uniform\|normal\|exponential` | how delays spread within the range |
| `--jitter 20%` | extra random ± on every delay |
| `--page-delay T` | time between page loads |
| `--break-every N` / `--break-for T` | a break every N downloads (ranges allowed) |
| `--max-per-hour N` / `--max-per-day N` | PDFs per site in the last 60 min / 24 h, counted across runs and journals (see below) |
| `--hours 22:00-07:00` | only download in this daily window (`any` = always) |
| `--backoff X` / `--backoff-max T` | how much to slow down when a site throttles |
| `--save-speed` / `--show-speed` | remember the settings as the default / show them |

**What the limits count.** The hourly and daily limits count PDFs downloaded from one site in the last
60 minutes / 24 hours (rolling, not per calendar day), across all runs and all journals on that site.
PDFs copied from another site's download, or found already in the folder, don't count. Each site has its
own count: when a journal alternates between two sites, `50/day` allows up to 50 from each, 100 in all.
To limit a single run instead, use `--max N`, which counts every site together.

A 2-second minimum between downloads always applies. After 4 throttling responses in a row, the run stops.

## Exit codes

`0` done · `1` journal not found or a check failed · `2` stopped (sign-in, bot check, throttling, disk,
browser closed) · `3` a page was not as expected (site layout changed) · `130` Ctrl+C
