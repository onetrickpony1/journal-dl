# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

import random
from datetime import datetime

import pytest

from journal_dl import pacing
from journal_dl.pacing import Pacer, Pacing, parse_duration, parse_hours, parse_range


class Clock:
    """Fake wall + monotonic clock; sleep advances it and records waits."""
    def __init__(self, t=datetime(2026, 11, 9, 12, 0).timestamp()):
        self.t, self.waits = t, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.waits.append(s)
        self.t += s


def pacer(p, clock, times=None, seed=1):
    return Pacer(p, times_since=times, log=lambda *a: None, rng=random.Random(seed),
                 clock=clock.now, mono=clock.now, sleep=clock.sleep)


def test_parsing():
    assert parse_duration("90") == 90 and parse_duration("2m") == 120 and parse_duration("1h30m") == 5400
    assert parse_duration("1.5h") == 5400 and parse_duration("45s") == 45
    with pytest.raises(ValueError):
        parse_duration("2x")
    assert parse_range("10") == (10, 10) and parse_range("15-5") == (5, 15)
    assert parse_range("2m-5m") == (120, 300) and parse_range("30s..2m") == (30, 120)
    assert parse_hours("22:00-07:00") == (1320, 420) and parse_hours("9-17") == (540, 1020)
    with pytest.raises(ValueError):
        parse_hours("25:00-3")


def test_validation():
    with pytest.raises(ValueError):
        Pacing(delay=(1, 1)).validate()              # below the 2 s floor
    with pytest.raises(ValueError):
        Pacing(mode="zigzag").validate()
    with pytest.raises(ValueError):
        Pacing(jitter=1.5).validate()
    for name in pacing.PRESETS:
        assert pacing.preset(name).preset == name


@pytest.mark.parametrize("mode", pacing.MODES)
def test_sampling_bounds_and_spread(mode):
    c = Clock()
    pc = pacer(Pacing(delay=(10, 20), mode=mode), c)
    vals = [pc.sample((10, 20)) for _ in range(4000)]
    assert min(vals) >= 10
    assert max(vals) <= (60 if mode == "exponential" else 20)
    assert len({round(v, 3) for v in vals}) > 3000             # really random
    mean = sum(vals) / len(vals)
    if mode == "uniform":
        assert 14.5 < mean < 15.5
    if mode == "normal":
        mid = sum(1 for v in vals if 12.5 <= v <= 17.5) / len(vals)
        assert mid > 0.6                                         # concentrated in the middle
    if mode == "exponential":
        assert sum(1 for v in vals if v < 15) / len(vals) > 0.55  # mostly short


def test_jitter_widens():
    c = Clock()
    pc = pacer(Pacing(delay=(10, 10), jitter=0.2), c)
    vals = [pc.sample((10, 10)) for _ in range(2000)]
    assert 8 <= min(vals) < 8.5 and 11.5 < max(vals) <= 12


def test_delay_between_downloads_and_floor():
    c = Clock()
    pc = pacer(Pacing(delay=(5, 5), break_every=(0, 0)), c)
    pc.wait_download()                  # first start: delay counted from nothing
    c.waits.clear()
    for _ in range(5):
        pc.wait_download()
    assert all(abs(w - 5) < 1e-9 for w in c.waits)
    # time already spent downloading counts towards the gap
    c.t += 3
    c.waits.clear()
    pc.wait_download()
    assert abs(c.waits[0] - 2) < 1e-9


def test_breaks_happen_on_schedule():
    c = Clock()
    pc = pacer(Pacing(delay=(5, 5), break_every=(3, 3), break_for=(100, 100)), c)
    waits = []
    for _ in range(10):
        c.waits.clear()
        pc.wait_download()
        pc.on_success()
        waits.append(sum(c.waits))
    breaks = [i for i, w in enumerate(waits) if w > 50]
    assert breaks == [3, 6, 9]


def test_hourly_cap_waits_exactly_for_oldest_to_expire():
    c = Clock()
    done = []
    pc = pacer(Pacing(delay=(2, 2), break_every=(0, 0), max_per_hour=3), c,
               times=lambda t: [x for x in done if x >= t])
    for _ in range(3):
        pc.wait_download()
        done.append(c.t)
    first = done[0]
    c.waits.clear()
    pc.wait_download()                           # 4th must wait until the 1st is an hour old
    assert c.t >= first + 3600
    assert c.t - (first + 3600) < 10


def test_daily_cap_counts_previous_runs():
    c = Clock()
    earlier = [c.t - 3600 * h for h in range(1, 6)]   # 5 downloads in the last 5 hours (other runs)
    pc = pacer(Pacing(delay=(2, 2), break_every=(0, 0), max_per_day=5), c,
               times=lambda t: [x for x in earlier if x >= t])
    pc.wait_download()
    assert c.t >= min(earlier) + 86400


def test_active_hours_wraps_midnight():
    c = Clock(datetime(2026, 11, 9, 12, 0).timestamp())   # noon, outside 22:00-07:00
    pc = pacer(Pacing(delay=(2, 2), break_every=(0, 0), hours=(1320, 420)), c)
    pc.wait_download()
    started = datetime.fromtimestamp(c.t)
    assert started.hour == 22 and started.day == 9
    c2 = Clock(datetime(2026, 11, 9, 3, 0).timestamp())   # 03:00 is inside
    pc2 = pacer(Pacing(delay=(2, 2), break_every=(0, 0), hours=(1320, 420)), c2)
    pc2.wait_download()
    assert sum(c2.waits) < 5


def test_backoff_and_recovery():
    c = Clock()
    p = Pacing(delay=(10, 10), break_every=(0, 0), backoff=2, backoff_max=100, recover_after=2)
    pc = pacer(p, c)
    pc.wait_download()
    pc.on_throttle()
    pc.on_throttle()
    assert pc.slow == 4
    for _ in range(5):
        pc.on_throttle()
    assert pc.slow == 10                          # capped: 10 s * 10 = backoff_max
    c.waits.clear()
    pc.wait_download()
    assert abs(sum(c.waits) - 100) < 1e-6
    for _ in range(2):
        pc.on_success()
    assert pc.slow == 5                           # halves after recover_after successes


def test_retry_after_is_honoured():
    c = Clock()
    pc = pacer(Pacing(delay=(5, 5), break_every=(0, 0)), c)
    pc.wait_download()
    pc.on_throttle(retry_after=120)
    c.waits.clear()
    pc.wait_download()
    assert sum(c.waits) >= 120


def test_save_and_load_default(tmp_path, monkeypatch):
    monkeypatch.setattr(pacing, "CONFIG", tmp_path / "pacing.json")
    assert pacing.load_default().preset == "normal"
    p = pacing.preset("slow")
    p.hours = (1320, 420)
    pacing.save_default(p)
    q = pacing.load_default()
    assert q == p
    (tmp_path / "pacing.json").write_text("{broken")
    assert pacing.load_default().preset == "normal"          # never crash on a bad file


def test_from_args_overrides(monkeypatch, tmp_path):
    monkeypatch.setattr(pacing, "CONFIG", tmp_path / "none.json")
    class A: pass
    a = A()
    a.speed, a.delay, a.delay_mode, a.jitter, a.page_delay = "careful", "20-40", "normal", "10%", None
    a.break_every = a.break_for = a.hours = a.backoff = a.backoff_max = None
    a.max_per_hour = a.max_per_day = None
    p = pacing.from_args(a)
    assert p.delay == (20, 40) and p.mode == "normal" and p.jitter == 0.1
    assert p.max_per_hour == 120 and p.preset == "custom"   # rest of the careful preset kept
