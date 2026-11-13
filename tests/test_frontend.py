# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Command line, saved state and OS helpers (no browser)."""
import sys
from pathlib import Path

import pytest

from journal_dl import files, frontend, paths, settings, state, system


def options(ap):
    return {s for a in ap._actions for s in a.option_strings}


def test_same_options_on_every_site_command():
    per_site = {name: options(frontend.build_parser(frontend.SITES[name])) for name in frontend.ORDER}
    first = per_site["wiley"]
    assert all(o == first for o in per_site.values())
    assert options(frontend.build_parser(None)) - first == {"--site", "--alternate"}   # journal-dl only


def test_month_help_only_where_sites_have_months():
    assert "2026-11" in frontend.build_parser(frontend.SITES["ovid"]).format_help()
    assert "2026-11 for one month" not in frontend.build_parser(frontend.SITES["tandf"]).format_help()


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("JOURNAL_DL_CONFIG", str(tmp_path / "cfg"))
    monkeypatch.setenv("JOURNAL_DL_DATA", str(tmp_path / "data"))
    return tmp_path


def test_state_resume_follow_and_sites(cfg):
    state.start_run({"site": "wiley", "journal": "J", "years": [2026, 2026]})
    state.progress("Vol 1 No 2 - Summer 2026", 3, 9)
    lr = state.unfinished()
    assert lr["where"].startswith("Vol 1") and lr["done"] == 3
    state.end_run(True)
    assert state.unfinished() is None
    state.follow("tandf", "European Journal of Work and Organizational Psychology")
    state.follow("tandf", "European Journal of Work and Organizational Psychology")
    assert len(state.follows()) == 1
    assert state.unfollow("european journal of work and organizational psychology") == 1
    state.remember_site("Personnel Psychology", "wiley")
    assert state.known_site("personnel  psychology") == "wiley"


def test_platform_folders(monkeypatch, tmp_path):
    monkeypatch.delenv("JOURNAL_DL_CONFIG", raising=False)
    monkeypatch.delenv("OVID_DL_CONFIG", raising=False)
    monkeypatch.delenv("JOURNAL_DL_DATA", raising=False)
    monkeypatch.delenv("OVID_ARCHIVE_DATA", raising=False)
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\u\AppData\Roaming")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\u\AppData\Local")
    assert str(paths.config_dir()).endswith("journal-dl") and "Roaming" in str(paths.config_dir())
    assert "Local" in str(paths.data_dir())
    monkeypatch.setattr(sys, "platform", "darwin")
    assert paths.config_dir() == tmp_path / "Library" / "Application Support" / "journal-dl"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert paths.config_dir() == tmp_path / ".config" / "journal-dl"


def test_show_path_aliases(monkeypatch):
    monkeypatch.setitem(settings.S, "path_aliases", [["/mnt/share/H", "H:"]])
    p = Path("/mnt/share/H/Journals/A B")
    assert system.show_path(p) == f"{p}  (H:\\Journals\\A B)"
    assert system.show_path(Path("/elsewhere")) == str(Path("/elsewhere"))
    assert system.show_path(Path("/mnt/share/Hx")) == str(Path("/mnt/share/Hx"))   # not a folder boundary


def test_launcher_and_schedule_files(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "desktop_dir", lambda: tmp_path)
    for plat, name in (("linux", "journal-dl.desktop"), ("darwin", "Journal Downloader.command"),
                       ("win32", "Journal Downloader.bat")):
        monkeypatch.setattr(sys, "platform", plat)
        lf = system.launcher_files()
        assert any(p.name == name for p in lf)
        assert all("--easy" in body for body, _ in lf.values())
    monkeypatch.setattr(sys, "platform", "darwin")
    plist = system.schedule_files("weekly")
    assert "--update" in next(iter(plist.values())) and "Weekday" in next(iter(plist.values()))
    monkeypatch.setattr(sys, "platform", "linux")
    units = system.schedule_files("daily")
    assert any("OnCalendar=*-*-* 09:00:00" in b for b in units.values())


def test_windows_name_room():
    deep = Path("C:/" + "x" * 180)
    assert files.room_for_name(deep, windows=True) < 110
    assert files.room_for_name(Path("C:/a"), windows=True) == 110
    assert files.room_for_name(deep, windows=False) == 110


def test_settings_proxy_naming(monkeypatch):
    monkeypatch.setitem(settings.S, "proxy", "proxy.library.example.edu")
    assert settings.proxied("www.tandfonline.com") == "https://www-tandfonline-com.proxy.library.example.edu"
    monkeypatch.setitem(settings.S, "proxy", "")
    assert settings.proxied("onlinelibrary.wiley.com") == "https://onlinelibrary.wiley.com"


# ---- issue #11: the guide says where PDFs go and lets you change it
@pytest.fixture
def folder_cfg(cfg, monkeypatch):
    from journal_dl import paths
    monkeypatch.delenv("JOURNAL_DL_OUTPUT", raising=False)
    monkeypatch.delenv("OVID_ARCHIVE_ROOT", raising=False)
    monkeypatch.setattr(paths, "default_output", lambda: cfg / "Documents" / "Journal Downloads")
    monkeypatch.setitem(settings.S, "output", None)
    return cfg


def answers(*seq):
    it = iter(seq)
    return lambda prompt: next(it)


def test_guide_keeps_folder_on_enter(folder_cfg, capsys):
    a = frontend.build_parser().parse_args(["--easy"])
    assert frontend.ask_folder(a, answers("")) == folder_cfg / "Documents" / "Journal Downloads"
    assert "PDFs go to:" in capsys.readouterr().out
    assert not settings.path().exists()                   # nothing saved


def test_guide_saves_typed_folder_until_reset(folder_cfg, monkeypatch):
    a = frontend.build_parser().parse_args(["--easy"])
    monkeypatch.chdir(folder_cfg)
    new = frontend.ask_folder(a, answers("papers"))      # relative: from the current folder
    assert new == (folder_cfg / "papers").resolve() and new.is_dir()
    assert settings.load()["output"] == str(new) and settings.output_dir() == new
    assert frontend.ask_folder(a, answers("default")) == folder_cfg / "Documents" / "Journal Downloads"
    assert settings.load()["output"] is None


def test_guide_rejects_a_file_and_asks_again(folder_cfg):
    a = frontend.build_parser().parse_args(["--easy"])
    (folder_cfg / "f.txt").write_text("x")
    assert frontend.ask_folder(a, answers(str(folder_cfg / "f.txt"), "")) == settings.output_dir()


def test_guide_does_not_ask_with_dash_o(folder_cfg):
    a = frontend.build_parser().parse_args(["--easy", "-o", str(folder_cfg / "x")])
    assert frontend.ask_folder(a, answers()) == folder_cfg / "x"     # no input() call
