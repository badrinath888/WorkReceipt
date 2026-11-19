#!/usr/bin/env python3
"""Result bookkeeping and the final PASS/FAIL report for scripts/validate_macos.sh. Standard library only.
  wrv_report.py add NAME STATUS [DETAIL] [--optional]      append one result (STATUS: PASS FAIL SKIP BLOCKED)
  wrv_report.py junit FILE RESULTS [--min-client-safe N] [--min-ui N]   turn a pytest junit file into results
  wrv_report.py deps RESULTS                                     check Chrome + poppler are discoverable (with install instructions)
  wrv_report.py report RESULTS [--out FILE] [--header TEXT]     print the report; exit 0 only if every REQUIRED result is PASS
  wrv_report.py snapshot-real                                    hash of the real app-data and reports folders (to prove they were not touched)
Exit codes of `report`: 0 PASS, 1 a required check FAILED, 2 incomplete (a required check was BLOCKED or SKIPPED)."""
import json, os, sys, xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def add(path, name, status, detail="", required=True):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"name": name, "status": status, "detail": detail[:500], "required": required}) + "\n")


CRITICAL = ("test_client_safe", "test_client_safe_ui", "test_pdf_quality", "test_validation_scripts", "test_e2e_desktop", "test_interaction_audit",
            "test_pdf_metadata_injection", "test_buildinfo", "test_native_import_isolation")
# Release gate: these PDF security tests must have RUN AND PASSED (a skip is a failure). Several need poppler (`brew install poppler`) and Chrome.
REQUIRED_PDF_SECURITY = (
    "test_client_safe.PdfArtifact.test_metadata_is_checked", "test_client_safe.PdfArtifact.test_hidden_text_is_detected",
    "test_client_safe.PdfArtifact.test_links_and_annotations_are_detected", "test_client_safe.EndToEnd.test_pdf_export_is_checked_and_clean",
    "test_pdf_metadata_injection.InjectedPdfMetadata.test_private_pdf_title_is_rejected_by_both_checkers_with_every_extractor",
    "test_pdf_metadata_injection.InjectedPdfMetadata.test_title_the_extractor_dropped_is_still_caught_from_the_file_itself",
    "test_pdf_metadata_injection.InjectedPdfMetadata.test_other_information_fields_are_rejected",
    "test_pdf_metadata_injection.ExportWithoutPoppler.test_client_export_refuses_a_pdf_whose_title_was_changed_after_printing",
    "test_pdf_metadata_injection.CreatorPolicy.test_arbitrary_creators_are_refused_by_the_product_validator",
    "test_pdf_metadata_injection.CreatorInRealPdf.test_malicious_creator_is_rejected_by_both_checkers_with_every_extractor",
    "test_pdf_metadata_injection.ExportRefusalDiagnostics.test_malicious_creator_refuses_the_export_and_reports_only_field_class_reason",
    "test_native_import_isolation.NoSnapshotPatchingAnywhere.test_no_test_or_script_uses_patch_dict_on_sys_modules",
)


def _short(c):
    node = c.find("failure") if c.find("failure") is not None else c.find("error")
    msg = ((node.get("message") or "") if node is not None else "").strip().splitlines()
    return f"{c.get('classname', '').split('.')[0]}::{c.get('name')}" + (f" ({msg[0][:110]})" if msg else "")


def junit(path, results, min_cs, min_ui):
    root = ET.parse(path).getroot()
    n = {"passed": 0, "failed": 0, "skipped": 0}
    by, skips, failed_by, crit_skips = {}, {}, {}, {}
    all_failed = []
    outcome = {}
    for c in root.iter("testcase"):
        cls = c.get("classname", "").split(".")[0]
        if c.find("failure") is not None or c.find("error") is not None:
            k = "failed"
            all_failed.append(_short(c))
            failed_by.setdefault(cls, []).append(_short(c))
        elif c.find("skipped") is not None:
            k = "skipped"
            msg = (c.find("skipped").get("message") or "skipped")[:70]
            skips[msg] = skips.get(msg, 0) + 1
            if cls in CRITICAL:
                crit_skips[msg] = crit_skips.get(msg, 0) + 1
        else:
            k = "passed"
        outcome[c.get("classname", "") + "." + c.get("name", "")] = k
        n[k] += 1
        by.setdefault(cls, {"passed": 0, "failed": 0, "skipped": 0})[k] += 1
    if all_failed:                                               # full list next to the results, so a failure can be diagnosed without re-running
        open(os.path.join(os.path.dirname(results), "failed-tests.txt"), "w", encoding="utf-8").write("\n".join(all_failed) + "\n")
    why = "; ".join(f"{v} skipped: {k}" for k, v in sorted(skips.items(), key=lambda kv: -kv[1])[:3])
    names = (" FAILED: " + " | ".join(all_failed[:8]) + (" ..." if len(all_failed) > 8 else "")) if all_failed else ""
    add(results, "regression + security suite (pytest, all existing tests)", "PASS" if n["failed"] == 0 and n["passed"] > 0 else "FAIL",
        f"{n['passed']} passed, {n['failed']} failed, {n['skipped']} skipped" + (f" ({why})" if why else "") + names)
    cs, csf = by.get("test_client_safe", {"passed": 0})["passed"], failed_by.get("test_client_safe", [])
    ui, uif = by.get("test_client_safe_ui", {"passed": 0})["passed"], failed_by.get("test_client_safe_ui", [])
    add(results, "Client-Safe backend adversarial tests actually ran and passed", "PASS" if cs >= min_cs and not csf else "FAIL",
        f"{cs} passed (need >= {min_cs})" + (f"; FAILED: {' | '.join(csf[:5])}" if csf else ""))
    add(results, "Client-Safe real-click browser tests actually ran and passed", "PASS" if ui >= min_ui and not uif else "FAIL",
        f"{ui} passed (need >= {min_ui})" + (f"; FAILED: {' | '.join(uif[:5])}" if uif else "") + ("" if ui >= min_ui else "; install Google Chrome or set WR_CHROME=/path/to/chrome"))
    st, detail = pdf_gate(outcome)
    add(results, "required PDF security tests ran and passed (release gate)", st, detail)
    cs_total = sum(crit_skips.values())
    add(results, "no critical tests were skipped", "PASS" if not cs_total else "FAIL",
        "none skipped in the Client-Safe, PDF-quality, browser and script suites" if not cs_total else
        f"{cs_total} critical test(s) skipped, so coverage is incomplete: " + "; ".join(f"{v}x {k}" for k, v in crit_skips.items()) + ". Run: brew install poppler; brew install --cask google-chrome")


