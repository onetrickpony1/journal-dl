# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Operating-system helpers: open a folder, show a path the way the user knows it, a desktop
launcher, a scheduled --update, and runs in the background. Linux, macOS and Windows."""
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from . import paths, settings

TASK = "journal-dl-update"


# ---------------------------------------------------------------- folders
def open_folder(path: Path):
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        if os.name == "nt":
            os.startfile(str(path))                                    # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"(could not open the folder: {e})")
        return False


def show_path(path: Path) -> str:
    """The path, plus how it looks on another computer when settings has "path_aliases",
    e.g. [["/mnt/share/H", "H:"]] -> '/mnt/share/H/X  (H:\\X)'."""
    s = str(path)
    for prefix, alias in settings.S.get("path_aliases") or []:
        if s.startswith(prefix):
            rest = s[len(prefix):].lstrip("/\\")
            win = alias.endswith(":") or "\\" in alias
            other = (alias.rstrip("\\/") + ("\\" if win else "/") + (rest.replace("/", "\\") if win else rest))
            return f"{s}  ({other})"
    return s


# ---------------------------------------------------------------- how to run ourselves
def self_command(prog: str = "journal-dl") -> list:
    """argv that starts this tool again (works without the launcher being on PATH)."""
    mod = {"journal-dl": "journal_dl", "ovid-dl": "journal_dl.ovid_dl", "wiley-dl": "journal_dl.wiley_dl",
           "tandf-dl": "journal_dl.tandf_dl"}.get(prog, "journal_dl")
    return [sys.executable, "-m", mod]


def _detach_kw():
    if os.name == "nt":
        return {"creationflags": 0x00000008 | 0x00000200 | 0x08000000}   # detached, new group, no window
    return {"start_new_session": True}


# ---------------------------------------------------------------- background runs
def run_in_background(prog: str, argv: list) -> Path:
    logs = paths.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{time.strftime('%Y-%m-%d_%H%M%S')}-{prog}.log"
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", JOURNAL_DL_BACKGROUND="1")
    with open(log, "w", encoding="utf-8") as f:
        f.write(f"$ {prog} {' '.join(shlex.quote(a) for a in argv)}\n")
        f.flush()
        subprocess.Popen(self_command(prog) + argv, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         env=env, **_detach_kw())
    return log


def latest_log():
    logs = sorted(paths.logs_dir().glob("*.log"), key=lambda p: p.stat().st_mtime) if paths.logs_dir().is_dir() else []
    return logs[-1] if logs else None


def show_log(lines=40):
    log = latest_log()
    if not log:
        print("No background runs yet.")
        return
    text = log.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"{log}  (last {min(lines, len(text))} lines)\n")
    print("\n".join(text[-lines:]))


# ---------------------------------------------------------------- desktop launcher
def desktop_dir() -> Path:
    if sys.platform.startswith("linux"):
        try:
            d = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5).stdout.strip()
            if d and Path(d).is_dir():
                return Path(d)
        except Exception:
            pass
    if os.name == "nt":
        one = Path(os.environ.get("OneDrive", "")) / "Desktop"
        if os.environ.get("OneDrive") and one.is_dir():
            return one
    return Path.home() / "Desktop"


def launcher_files() -> dict:
    """{path: (content, executable)} for this OS."""
    cmd = self_command("journal-dl")
    out = {}
    if os.name == "nt":
        body = f'@echo off\r\ntitle Journal Downloader\r\n"{cmd[0]}" -m journal_dl --easy\r\npause\r\n'
        out[desktop_dir() / "Journal Downloader.bat"] = (body, False)
    elif sys.platform == "darwin":
        body = f"#!/bin/bash\nexec {shlex.quote(cmd[0])} -m journal_dl --easy\n"
        out[desktop_dir() / "Journal Downloader.command"] = (body, True)
    else:
        line = " ".join(shlex.quote(c) for c in cmd) + " --easy"
        body = ("[Desktop Entry]\nType=Application\nName=Journal Downloader\n"
                "Comment=Download journal article PDFs (guided)\n"
                f"Exec=sh -c '{line}; echo; read -p \"Press Enter to close\" x'\n"
                "Terminal=true\nIcon=document-save\nCategories=Office;Education;\n")
        apps = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "applications"
        out[apps / "journal-dl.desktop"] = (body, True)
        if desktop_dir().is_dir():
            out[desktop_dir() / "journal-dl.desktop"] = (body, True)
    return out


def install_launcher():
    for path, (body, exe) in launcher_files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="")
        if exe:
            path.chmod(0o755)
        if path.suffix == ".desktop" and "Desktop" in str(path.parent):
            subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"created {path}")
    print("Double-click 'Journal Downloader' to start the guide.")


# ---------------------------------------------------------------- scheduled --update
def schedule_files(every: str) -> dict:
    """{path: content} for systemd (Linux) or launchd (macOS); Windows uses schtasks instead."""
    cmd = self_command("journal-dl") + ["--update"]
    if sys.platform == "darwin":
        args = "".join(f"<string>{c}</string>" for c in cmd)
        when = ("<key>StartCalendarInterval</key><dict><key>Weekday</key><integer>1</integer>"
                "<key>Hour</key><integer>9</integer></dict>") if every == "weekly" else \
            "<key>StartCalendarInterval</key><dict><key>Hour</key><integer>9</integer></dict>"
        log = paths.logs_dir() / "scheduled.log"
        plist = (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                 f'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
                 f"<key>Label</key><string>org.journal-dl.update</string>"
                 f"<key>ProgramArguments</key><array>{args}</array>{when}"
                 f"<key>StandardOutPath</key><string>{log}</string><key>StandardErrorPath</key><string>{log}</string>"
                 f"</dict></plist>\n")
        return {Path.home() / "Library/LaunchAgents/org.journal-dl.update.plist": plist}
    unit = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd/user"
    service = ("[Unit]\nDescription=journal-dl: download new issues of followed journals\n\n"
               "[Service]\nType=oneshot\nEnvironment=PYTHONUNBUFFERED=1\n"
               f"ExecStart={' '.join(shlex.quote(c) for c in cmd)}\n")
    timer = ("[Unit]\nDescription=journal-dl update schedule\n\n[Timer]\n"
             f"OnCalendar={'Mon *-*-* 09:00:00' if every == 'weekly' else '*-*-* 09:00:00'}\n"
             "Persistent=true\nRandomizedDelaySec=30m\n\n[Install]\nWantedBy=timers.target\n")
    return {unit / f"{TASK}.service": service, unit / f"{TASK}.timer": timer}


def schedule(every: str):
    """every: 'weekly', 'daily' or 'off'."""
    if os.name == "nt":
        if every == "off":
            r = subprocess.run(["schtasks", "/Delete", "/TN", TASK, "/F"], capture_output=True, text=True)
        else:
            cmd = self_command("journal-dl") + ["--update"]
            tr = " ".join(f'"{c}"' if " " in c else c for c in cmd)
            sc = ["/SC", "WEEKLY", "/D", "MON"] if every == "weekly" else ["/SC", "DAILY"]
            r = subprocess.run(["schtasks", "/Create", "/TN", TASK, "/TR", tr, *sc, "/ST", "09:00", "/F"],
                               capture_output=True, text=True)
        print((r.stdout or r.stderr).strip())
        return r.returncode == 0
    files = schedule_files(every if every != "off" else "weekly")
    if sys.platform == "darwin":
        plist = next(iter(files))
        subprocess.run(["launchctl", "unload", str(plist)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if every == "off":
            plist.unlink(missing_ok=True)
            print("Schedule removed.")
            return True
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(files[plist], encoding="utf-8")
        r = subprocess.run(["launchctl", "load", str(plist)], capture_output=True, text=True)
        print(f"Scheduled {every} (Mondays 09:00 for weekly, 09:00 for daily): {plist}")
        return r.returncode == 0
    from shutil import which
    if not which("systemctl"):
        line = " ".join(shlex.quote(c) for c in self_command("journal-dl")) + " --update"
        print("No systemd here. Add this line with `crontab -e` instead:\n"
              f"  0 9 * * {'1' if every == 'weekly' else '*'} {line}")
        return False
    if every == "off":
        subprocess.run(["systemctl", "--user", "disable", "--now", f"{TASK}.timer"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for p in files:
            p.unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"])
        print("Schedule removed.")
        return True
    for p, body in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    r = subprocess.run(["systemctl", "--user", "enable", "--now", f"{TASK}.timer"], capture_output=True, text=True)
    print(f"Scheduled {every}: " + ("Mondays around 09:00" if every == "weekly" else "every day around 09:00")
          + f" (systemd timer {TASK}.timer). Missed runs happen at the next start-up.")
    return r.returncode == 0


def schedule_status() -> str:
    try:
        if os.name == "nt":
            r = subprocess.run(["schtasks", "/Query", "/TN", TASK], capture_output=True, text=True, timeout=10)
            return "on (Windows Task Scheduler)" if r.returncode == 0 else "off"
        files = schedule_files("weekly")
        return "on" if any(p.exists() for p in files) else "off"
    except Exception:
        return "unknown"
