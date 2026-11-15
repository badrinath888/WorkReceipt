#!/bin/bash
# Build WorkReceipt.app and .dmg. Run on macOS (Apple Silicon). Unsigned unless SIGN_ID is set.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .build-venv && source .build-venv/bin/activate
pip install -q pywebview pyinstaller
pyinstaller --noconfirm --windowed --name WorkReceipt --osx-bundle-identifier app.workreceipt \
  --add-data "ui:ui" --add-data "examples/make_demo_workspace.py:examples" desktop/main.py
[ -n "${SIGN_ID:-}" ] && codesign --deep --force --options runtime --sign "$SIGN_ID" dist/WorkReceipt.app
hdiutil create -volname WorkReceipt -srcfolder dist/WorkReceipt.app -ov -format UDZO dist/WorkReceipt.dmg
echo "Built dist/WorkReceipt.dmg (notarization: not done; needs Apple Developer ID)"