def pdf_gate(outcome):
    """-> (status, detail) for the required PDF security tests."""
    bad = {t: outcome.get(t, "missing") for t in REQUIRED_PDF_SECURITY if outcome.get(t) != "passed"}
    if not bad:
        return "PASS", f"all {len(REQUIRED_PDF_SECURITY)} required PDF security tests ran and passed"
    why = "; ".join(f"{t.split('.', 1)[1]}: {v}" for t, v in list(bad.items())[:4])
    return "FAIL", (f"{len(bad)} of {len(REQUIRED_PDF_SECURITY)} required PDF security tests did not pass ({why}). Release approval needs them: "
                    "brew install poppler; brew install --cask google-chrome; then re-run scripts/validate_macos.sh")


def deps(results):
    import shutil
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    chrome = next((c for c in (os.environ.get("WR_CHROME"), shutil.which("google-chrome"), shutil.which("chromium"), mac if os.path.exists(mac) else None) if c and os.path.exists(c)), None)
    add(results, "Google Chrome found (browser tests and Chrome PDF path)", "PASS" if chrome else "FAIL",
        chrome or "not found. Install: brew install --cask google-chrome   (or set WR_CHROME=/path/to/chrome)")
    missing = [t for t in ("pdftotext", "pdfinfo", "pdftoppm") if not shutil.which(t)]
    add(results, "poppler found (pdftotext, pdfinfo, pdftoppm: PDF text/metadata tests)", "FAIL" if missing else "PASS",
        ("missing " + ", ".join(missing) + ". Install: brew install poppler   (Homebrew dirs /opt/homebrew/bin and /usr/local/bin are searched automatically)") if missing else "all three on PATH")


def report(results, out, header):
    rows = [json.loads(l) for l in open(results, encoding="utf-8") if l.strip()] if os.path.exists(results) else []
    lines = [header, ""] if header else []
    w = max([len(r["name"]) for r in rows] + [10])
    for r in rows:
        tag = f"{r['status']:<7} {'req' if r['required'] else 'opt'}"
        lines.append(f"{tag}  {r['name']}" + (f"\n{'':14}{r['detail']}" if r["detail"] and (r["status"] != "PASS" or len(r["detail"]) < 400) else ""))
    req = [r for r in rows if r["required"]]
    failed = [r for r in req if r["status"] == "FAIL"]
    incomplete = [r for r in req if r["status"] in ("BLOCKED", "SKIP")]
    count = lambda s: sum(1 for r in rows if r["status"] == s)
    lines += ["", f"{count('PASS')} PASS, {count('FAIL')} FAIL, {count('BLOCKED')} BLOCKED, {count('SKIP')} SKIP  ({len(req)} required)"]
    if failed:
        lines.append("RESULT: FAIL - " + "; ".join(r["name"] for r in failed[:6]))
        code = 1
    elif incomplete or not rows:
        lines.append("RESULT: INCOMPLETE - required checks not run: " + "; ".join(r["name"] for r in incomplete[:6]))
        code = 2
    else:
        selftest = os.environ.get("WRV_SELFTEST") == "1"
        lines.append("RESULT: SELFTEST PASS - Linux dry run of the validation logic. This is NOT macOS validation." if selftest else "RESULT: PASS")
        code = 0
    text = "\n".join(lines)
    print(text)
    if out:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "w", encoding="utf-8").write(text + "\n")
        print(f"\nreport saved: {out}")
    return code


def main(a):
    if not a:
        print(__doc__); return 2
    c = a[0]
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    if c == "add":
        add(os.environ["WRV_RESULTS"], a[1], a[2], a[3] if len(a) > 3 and not a[3].startswith("--") else "", "--optional" not in a)
        return 0
    if c == "junit":
        junit(a[1], a[2], int(opt("--min-client-safe", 30)), int(opt("--min-ui", 10)))
        return 0
    if c == "deps":
        deps(a[1])
        return 0
    if c == "report":
        return report(a[1], opt("--out"), opt("--header"))
    if c == "snapshot-real":
        import wrv
        print(wrv.snapshot(wrv.real_dirs()))
        return 0
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
