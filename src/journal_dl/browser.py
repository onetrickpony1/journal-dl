# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""The downloader's own browser window: a dedicated Chrome profile with a local control port.

The user signs in there by hand (the tools never see passwords). Every command connects to the
same window over the Chrome DevTools Protocol on 127.0.0.1, so a sign-in is shared by all sites.
Works with Google Chrome, Chromium or Microsoft Edge on Linux, macOS and Windows, including the
Flatpak builds on Linux.
"""
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from . import paths, settings

DEFAULT_PROFILE = Path(os.environ.get("JOURNAL_DL_PROFILE") or os.environ.get("OVID_ARCHIVE_PROFILE")
                       or paths.data_dir() / "profile")


def cdp_url() -> str:
    return os.environ.get("JOURNAL_DL_CDP") or os.environ.get("OVID_ARCHIVE_CDP") or \
        f"http://127.0.0.1:{settings.S.get('cdp_port', 9333)}"


# Flatpak builds of the supported browsers (Linux). They are not on PATH under their usual names, only as
# their app id in .../flatpak/exports/bin, and they run sandboxed (see launch_args).
FLATPAK_IDS = ("com.google.Chrome", "org.chromium.Chromium", "com.microsoft.Edge")
FLATPAK_EXPORTS = (Path.home() / ".local/share/flatpak/exports/bin", Path("/var/lib/flatpak/exports/bin"))


def flatpak_id(exe):
    """The Flatpak app id when `exe` is a Flatpak browser launcher, else None."""
    if not exe:
        return None
    name = os.path.basename(str(exe))
    return name if name in FLATPAK_IDS or "/flatpak/exports/bin/" in str(exe) else None


def _resolve(value):
    """A browser given in settings as a path, a command name, an app id or 'flatpak run <id>' -> a path, or None."""
    if not value:
        return None
    value = os.path.expanduser(str(value).strip())
    if os.path.isfile(value):
        return value
    words = shlex.split(value)
    if words and os.path.basename(words[0]) == "flatpak":
        words = [w for w in words[1:] if w != "run" and not w.startswith("-")]
    if len(words) == 1:
        w = words[0]
        if w in FLATPAK_IDS or ("." in w and os.sep not in w):
            for d in FLATPAK_EXPORTS:
                if (d / w).is_file():
                    return str(d / w)
        return shutil.which(w)
    return None


def candidates() -> list:
    """Likely browser locations for this OS, best first."""
    out = []
    if settings.S.get("chrome"):
        out.append(_resolve(settings.S["chrome"]) or settings.S["chrome"])
    if sys.platform == "win32":
        roots = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for r in filter(None, roots):
            out += [os.path.join(r, "Google", "Chrome", "Application", "chrome.exe"),
                    os.path.join(r, "Chromium", "Application", "chrome.exe"),
                    os.path.join(r, "Microsoft", "Edge", "Application", "msedge.exe")]
    elif sys.platform == "darwin":
        for app in ("Google Chrome", "Chromium", "Microsoft Edge"):
            exe = "Google Chrome" if app == "Google Chrome" else app
            out += [f"/Applications/{app}.app/Contents/MacOS/{exe}",
                    str(Path.home() / f"Applications/{app}.app/Contents/MacOS/{exe}")]
    else:
        for name in ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser",
                     "microsoft-edge-stable", "microsoft-edge"):
            w = shutil.which(name)
            if w:
                out.append(w)
        if shutil.which("flatpak"):
            for app in FLATPAK_IDS:
                out += [str(d / app) for d in FLATPAK_EXPORTS]
    return out


def find_chrome(p=None):
    """The browser to use. Pass the running Playwright `p` when there is one (see bundled_chromium)."""
    for c in candidates():
        if c and os.path.isfile(c):
            return c
    return bundled_chromium(p)


def launch_args(exe, profile: Path) -> list:
    """The command that starts `exe` with `profile`. A Flatpak browser can't see ~/.local/share, so without
    --filesystem it silently keeps the profile inside its sandbox and every sign-in is lost on restart."""
    app = flatpak_id(exe)
    if app:
        return ["flatpak", "run", f"--filesystem={profile}", app]
    return [exe]


def bundled_chromium(p=None):
    """The private Chromium installed by `journal-dl --install-browser` (Playwright's build), if any.

    Inside a `with sync_playwright() as p:` block, pass that `p`: Playwright's sync API can't be started a
    second time there ("using Playwright Sync API inside the asyncio loop"), so a fresh sync_playwright()
    would fail and the private Chromium would look missing whenever the window has to be started mid-run."""
    try:
        if p is not None:
            path = p.chromium.executable_path
        else:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                path = pw.chromium.executable_path
        return path if path and os.path.isfile(path) else None
    except Exception:
        return None


def install_browser() -> bool:
    """Download a private Chromium for journal-dl (no admin rights; about 150 MB)."""
    print("Downloading a private Chromium for journal-dl (about 150 MB)...")
    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    r = subprocess.run(cmd + ["--no-shell"])          # the full browser only (a window is needed to sign in)
    if r.returncode != 0:
        r = subprocess.run(cmd)                       # older Playwright without --no-shell
    if r.returncode != 0:
        return False
    if sys.platform.startswith("linux"):
        print("If it doesn't start, it may need some system libraries. Install Chrome or Chromium from your "
              "distribution instead, or run (needs admin):\n"
              f"  sudo {sys.executable} -m playwright install-deps chromium")
    return bundled_chromium() is not None


def alive(timeout=2) -> bool:
    try:
        urllib.request.urlopen(cdp_url() + "/json/version", timeout=timeout)
        return True
    except Exception:
        return False


def start(profile: Path = DEFAULT_PROFILE, url: str = "about:blank", wait_s: float = 20, p=None) -> bool:
    """Start the dedicated browser window if it isn't running. Returns True when reachable.
    `p`: the running Playwright, when called inside a sync_playwright() block."""
    if alive():
        return True
    exe = find_chrome(p)
    if not exe:
        raise SystemExit("Could not find Google Chrome, Chromium or Microsoft Edge. Install one, or run "
                         f'journal-dl --install-browser, or set "chrome" to its path in {settings.path()}')
    profile.mkdir(parents=True, exist_ok=True)
    port = cdp_url().rsplit(":", 1)[1]
    args = launch_args(exe, profile) + [f"--user-data-dir={profile}", f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check", url]
    kw = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(args, **kw)
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        time.sleep(0.5)
        if alive():
            return True
    return False


def connect(p):
    """Playwright BrowserContext of the running window (starting it if needed)."""
    if not alive():
        print("Starting the downloader's browser window...")
        if not start(p=p):
            raise SystemExit("The browser window did not start. Try again, or start it with: journal-dl --browser")
    return p.chromium.connect_over_cdp(cdp_url()).contexts[0]


# --- used by the low-level `ovid-archive login/probe` commands -------------------------------
@contextmanager
def session(profile: Path = DEFAULT_PROFILE, headless: bool = False):
    from playwright.sync_api import sync_playwright
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        exe = find_chrome(p)
        if flatpak_id(exe):          # Playwright launches over a pipe, which can't reach into a Flatpak sandbox
            exe = bundled_chromium(p)
        ctx = p.chromium.launch_persistent_context(str(profile), executable_path=exe, headless=headless,
                                                   accept_downloads=True, viewport=None)
        try:
            yield ctx
        finally:
            ctx.close()


def all_text(page) -> str:
    """Every word on the page, also those in menus, banners or behind a cookie notice. inner_text() only gives
    what is visible, and a consent overlay or a collapsed menu (T&F's "Access provided by ...") hides it."""
    return page.evaluate("() => document.body ? document.body.textContent : ''") or ""


def current_page(ctx):
    return ctx.pages[-1] if ctx.pages else ctx.new_page()
