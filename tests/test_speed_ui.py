# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

import pytest

from journal_dl import pacing, speed_ui


def feed(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


@pytest.mark.parametrize("typed", ["[1m-5m]", " [1m-5m] ", "[ 1m-5m ]", "1m-5m"])
def test_ask_accepts_value_typed_with_brackets(monkeypatch, typed):
    # The prompt shows the current value as "[5s-12s]"; typing a value the same way must work.
    feed(monkeypatch, typed)
    assert speed_ui._ask("Delay [5s-12s]: ", pacing.parse_range, (5.0, 12.0)) == (60.0, 300.0)


def test_ask_enter_keeps_none_default(monkeypatch):
    # hours = None ("any") must be kept on Enter instead of asking forever.
    feed(monkeypatch, "")
    assert speed_ui._ask("Hours [any]: ", pacing.parse_hours, None) is None


def test_ask_without_default_asks_again_on_enter(monkeypatch, capsys):
    feed(monkeypatch, "", "7")
    assert speed_ui._ask("N: ", int) == 7


def test_custom_speed_bracketed_delay_and_enter_for_rest(monkeypatch):
    base = pacing.preset("normal")   # hours = None
    feed(monkeypatch, "[1m-5m]", *[""] * 20)
    p = speed_ui.custom_speed(base)
    assert p.delay == (60.0, 300.0)
    assert p.hours is None
    assert p.preset == "custom"
