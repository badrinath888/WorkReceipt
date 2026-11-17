#!/bin/bash
# One-command macOS validation for WorkReceipt Client-Safe Mode.   Usage:  scripts/validate_macos.sh [--keep] [--quick] [--selftest] [--rebuild]
#   --keep      keep the temp sandbox (synthetic reports, logs) even when everything passes
#   --quick     skip the regression suite (the run is then reported INCOMPLETE, never PASS)
#   --selftest  Linux dry run of the validation LOGIC using Chrome/poppler; labelled as NOT macOS evidence
#   --rebuild   first rebuild dist/WorkReceipt.app from this checkout (desktop/build_macos.sh), so a stale packaged app can never be validated
# Everything runs against a synthetic workspace in a temp sandbox. Your real projects, ~/.claude, app data and reports are never read or
# written; a before/after fingerprint of the real app-data and reports folders proves it. Needs network once, for pip.
# Exit codes: 0 PASS, 1 a required check failed, 2 incomplete (a required check could not run), 64 usage/setup error.
set -u -o pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEEP=0; QUICK=0; SELF=0; REBUILD=0
for a in "$@"; do case "$a" in --keep) KEEP=1;; --quick) QUICK=1;; --selftest) SELF=1;; --rebuild) REBUILD=1;; -h|--help) sed -n 2,10p "$0"; exit 0;; *) echo "unknown option: $a" >&2; exit 64;; esac; done
OS="$(uname -s)"
if [ "$OS" != "Darwin" ] && [ "$SELF" != 1 ]; then
  echo "note: this is not macOS. The native stages will be reported BLOCKED (exit 2). Use --selftest for a labelled Linux dry run." >&2
fi
[ "$SELF" = 1 ] && [ "$OS" = "Darwin" ] && { echo "--selftest is for Linux only" >&2; exit 64; }

# Homebrew is not on PATH in every shell (IDE terminals, ssh, cron); poppler and chrome are looked up there too.
for d in /opt/homebrew/bin /usr/local/bin; do [ -d "$d" ] && case ":$PATH:" in *":$d:"*) ;; *) PATH="$PATH:$d";; esac; done; export PATH
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null || { echo "error: need Python >= 3.9 (set PYTHON=/path/to/python3)" >&2; exit 64; }

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/wr-validate.XXXXXX")"
export WRV_RESULTS="$ROOT/results.jsonl"; : > "$WRV_RESULTS"
export PYTHONDONTWRITEBYTECODE=1
[ "$SELF" = 1 ] && export WRV_SELFTEST=1
REPORT="$REPO/validation-results/macos-validation-$(date +%Y%m%d-%H%M%S).txt"
R() { "$PY" "$REPO/scripts/wrv_report.py" "$@"; }                 # R add NAME STATUS [DETAIL] [--optional]   (appends to $WRV_RESULTS)
mkdir -p "$ROOT/pytest" "$ROOT/native/tmp" "$ROOT/app/tmp" "$ROOT/logs"
echo "WorkReceipt macOS validation - sandbox: $ROOT"

# ---- 1. isolation: fingerprint the REAL data folders so we can prove they were not touched
BEFORE="$(R snapshot-real)"
R add "sandbox created; real app data and reports folders fingerprinted" PASS "$ROOT"

# ---- 2. tooling in a private venv inside the repo (reused between runs)
VENV="$REPO/.validate-venv"
if [ ! -x "$VENV/bin/python" ]; then "$PY" -m venv "$VENV" >"$ROOT/logs/venv.log" 2>&1; fi
VPY="$VENV/bin/python"
PKGS=(pytest pypdf playwright pillow)
[ "$OS" = "Darwin" ] && PKGS+=("pywebview>=5.3,<6" pyobjc-framework-Quartz pyobjc-framework-WebKit)
if [ -x "$VPY" ] && "$VPY" -m pip install -q --disable-pip-version-check "${PKGS[@]}" >"$ROOT/logs/pip.log" 2>&1; then
  R add "tooling installed in .validate-venv" PASS "${PKGS[*]}"
  TOOLS=1
else
  R add "tooling installed in .validate-venv" FAIL "pip failed (network?). See $ROOT/logs/pip.log"
  TOOLS=0
fi
CHROME_BIN="${WR_CHROME:-}"
if [ -z "$CHROME_BIN" ]; then for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" /usr/bin/google-chrome /usr/bin/chromium; do [ -x "$c" ] && CHROME_BIN="$c" && break; done; fi
[ -n "$CHROME_BIN" ] && export WR_CHROME="$CHROME_BIN"

R deps "$WRV_RESULTS"
MISSING=""; for t in pdftotext pdfinfo pdftoppm; do command -v "$t" >/dev/null 2>&1 || MISSING="$MISSING $t"; done
if [ -n "$MISSING" ] && [ "$SELF" != 1 ]; then
  echo "WARNING: poppler is missing (${MISSING# }). The required PDF security tests will be SKIPPED, so this run cannot PASS and the build cannot be approved." >&2
  echo "         Fix:  brew install poppler   (and, if Chrome is missing, brew install --cask google-chrome)" >&2
