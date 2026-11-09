# Changelog

## 1.0.0 — 2026-11-09

First public version.

- `journal-dl` finds a journal on Wiley, Taylor & Francis or Ovid; `wiley-dl`, `tandf-dl` and `ovid-dl` take
  the same options for one site each.
- Plan and time estimate before every download; live progress line with the time left.
- Resume (`--resume`, or offered automatically), `--new`, follow + `--update`, `--schedule weekly|daily`.
- Background runs (`--background`, `--log`) and notifications (desktop; optional ntfy).
- `--doctor`, `--setup`, `--install-launcher`, `--open`.
- PDFs already saved from another site (same DOI) are copied instead of downloaded again.
- Speed presets and a full pacing model (ranges, spread, jitter, breaks, hourly/daily caps, hours, back-off).
- Licensed under the GNU GPL v3.0 or later; legal notice and terms of use (LEGAL.md), summarised in the README.
- Linux, macOS and Windows: per-OS folders, run lock, browser discovery, launchers, schedules, path-length limits.
