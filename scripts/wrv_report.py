#!/usr/bin/env python3
"""Result bookkeeping and the final PASS/FAIL report for scripts/validate_macos.sh. Standard library only.
  wrv_report.py add NAME STATUS [DETAIL] [--optional]      append one result (STATUS: PASS FAIL SKIP BLOCKED)
  wrv_report.py junit FILE RESULTS [--min-client-safe N] [--min-ui N]   turn a pytest junit file into results
  wrv_report.py report RESULTS [--out FILE] [--header TEXT]     print the report; exit 0 only if every REQUIRED result is PASS
  wrv_report.py snapshot-real                                    hash of the real app-data and reports folders (to prove they were not touched)
Exit codes of `report`: 0 PASS, 1 a required check FAILED, 2 incomplete (a required check was BLOCKED or SKIPPED)."""
import json, os, sys, xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def add(path, name, status, detail="", required=True):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"name": name, "status": status, "detail": detail[:500], "required": required}) + "\n")


def junit(path, results, min_cs, min_ui):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    n = {"passed": 0, "failed": 0, "skipped": 0}
    by, skips = {}, {}
    for c in cases:
        cls = c.get("classname", "").split(".")[0]
        if c.find("failure") is not None or c.find("error") is not None:
            k = "failed"
        elif c.find("skipped") is not None:
            k = "skipped"
            msg = (c.find("skipped").get("message") or "skipped")[:70]
            skips[msg] = skips.get(msg, 0) + 1
        else:
            k = "passed"
        n[k] += 1
        by.setdefault(cls, {"passed": 0, "failed": 0, "skipped": 0})[k] += 1
    why = "; ".join(f"{v} skipped: {k}" for k, v in sorted(skips.items(), key=lambda kv: -kv[1])[:3])
    add(results, "regression + security suite (pytest, all existing tests)", "PASS" if n["failed"] == 0 and n["passed"] > 0 else "FAIL",
        f"{n['passed']} passed, {n['failed']} failed, {n['skipped']} skipped" + (f" ({why})" if why else ""))
    cs = by.get("test_client_safe", {"passed": 0})["passed"]
    ui = by.get("test_client_safe_ui", {"passed": 0})["passed"]
    add(results, "Client-Safe backend adversarial tests actually ran", "PASS" if cs >= min_cs and not by.get("test_client_safe", {}).get("failed") else "FAIL", f"{cs} passed (need >= {min_cs})")
    add(results, "Client-Safe real-click browser tests actually ran", "PASS" if ui >= min_ui and not by.get("test_client_safe_ui", {}).get("failed") else "FAIL",
        f"{ui} passed (need >= {min_ui})" + ("" if ui >= min_ui else "; install Google Chrome or set WR_CHROME=/path/to/chrome"))


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
    if c == "report":
        return report(a[1], opt("--out"), opt("--header"))
    if c == "snapshot-real":
        import wrv
        print(wrv.snapshot(wrv.real_dirs()))
        return 0
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
