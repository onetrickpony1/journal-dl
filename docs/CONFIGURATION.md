# Configuration

## Settings file

`journal-dl --setup` writes `settings.json` in the config folder. Every key is optional.

```json
{
  "output": "D:/Journals",
  "proxy": "proxy.library.example.edu",
  "login_hosts": ["login.example.edu", "login.microsoftonline.com"],
  "institution_name": "Example University",
  "library_journal_search": "https://library.example.edu/discovery/jsearch?query=any,contains,",
  "library_ovid_door": "Some Journal Your Library Has On Ovid",
  "chrome": null,
  "cdp_port": 9333,
  "notify": true,
  "ntfy_topic": "",
  "ntfy_server": "https://ntfy.sh",
  "path_aliases": [["/mnt/share/H", "H:"]]
}
```

| Key | Meaning |
|---|---|
| `output` | archive folder (default: `Documents/Journal Downloads` in your home folder) |
| `proxy` | your library's EZproxy host. Sites are opened as `https://<site-with-dashes>.<proxy>`; empty = direct (campus/VPN) |
| `access` | with a proxy set: `auto` (default) goes direct when the publisher already recognises your institution at the start of a run (campus/VPN), else through the proxy; `proxy` or `direct` = always. `--direct` / `--via-proxy` override it for one run |
| `login_hosts` | your institution's sign-in host(s); seeing one means the session has expired |
| `institution_name` | the name Wiley shows when you are signed in (empty = don't check; also needed for `access: auto` to go direct on Wiley) |
| `library_journal_search` | your catalogue's journal search URL ending where the search text goes; used to open Ovid |
| `library_ovid_door` | any journal your catalogue opens on Ovid ("Available Online"); used once to get into Ovid |
| `chrome` | path to Chrome, Chromium or Edge, if it isn't found automatically |
| `cdp_port` | local port of the downloader's browser window (127.0.0.1 only) |
| `notify` | desktop notifications on/off |
| `ntfy_topic` | optional: also send notifications to this [ntfy](https://ntfy.sh) topic (journal name and counts only) |
| `path_aliases` | optional: also print paths the way another computer sees the same folder |

Without `library_*`, open Ovid through your library yourself in the browser window the first time; journal-dl
waits for the Ovid tab to appear.

## Folders

| | Linux | macOS | Windows |
|---|---|---|---|
| settings, speed, state | `~/.config/journal-dl` | `~/Library/Application Support/journal-dl` | `%APPDATA%\journal-dl` |
| databases, browser profile, logs | `~/.local/share/journal-dl` | `~/Library/Application Support/journal-dl` | `%LOCALAPPDATA%\journal-dl` |

The config folder holds `settings.json`, `pacing.json` (saved speed) and `state.json` (last run, followed
journals, which site each journal is on, the guide's last answers).
The data folder holds one SQLite database per site (`wiley.sqlite`, `tandf.sqlite`, `ovid.sqlite`), `profile/`
(the browser profile with your sign-in; keep it private) and `logs/` (background runs).

Databases are always kept on the local disk. SQLite can't lock files reliably on network shares, so a backup
copy goes into each journal's `.journal-dl/` folder instead.

## Environment variables

| | |
|---|---|
| `JOURNAL_DL_CONFIG`, `JOURNAL_DL_DATA` | use other config / data folders |
| `JOURNAL_DL_OUTPUT` | archive folder for this shell |
| `JOURNAL_DL_PROFILE` | browser profile folder |
| `JOURNAL_DL_CDP` | browser control address (default `http://127.0.0.1:9333`) |
| `WILEY_DL_BASE`, `TANDF_DL_BASE` | full base URL of the site, overriding the proxy setting |

## The browser window

journal-dl starts your Chrome with its **own profile** and a control port bound to 127.0.0.1, so it never
touches your normal browser profile, and nothing outside your computer can reach the port. Sign in there once;
the session is reused by every command. Recent Chrome versions only allow the control port with a separate
profile, which is why journal-dl uses its own.
