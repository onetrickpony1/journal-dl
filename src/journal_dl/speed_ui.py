# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Speed questions for the guide (the speed system itself is pacing.py)."""
from . import pacing


_REQUIRED = object()   # no default: Enter alone asks again


def _ask(prompt, parse, default=_REQUIRED):
    while True:
        # The current value is shown as "[5s-12s]", so accept it typed back with the brackets.
        v = input(prompt).strip().removeprefix("[").removesuffix("]").strip()
        if not v and default is not _REQUIRED:
            return default   # may be None, e.g. hours = "any"
        try:
            return parse(v)
        except (ValueError, SystemExit) as e:
            print(f"  {e}")


def ask_speed():
    cur = pacing.load_default()
    names = list(pacing.PRESETS)
    print("\nSpeed (time between downloads):")
    print(f"  0. keep saved setting  {cur.describe()}")
    for n, k in enumerate(names, 1):
        print(f"  {n}. {k:<9} {pacing.PRESET_HELP[k]}")
    print(f"  {len(names) + 1}. custom    choose every setting yourself")
    ch = _ask(f"Choose 0-{len(names) + 1} (Enter = 0): ",
              lambda v: int(v) if v.isdigit() and 0 <= int(v) <= len(names) + 1 else (_ for _ in ()).throw(ValueError("type a number from the list")), 0)
    if ch == 0:
        return cur
    if ch <= len(names):
        p = pacing.preset(names[ch - 1])
    else:
        p = custom_speed(cur)
    print("Speed:", p.describe())
    if input("Save this as your default speed? [y/N] ").strip().lower() in ("y", "yes"):
        pacing.save_default(p)
        print(f"  saved ({pacing.CONFIG})")
    return p


def custom_speed(base):
    p = pacing.Pacing(**{k: v for k, v in vars(base).items()})
    p.preset = "custom"
    R, D, I = pacing.parse_range, pacing.fmt_range, pacing.parse_int_range
    print("Press Enter to keep the value in [brackets]. Times: 10, 5-15, 45s, 2m-5m, 1h.")
    p.delay = _ask(f"  Delay between downloads [{D(p.delay)}]: ", R, p.delay)
    p.mode = _ask(f"  Randomness: uniform (even), normal (mostly middle), exponential (mostly short, some long) [{p.mode}]: ",
                  lambda v: v if v in pacing.MODES else (_ for _ in ()).throw(ValueError("uniform, normal or exponential")), p.mode)
    p.jitter = _ask(f"  Extra random +-% on every delay [{p.jitter:.0%}]: ",
                    lambda v: float(v.rstrip("%")) / 100, p.jitter)
    p.page_delay = _ask(f"  Delay between page loads [{D(p.page_delay)}]: ", R, p.page_delay)
    p.break_every = _ask(f"  Break every N downloads (0 = never) [{D(p.break_every, lambda x: str(int(x)))}]: ", I, p.break_every)
    if p.break_every[1] > 0:
        p.break_for = _ask(f"  Break length [{D(p.break_for)}]: ", R, p.break_for)
    p.max_per_hour = _ask(f"  Max downloads per hour, per site (0 = no limit) [{p.max_per_hour}]: ", int, p.max_per_hour)
    p.max_per_day = _ask(f"  Max downloads per day, per site (0 = no limit) [{p.max_per_day}]: ", int, p.max_per_day)
    h = p.hours
    hs = "any" if not h else f"{h[0] // 60:02d}:{h[0] % 60:02d}-{h[1] // 60:02d}:{h[1] % 60:02d}"
    p.hours = _ask(f"  Only download between (e.g. 22:00-07:00, 'any' = any time) [{hs}]: ",
                   lambda v: None if v.lower() in ("any", "all") else pacing.parse_hours(v), h)
    p.backoff = _ask(f"  Slow-down factor when the site throttles [{p.backoff:g}]: ", float, p.backoff)
    try:
        return p.validate()
    except ValueError as e:
        print(f"  {e}; using the 'normal' preset instead")
        return pacing.preset("normal")

