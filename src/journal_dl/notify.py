# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Desktop notifications (and optional phone push through ntfy) when a run ends or needs you.

Desktop: notify-send (Linux), osascript (macOS), a PowerShell balloon (Windows). Nothing is
sent anywhere else unless "ntfy_topic" is set in settings.json (then a short message goes to
that ntfy topic: journal name and counts only). Turn everything off with "notify": false or
--no-notify. Failures are silent: a notification must never break a download.
"""
import os
import shutil
import subprocess
import sys
import urllib.request

from . import settings

ENABLED = True


def send(title: str, body: str, urgent: bool = False):
    if not ENABLED or not settings.S.get("notify", True):
        return
    title, body = f"journal-dl: {title}", body[:300]
    try:
        _desktop(title, body, urgent)
    except Exception:
        pass
    topic = (settings.S.get("ntfy_topic") or "").strip()
    if topic:
        try:
            server = (settings.S.get("ntfy_server") or "https://ntfy.sh").rstrip("/")
            req = urllib.request.Request(f"{server}/{topic}", data=body.encode("utf-8"),
                                         headers={"Title": title, "Priority": "high" if urgent else "default"})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass


def _desktop(title, body, urgent):
    quiet = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    if sys.platform == "darwin":
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display notification "{esc(body)}" with title "{esc(title)}"'], **quiet)
    elif os.name == "nt":
        esc = lambda s: s.replace("'", "''")
        ps = ("Add-Type -AssemblyName System.Windows.Forms; "
              "$n = New-Object System.Windows.Forms.NotifyIcon; "
              "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
              f"$n.ShowBalloonTip(10000, '{esc(title)}', '{esc(body)}', 'Info'); Start-Sleep -Seconds 8; $n.Dispose()")
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
    elif shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "journal-dl", "-u", "critical" if urgent else "normal", title, body], **quiet)