fi
if [ "$REBUILD" = 1 ]; then
  if [ "$OS" != Darwin ]; then R add "clean rebuild of dist/WorkReceipt.app from this checkout" BLOCKED "requires macOS"
  else
    echo "rebuilding dist/WorkReceipt.app from this checkout (a few minutes)..."
    if "$REPO/desktop/build_macos.sh" >"$ROOT/logs/build.log" 2>&1; then R add "clean rebuild of dist/WorkReceipt.app from this checkout" PASS "the build script verified the app reports this source"
    else R add "clean rebuild of dist/WorkReceipt.app from this checkout" FAIL "build failed; see $ROOT/logs/build.log"; fi
  fi
fi

# ---- 3. regression + security suite (existing tests, unmodified assertions)
if [ "$QUICK" = 1 ]; then
  R add "regression + security suite (pytest, all existing tests)" SKIP "--quick"
elif [ "$TOOLS" = 1 ]; then
  echo "running the regression suite (a few minutes)..."
  ( cd "$REPO" && TMPDIR="$ROOT/native/tmp" "$VPY" -m pytest -q -p no:cacheprovider --junitxml="$ROOT/junit.xml" >"$ROOT/logs/pytest.log" 2>&1 )
  if [ -s "$ROOT/junit.xml" ]; then R junit "$ROOT/junit.xml" "$WRV_RESULTS"; else R add "regression + security suite (pytest, all existing tests)" FAIL "pytest produced no result file; see $ROOT/logs/pytest.log"; fi
  tail -n 3 "$ROOT/logs/pytest.log" | sed 's/^/    pytest: /'
else
  R add "regression + security suite (pytest, all existing tests)" BLOCKED "tooling not installed"
fi

# ---- 4/5. native export + live app
if [ "$TOOLS" = 1 ] && { [ "$OS" = "Darwin" ] || [ "$SELF" = 1 ]; }; then
  echo "running the native export / PDF checks..."
  ( cd "$REPO" && WRV_ROOT="$ROOT/native" TMPDIR="$ROOT/native/tmp" "$VPY" scripts/macos_native.py >"$ROOT/logs/native.log" 2>&1 )
  grep -q "native harness ran to completion" "$WRV_RESULTS" || R add "native harness ran to completion" FAIL "no result; see $ROOT/logs/native.log"
  if [ "$OS" = "Darwin" ]; then
    echo "launching the real app (a window will appear briefly; leave the Mac unlocked)..."
    ( cd "$REPO" && WRV_ROOT="$ROOT/app" TMPDIR="$ROOT/app/tmp" "$VPY" scripts/macos_app.py >"$ROOT/logs/app.log" 2>&1 )
  else
    R add "live app: launch, window, PDF export" BLOCKED "Linux selftest cannot launch the macOS desktop shell" --optional
  fi
else
  why="requires macOS"; [ "$TOOLS" = 0 ] && why="tooling not installed"
  R add "native export: WKWebView PDF, PDFKit read-back, approval and block checks" BLOCKED "$why"
  R add "live app: launch, window, PDF export" BLOCKED "$why"
fi

# ---- 6. real data untouched?
AFTER="$(R snapshot-real)"
if [ "$BEFORE" = "$AFTER" ]; then R add "your real app data and reports folders were not modified" PASS "fingerprint unchanged"
else R add "your real app data and reports folders were not modified" FAIL "fingerprint changed (close the real app and re-run; if it still changes, a test is writing outside the sandbox)"; fi

# ---- 7. report
PKG="not built"; APPBIN="${WR_APP_BIN:-$REPO/dist/WorkReceipt.app/Contents/MacOS/WorkReceipt}"
if [ "$OS" = Darwin ] && [ -x "$APPBIN" ]; then PKG="$("$PY" "$REPO/buildinfo.py" check-app "$APPBIN" 2>&1 | head -n 1 | sed 's/:.*//')"; fi
COMMIT="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo '?')"; DIRTY=""; git -C "$REPO" diff --quiet 2>/dev/null || DIRTY="+uncommitted changes"
FP="$("$PY" "$REPO/buildinfo.py" show 2>/dev/null | "$PY" -c "import json,sys; print(json.load(sys.stdin)['fingerprint'][:12])" 2>/dev/null || echo '?')"
VER="$("$PY" -c "import sys; sys.path.insert(0, '$REPO'); import app_core; print(app_core.VERSION)" 2>/dev/null || echo '?')"
MAC="$( [ "$OS" = Darwin ] && echo "macOS $(sw_vers -productVersion) $(uname -m)" || echo "$OS$([ "$SELF" = 1 ] && echo ' (selftest)')")"
R report "$WRV_RESULTS" --out "$REPORT" --header "WorkReceipt v$VER  commit $COMMIT$DIRTY  source ${FP:-?}  packaged app: $PKG  $MAC  $(date '+%Y-%m-%d %H:%M')"
CODE=$?
if [ "$CODE" = 0 ] && [ "$KEEP" = 0 ]; then case "$ROOT" in */wr-validate.*) rm -rf "$ROOT";; esac; else echo "sandbox kept for inspection (synthetic data only): $ROOT"; fi
exit $CODE
