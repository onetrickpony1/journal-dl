from pathlib import Path

from journal_dl import browser


def test_flatpak_launcher_gets_profile_access():
    exe = "/var/lib/flatpak/exports/bin/com.google.Chrome"
    assert browser.flatpak_id(exe) == "com.google.Chrome"
    assert browser.launch_args(exe, Path("/p")) == ["flatpak", "run", "--filesystem=/p", "com.google.Chrome"]


def test_plain_binary_unchanged():
    assert browser.flatpak_id("/usr/bin/chromium") is None
    assert browser.launch_args("/usr/bin/chromium", Path("/p")) == ["/usr/bin/chromium"]


def test_resolve_flatpak_forms(tmp_path, monkeypatch):
    exports = tmp_path / "exports" / "bin"
    exports.mkdir(parents=True)
    (exports / "org.chromium.Chromium").write_text("#!/bin/sh\n")
    monkeypatch.setattr(browser, "FLATPAK_EXPORTS", (exports,))
    want = str(exports / "org.chromium.Chromium")
    for v in ("org.chromium.Chromium", "flatpak run org.chromium.Chromium",
              "flatpak run --branch=stable org.chromium.Chromium", want):
        assert browser._resolve(v) == want
    assert browser._resolve("") is None
