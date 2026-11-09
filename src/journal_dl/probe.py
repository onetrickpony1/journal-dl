# journal-dl: download journal article PDFs with your own library sign-in.
# Copyright (C) 2026 journal-dl contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the License,
# or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file and LEGAL.md.

"""Developer tool: find out how a site delivers article PDFs (used to build the Ovid support).

    python -m journal_dl.probe [--count 3] [--out probe-output]

The user opens an Ovid issue page in the managed browser. For the first N
article PDF controls we click once, watch every channel a PDF can arrive by
(download event, new tab, PDF network response, embedded viewer), save what
arrives, validate it and record how it was delivered. Output: probe-output/.
Nothing here guesses URLs or IDs; it only clicks controls the page shows.
"""
import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from . import sanitize
from .validate import check_pdf, identity_hint

PDF_CONTROL = re.compile(r"\bPDF\b", re.I)
ISSUE_LABEL = re.compile(r"Volume\s+\S+\s+pgs\.[^\n]*|Volume\s+\S+\([^)]*\)[^\n]*")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.I)

# JS: for a control element, climb to the smallest ancestor that looks like
# an article card (contains a heading/title link and some text) and return its data.
CARD_JS = """
el => {
  let n = el;
  for (let i = 0; i < 12 && n && n.parentElement; i++) {
    n = n.parentElement;
    const txt = (n.innerText || '').trim();
    if (txt.length > 80 && n.querySelector('a[href], h2, h3, h4')) break;
  }
  const links = [...n.querySelectorAll('a[href]')].map(a => ({text: (a.innerText||'').trim(), href: a.href}));
  const heading = n.querySelector('h2, h3, h4, .title, [class*=title]');
  return {text: (n.innerText || '').slice(0, 2000), heading: heading ? heading.innerText.trim() : null, links};
}
"""


def _pdf_controls(page):
    seen, out = set(), []
    for role in ("link", "button"):
        for loc in page.get_by_role(role, name=PDF_CONTROL).all():
            try:
                if not loc.is_visible():
                    continue
                key = loc.evaluate("e => e.outerHTML.slice(0, 300)")
            except Exception:
                continue
            if key not in seen:
                seen.add(key)
                out.append(loc)
    return out


def _card(loc):
    c = loc.evaluate(CARD_JS)
    doi = DOI_RE.search(c["text"])
    title = c["heading"] or next((l["text"] for l in c["links"] if len(l["text"]) > 25), None)
    ids = {}
    for l in c["links"]:
        ids.update(sanitize.id_params(l["href"]))
    return {
        "title": title,
        "doi": doi.group(0).rstrip(".,;)") if doi else None,
        "id_params": ids,
        "link_paths": sorted({sanitize.url(l["href"]) for l in c["links"]})[:20],
    }


def _deliver(ctx, page, control, tmp: Path, timeout_s: float):
    """Click one control; return (channel, details) once a PDF lands in tmp, or ('none', details)."""
    events = {"download": None, "pages": [], "pdf_responses": []}

    def on_resp(r):
        try:
            if "application/pdf" in (r.headers.get("content-type") or "").lower():
                events["pdf_responses"].append(r)
        except Exception:
            pass

    on_dl = lambda d: events.__setitem__("download", d)
    on_page = lambda p: events["pages"].append(p)
    ctx.on("response", on_resp)
    ctx.on("page", on_page)
    page.on("download", on_dl)
    start_url = page.url
    details = {}
    try:
        control.click()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            page.wait_for_timeout(500)
            if events["download"] or events["pdf_responses"]:
                break
        details["new_tabs"] = [sanitize.url(p.url) for p in events["pages"]]
        details["same_tab_navigated"] = page.url != start_url
        details["landing_url"] = sanitize.url(page.url)

        if events["download"]:
            d = events["download"]
            d.save_as(tmp)
            details["suggested_filename"] = d.suggested_filename
            details["source_url"] = sanitize.url(d.url)
            return "download-event", details

        for r in events["pdf_responses"]:
            details["source_url"] = sanitize.url(r.url)
            details["ovid_an"] = sanitize.ovid_an(r.url)
            details["status"] = r.status
            where = "-new-tab" if r.frame.page != page else ""
            try:
                body = r.body()
            except Exception as e:
                body, details["body_error"] = b"", type(e).__name__
            if body.lstrip()[:5] == b"%PDF-":
                tmp.write_bytes(body)
                return "pdf-response" + where, details
            # Chrome's PDF viewer swallows the bytes (body() returns its HTML stub):
            # refetch the same URL inside the browser context so its cookies apply.
            details["viewer_stub"] = bool(body)
            resp = ctx.request.get(r.url)
            if "application/pdf" in resp.headers.get("content-type", ""):
                tmp.write_bytes(resp.body())
                return "pdf-refetch" + where, details

        # Embedded viewer: look for iframe/embed/object pointing at a PDF in the landing page(s)
        for p in [page] + events["pages"]:
            try:
                p.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
            srcs = p.evaluate("""() => [...document.querySelectorAll('iframe[src], embed[src], object[data]')]
                                     .map(e => e.src || e.data)""")
            details.setdefault("embedded_srcs", []).extend(sanitize.url(s) for s in srcs)
            for s in srcs:
                resp = ctx.request.get(s)
                if "application/pdf" in resp.headers.get("content-type", ""):
                    tmp.write_bytes(resp.body())
                    return "embedded-viewer", details
        return "none", details
    finally:
        ctx.remove_listener("response", on_resp)
        ctx.remove_listener("page", on_page)
        page.remove_listener("download", on_dl)
        for p in events["pages"]:
            try:
                p.close()
            except Exception:
                pass


