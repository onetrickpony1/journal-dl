# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Request pacing / rate limiting for ovid-dl.

Everything that decides *when* the next request may happen lives here:
  - delay between article downloads: fixed, range, jitter; uniform / normal / exponential spread
  - delay between page loads (issue lists, results pages), separate and usually shorter
  - breaks: a longer pause every N downloads (N and the pause may both be ranges)
  - caps: max downloads per hour and per day (rolling windows, counted across runs)
  - active hours: only download inside a daily time window (may wrap midnight)
  - adaptive slow-down: throttling/errors multiply the delay (honouring Retry-After),
    successes bring it back gradually (AIMD)
Settings are a plain dataclass, parsed from short strings like "5-15", "2m-5m", "22:00-07:00",
saved as the user's default in ~/.config/ovid-dl/pacing.json.
"""
import json
import math
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta

from . import paths

CONFIG = paths.config_dir() / "pacing.json"
FLOOR_S = 2.0            # never start downloads closer together than this
MODES = ("uniform", "normal", "exponential")


# ---------------------------------------------------------------- parsing
def parse_duration(s) -> float:
    """'90' / '90s' / '2m' / '1.5h' / '1h30m' -> seconds."""
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip().lower().replace(" ", "")
    if not t:
        raise ValueError("empty duration")
    if re.fullmatch(r"\d+(\.\d+)?", t):
        return float(t)
    total, pos = 0.0, 0
    for m in re.finditer(r"(\d+(?:\.\d+)?)(h|m|s)", t):
        if m.start() != pos:
            raise ValueError(f"bad duration {s!r}")
        total += float(m.group(1)) * {"h": 3600, "m": 60, "s": 1}[m.group(2)]
        pos = m.end()
    if pos != len(t):
        raise ValueError(f"bad duration {s!r} (use e.g. 30, 45s, 2m, 1h30m)")
    return total


def parse_range(s, kind=parse_duration) -> tuple:
    """'10' -> (10,10); '5-15' / '5..15' / '2m-5m' -> (lo,hi)."""
    t = str(s).strip()
    parts = re.split(r"\s*(?:\.\.|-|–|to)\s*", t, maxsplit=1) if not t.startswith("-") else [t]
    if len(parts) == 2 and parts[0] and parts[1]:
        lo, hi = kind(parts[0]), kind(parts[1])
    else:
        lo = hi = kind(t)
    if lo < 0 or hi < 0:
        raise ValueError(f"negative value in {s!r}")
    return (min(lo, hi), max(lo, hi))


def parse_int_range(s) -> tuple:
    return parse_range(s, kind=lambda x: float(int(x)))


def parse_hours(s):
    """'22:00-07:00' / '9-17' -> (minute_of_day_start, minute_of_day_end)."""
    def mins(x):
        m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", x.strip())
        if not m or int(m.group(1)) > 24 or int(m.group(2) or 0) > 59:
            raise ValueError(f"bad time {x!r} (use HH:MM)")
        return (int(m.group(1)) * 60 + int(m.group(2) or 0)) % 1440
    a, _, b = str(s).partition("-")
    if not b:
        raise ValueError("hours must look like 22:00-07:00")
    return (mins(a), mins(b))


def fmt(sec: float) -> str:
    sec = max(0, int(round(sec)))
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m{sec % 60:02d}s"
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"


def fmt_range(r, f=fmt):
    return f(r[0]) if r[0] == r[1] else f"{f(r[0])}-{f(r[1])}"


# ---------------------------------------------------------------- settings
@dataclass
class Pacing:
    delay: tuple = (5.0, 12.0)          # seconds between article download starts
    mode: str = "uniform"               # how values inside the range are spread
    jitter: float = 0.0                 # extra +-fraction applied to every delay (0.2 = +-20%)
    page_delay: tuple = (2.0, 4.0)      # between page loads
    break_every: tuple = (25.0, 40.0)   # downloads between breaks (0 = no breaks)
    break_for: tuple = (60.0, 180.0)    # length of a break
    max_per_hour: int = 0               # 0 = no cap
    max_per_day: int = 0
    hours: tuple | None = None          # (start_min, end_min) of day, or None = any time
    backoff: float = 2.0                # multiply delay by this on throttling/errors
    backoff_max: float = 900.0          # ...up to this many seconds
    recover_after: int = 5              # successes needed to halve the slow-down
    preset: str = "normal"

    def validate(self):
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        if not 0 <= self.jitter <= 1:
            raise ValueError("jitter must be between 0% and 100%")
        if self.backoff < 1:
            raise ValueError("backoff factor must be >= 1")
        if self.delay[1] < FLOOR_S:
            raise ValueError(f"delay must allow at least {FLOOR_S:g}s between downloads")
        if self.max_per_hour < 0 or self.max_per_day < 0:
            raise ValueError("caps cannot be negative")
        return self

    def describe(self) -> str:
        parts = [f"{fmt_range(self.delay)} between downloads ({self.mode}"
                 + (f", jitter +-{self.jitter:.0%}" if self.jitter else "") + ")",
                 f"{fmt_range(self.page_delay)} between pages"]
        if self.break_every[1] > 0:
            parts.append(f"break {fmt_range(self.break_for)} every "
                         f"{fmt_range(self.break_every, lambda x: str(int(x)))} downloads")
        if self.max_per_hour:
            parts.append(f"max {self.max_per_hour}/hour")
        if self.max_per_day:
            parts.append(f"max {self.max_per_day}/day")
        if self.hours:
            h = lambda m: f"{m // 60:02d}:{m % 60:02d}"
            parts.append(f"only {h(self.hours[0])}-{h(self.hours[1])}")
        parts.append(f"slow-down x{self.backoff:g} on throttling (max {fmt(self.backoff_max)})")
        return f"[{self.preset}] " + "; ".join(parts)

    def to_json(self):
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        d = {k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items() if k in names}
        return cls(**d).validate()


PRESETS = {
    "fast":    dict(delay=(3, 6),   page_delay=(1, 2),  break_every=(0, 0),   break_for=(0, 0)),
    "normal":  dict(delay=(5, 12),  page_delay=(2, 4),  break_every=(25, 40), break_for=(60, 180)),
    "careful": dict(delay=(10, 25), page_delay=(3, 6),  break_every=(15, 30), break_for=(180, 480),
                    max_per_hour=120),
    "slow":    dict(delay=(30, 90), page_delay=(5, 10), break_every=(10, 20), break_for=(300, 900),
                    max_per_hour=40, max_per_day=300),
}
PRESET_HELP = {
    "fast": "3-6s between PDFs, no breaks",
    "normal": "5-12s between PDFs, 1-3 min break every 25-40 PDFs",
    "careful": "10-25s, 3-8 min break every 15-30, max 120/hour",
    "slow": "30-90s, 5-15 min break every 10-20, max 40/hour and 300/day",
}


def preset(name: str) -> Pacing:
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose {', '.join(PRESETS)}")
    p = Pacing(**{k: tuple(map(float, v)) if isinstance(v, tuple) else v for k, v in PRESETS[name].items()})
    p.preset = name
    return p.validate()


def load_default() -> Pacing:
    try:
        return Pacing.from_dict(json.loads(CONFIG.read_text()))
    except FileNotFoundError:
        return preset("normal")
    except Exception as e:
        print(f"(ignoring unreadable pacing settings in {CONFIG}: {e})", file=sys.stderr)
        return preset("normal")


def save_default(p: Pacing):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".part")
    tmp.write_text(p.to_json())
    os.replace(tmp, CONFIG)


def from_args(a, base: Pacing | None = None) -> Pacing:
    """Apply command-line options on top of a preset or the saved default."""
    p = preset(a.speed) if getattr(a, "speed", None) else (base or load_default())
    changed = False
    if getattr(a, "delay", None):
        p.delay = parse_range(a.delay); changed = True
    if getattr(a, "delay_mode", None):
        p.mode = a.delay_mode; changed = True
    if getattr(a, "jitter", None) is not None:
        p.jitter = float(str(a.jitter).rstrip("%")) / 100; changed = True
    if getattr(a, "page_delay", None):
        p.page_delay = parse_range(a.page_delay); changed = True
    if getattr(a, "break_every", None):
        p.break_every = parse_int_range(a.break_every); changed = True
    if getattr(a, "break_for", None):
        p.break_for = parse_range(a.break_for); changed = True
    if getattr(a, "max_per_hour", None) is not None:
        p.max_per_hour = int(a.max_per_hour); changed = True
    if getattr(a, "max_per_day", None) is not None:
        p.max_per_day = int(a.max_per_day); changed = True
    if getattr(a, "hours", None):
        p.hours = None if a.hours in ("any", "all") else parse_hours(a.hours); changed = True
    if getattr(a, "backoff", None):
        p.backoff = float(a.backoff); changed = True
    if getattr(a, "backoff_max", None):
        p.backoff_max = parse_duration(a.backoff_max); changed = True
    if changed:
        p.preset = "custom"
    return p.validate()


def add_arguments(ap):
    g = ap.add_argument_group("speed / pacing (default: your saved setting, else 'normal')")
    g.add_argument("--speed", choices=list(PRESETS), help="preset: " + "; ".join(f"{k} = {v}" for k, v in PRESET_HELP.items()))
    g.add_argument("--delay", metavar="T", help="between downloads: 10, 5-15, 30s-2m")
    g.add_argument("--delay-mode", choices=MODES, help="spread inside the range (default uniform)")
    g.add_argument("--jitter", metavar="PCT", help="extra random +- percent on every delay, e.g. 20%%")
    g.add_argument("--page-delay", metavar="T", help="between page loads, e.g. 2-4")
    g.add_argument("--break-every", metavar="N", help="downloads between breaks, e.g. 20-40 (0 = never)")
    g.add_argument("--break-for", metavar="T", help="break length, e.g. 2m-5m")
    g.add_argument("--max-per-hour", type=int, metavar="N", help="cap per rolling hour (0 = none)")
    g.add_argument("--max-per-day", type=int, metavar="N", help="cap per rolling 24 h (0 = none)")
    g.add_argument("--hours", metavar="HH:MM-HH:MM", help="only download in this daily window, e.g. 22:00-07:00 ('any' = off)")
    g.add_argument("--backoff", type=float, metavar="X", help="slow-down factor on throttling (default 2)")
    g.add_argument("--backoff-max", metavar="T", help="largest slow-down delay (default 15m)")
    g.add_argument("--save-speed", action="store_true", help="remember these pacing settings as the default")
    g.add_argument("--show-speed", action="store_true", help="print the pacing settings and exit")


# ---------------------------------------------------------------- runtime
@dataclass
class Pacer:
    p: Pacing
    times_since: object = None          # f(epoch) -> sorted download times since then (from the DB, all runs)
    log: object = print
    rng: random.Random = field(default_factory=random.Random)
    clock: object = time.time
    mono: object = time.monotonic
    sleep: object = None
    slow: float = 1.0                   # current adaptive multiplier
    successes: int = 0
    since_break: int = 0
    next_break_at: int = 0
    last_start: float | None = None
    last_page: float | None = None
    retry_after_until: float = 0.0
    status: object = None               # f(seconds_left) -> one-line progress text for the countdown

    def __post_init__(self):
        if self.sleep is None:
            self.sleep = lambda sec: _sleep_interruptible(sec, self._status_text)
        self._plan_break()

    def _status_text(self, left):
        base = f"next in {fmt(left)}"
        if self.status:
            try:
                return self.status(left) or base
            except Exception:
                return base
        return base

    # --- sampling
    def sample(self, r: tuple) -> float:
        lo, hi = r
        if hi <= lo:
            v = lo
        elif self.p.mode == "uniform":
            v = self.rng.uniform(lo, hi)
        elif self.p.mode == "normal":
            mu, sd = (lo + hi) / 2, (hi - lo) / 4      # ~95% inside the range
            v = min(hi, max(lo, self.rng.gauss(mu, sd)))
        else:  # exponential: mostly near the minimum, sometimes long; capped at 3x the range top
            mean = (hi - lo) / 2 or 1
            v = min(lo + self.rng.expovariate(1 / mean), hi * 3)
        if self.p.jitter:
            v *= 1 + self.rng.uniform(-self.p.jitter, self.p.jitter)
        return max(0.0, v)

    def _plan_break(self):
        lo, hi = self.p.break_every
        self.next_break_at = int(round(self.rng.uniform(lo, hi))) if hi > 0 else 0
        self.since_break = 0

    # --- waits
    def _wait(self, seconds, why):
        if seconds <= 0:
            return
        if seconds >= 20 and why:
            self.log(f"   ... {why}: waiting {fmt(seconds)}")
        self.sleep(seconds)

    def wait_page(self):
        d = self.sample(self.p.page_delay) * self.slow
        if self.last_page is not None:
            d -= self.mono() - self.last_page
        self._wait(d, None)
        self.last_page = self.mono()

    def wait_download(self):
        """Block until the next article download may start."""
        while True:
            w, why = self._hours_wait()
            if w > 0:
                self._wait(w, why)
                continue
            w, why = self._cap_wait()
            if w > 0:
                self._wait(w, why)
                continue
            break
        if self.next_break_at and self.since_break >= self.next_break_at:
            self._wait(self.sample(self.p.break_for), f"break after {self.since_break} downloads")
            self._plan_break()
        ra = self.retry_after_until - self.clock()
        if ra > 0:
            self._wait(ra, "server asked to retry later")
        d = max(FLOOR_S, self.sample(self.p.delay)) * self.slow
        d = min(d, max(self.p.backoff_max, self.p.delay[1]))
        if self.last_start is not None:
            d -= self.mono() - self.last_start
        self._wait(d, "slowed down after throttling" if self.slow > 1 else None)
        self.last_start = self.mono()
        self.last_page = self.mono()

    def _hours_wait(self):
        if not self.p.hours:
            return 0, None
        start, end = self.p.hours
        now = datetime.fromtimestamp(self.clock())
        m = now.hour * 60 + now.minute
        inside = (start <= m < end) if start < end else (m >= start or m < end)
        if start == end or inside:
            return 0, None
        target = now.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds(), f"outside download hours, resuming at {target:%H:%M}"

    def _cap_wait(self):
        if not self.times_since:
            return 0, None
        now = self.clock()
        worst = (0, None)
        for cap, window, name in ((self.p.max_per_hour, 3600, "hourly"), (self.p.max_per_day, 86400, "daily")):
            if not cap:
                continue
            times = sorted(self.times_since(now - window))
            if len(times) >= cap:
                # the window frees a slot when its (len-cap)-th oldest download ages out
                w = times[len(times) - cap] + window - now + 1
                if w > worst[0]:
                    worst = (w, f"{name} limit of {cap} downloads reached")
        return worst

    # --- feedback
    def on_success(self):
        self.since_break += 1
        self.successes += 1
        if self.slow > 1 and self.successes >= self.p.recover_after:
            self.slow = max(1.0, self.slow / 2)
            self.successes = 0
            if self.slow == 1:
                self.log("   (back to normal speed)")

    def on_throttle(self, retry_after: float | None = None):
        self.successes = 0
        cap = max(1.0, self.p.backoff_max / max(self.p.delay[1], 1))
        self.slow = min(self.slow * self.p.backoff, cap)
        if retry_after:
            self.retry_after_until = max(self.retry_after_until, self.clock() + retry_after)
        self.log(f"   (throttled: slowing down x{self.slow:g})")

    def on_error(self):
        self.successes = 0
        cap = max(1.0, self.p.backoff_max / max(self.p.delay[1], 1))
        self.slow = min(self.slow * math.sqrt(self.p.backoff), cap)

    def retry_delay(self, attempt: int, base=(30, 60)) -> float:
        """Exponential retry delay with jitter, scaled by the current slow-down."""
        b = base[min(attempt, len(base) - 1)] * (2 ** max(0, attempt - len(base) + 1))
        return min(self.p.backoff_max, b * self.slow * self.rng.uniform(0.8, 1.25))


def _sleep_interruptible(seconds, status=None):
    end = time.monotonic() + seconds
    tty = sys.stdout.isatty() and seconds >= 3
    width = 0
    while True:
        left = end - time.monotonic()
        if left <= 0:
            break
        if tty:
            text = "   " + (status(left) if status else f"next in {fmt(left)}")
            width = max(width, len(text))
            print("\r" + text.ljust(width), end="", flush=True)
        time.sleep(min(1.0, left))
    if tty and width:
        print("\r" + " " * width + "\r", end="", flush=True)


# ---------------------------------------------------------------- estimates
def mean(r):
    return (r[0] + r[1]) / 2


def estimate(p: Pacing, items: int, pages: int = 0, item_s: float = 4.0, page_s: float = 3.0,
             done_recently: int = 0) -> tuple:
    """(low, typical, high) seconds to download `items` PDFs and load `pages` pages with these settings.
    item_s/page_s are the time a download / page load itself takes (counts inside the delay when shorter).
    Accounts for delay spread, breaks, hourly/daily caps and the daily time window."""
    if items <= 0 and pages <= 0:
        return (0.0, 0.0, 0.0)

    def per_item(d):
        return max(d, FLOOR_S, item_s)

    if p.mode == "exponential":
        lo_d, mid_d, hi_d = p.delay[0], p.delay[0] + (p.delay[1] - p.delay[0]) / 2, p.delay[1] * 1.5
    else:
        lo_d, mid_d, hi_d = p.delay[0], mean(p.delay), p.delay[1]
    j = 1 + p.jitter
    out = []
    for d, pd, bf in ((lo_d / j, p.page_delay[0], p.break_for[0]),
                      (mid_d, mean(p.page_delay), mean(p.break_for)),
                      (hi_d * j, p.page_delay[1], p.break_for[1])):
        t = items * per_item(d) + pages * (pd + page_s)
        if p.break_every[1] > 0 and items:
            t += int(items / max(mean(p.break_every), 1)) * bf
        # rolling caps: items beyond the cap have to wait for the window to move on
        for cap, window in ((p.max_per_hour, 3600), (p.max_per_day, 86400)):
            if cap and items + done_recently > cap:
                t = max(t, ((items + done_recently - 1) // cap) * window + (items % cap) * per_item(d))
        if p.hours:
            start, end = p.hours
            open_min = (end - start) % 1440 or 1440
            if open_min < 1440:
                t *= 1440 / open_min          # only part of each day is usable
        out.append(t)
    return tuple(out)


def fmt_long(sec: float) -> str:
    """Friendly duration: '40 min', '3 h 15 min', '2 days 4 h'."""
    sec = max(0, int(sec))
    if sec < 90:
        return f"{sec} s"
    m = round(sec / 60)
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h} h {m:02d} min" if m else f"{h} h"
    d, h = divmod(h, 24)
    return f"{d} days {h} h"


def fmt_estimate(est) -> str:
    lo, mid, hi = est
    if hi - lo < 120:
        return f"about {fmt_long(mid)}"
    return f"about {fmt_long(mid)} ({fmt_long(lo)} to {fmt_long(hi)})"