def issue_label(page):
    m = ISSUE_LABEL.search(page.inner_text("body").replace("\xa0", " "))
    return " ".join(m.group(0).split()) if m else None


def _breadcrumb(label):
    """'Volume 20(3) pgs. 151-215 September 2021' -> '20(3) September 2021' (Ovid breadcrumb text)."""
    m = re.match(r"Volume\s+(\S+\([^)]*\)).*?([A-Z][a-z]+(?:/[A-Z][a-z]+)?\s+\d{4})\s*$", label or "")
    return f"{m.group(1)} {m.group(2)}" if m else None


def _return_to_issue(page, label, issue_url):
    """Ovid issue URLs are session state, not addresses: go Back, then verify the heading."""
    if issue_label(page) == label:
        return True
    crumb = _breadcrumb(label)
    if crumb:
        link = page.get_by_role("link", name=crumb, exact=True)
        if link.count():
            link.first.click()
            page.wait_for_load_state("load")
            page.wait_for_timeout(1500)
    for _ in range(3):
        if issue_label(page) == label:
            return True
        try:
            page.go_back(wait_until="load")
            page.wait_for_timeout(1500)
        except Exception:
            break
    return issue_label(page) == label


def run(ctx, page, out: Path, count: int = 3, delay_s: float = 5.0, timeout_s: float = 30.0):
    out.mkdir(parents=True, exist_ok=True)
    (out / "pdfs").mkdir(exist_ok=True)
    (out / "quarantine").mkdir(exist_ok=True)
    issue_url = page.url  # kept in memory only, never written
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out / f"issue-page-{stamp}.html").write_text(page.content())  # private local snapshot for adapter work

    label = issue_label(page)
    n_controls = len(_pdf_controls(page))
    report = {"run": stamp, "issue_page": sanitize.url(issue_url), "page_title": page.title(),
              "issue_label": label,
              "pdf_controls_found": n_controls, "articles": []}
    print(f"Found {n_controls} PDF controls on this page; probing {min(count, n_controls)}.")

    for i in range(min(count, n_controls)):
        if not _return_to_issue(page, label, issue_url):
            report["stopped"] = f"could not return to issue {label!r} (now {issue_label(page)!r})"
            print("STOP:", report["stopped"])
            break
        control = _pdf_controls(page)[i]
        rec = {"index": i + 1, "issue_label": label, **_card(control),
               "control_text": control.inner_text().strip()[:60]}
        print(f"[{i+1}] {rec['title']!r}")
        tmp = out / f".tmp-{stamp}-{i+1}.part"
        try:
            channel, details = _deliver(ctx, page, control, tmp, timeout_s)
        except Exception as e:
            channel, details = "error", {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        rec["channel"], rec["details"] = channel, details
        if tmp.exists():
            chk = check_pdf(tmp)
            rec["validation"] = {k: v for k, v in asdict(chk).items() if k != "first_page_text"}
            rec["identity"] = identity_hint(chk, rec["doi"], rec["title"]) if chk.ok else None
            dest_dir = out / ("pdfs" if chk.ok else "quarantine")
            dest = dest_dir / f"{i+1:03d}_{chk.sha256[:12]}.{'pdf' if chk.ok else 'bin'}"
            tmp.replace(dest)
            rec["saved_as"] = str(dest.relative_to(out))
        print(f"    channel={channel} -> {rec.get('validation', {}).get('reason', 'nothing received')}"
              f" identity={rec.get('identity')}")
        report["articles"].append(rec)
        if i + 1 < min(count, n_controls):
            time.sleep(delay_s)

    _return_to_issue(page, label, issue_url)
    (out / f"report-{stamp}.json").write_text(json.dumps(report, indent=2))
    ok = sum(1 for a in report["articles"] if a.get("validation", {}).get("ok"))
    print(f"\n{ok}/{len(report['articles'])} validated PDFs. Report: {out / f'report-{stamp}.json'}")
    return report


def main(argv=None):
    import argparse
    from playwright.sync_api import sync_playwright
    from . import browser
    ap = argparse.ArgumentParser(prog="python -m journal_dl.probe",
                                 description="Click the first PDF controls on the issue page open in the "
                                             "downloader's browser window and report how PDFs arrive.")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--delay", type=float, default=5.0)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--out", default="probe-output")
    a = ap.parse_args(argv)
    with sync_playwright() as p:
        ctx = browser.connect(p)
        input("Open an issue's table of contents in the browser window (signed in), then press Enter... ")
        page = ctx.pages[-1]
        run(ctx, page, Path(a.out), count=a.count, delay_s=a.delay, timeout_s=a.timeout)


if __name__ == "__main__":
    main()
