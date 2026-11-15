#!/bin/bash
# Reproducible macOS build: dist/WorkReceipt.app and dist/WorkReceipt-<version>.dmg. Run on a Mac (Apple Silicon builds arm64).
# Unsigned by default. Optional, supplied via environment, never stored in the repo:
#   SIGN_IDENTITY="Developer ID Application: Name (TEAMID)"   -> codesign with hardened runtime
#   NOTARY_PROFILE=<name from: xcrun notarytool store-credentials>   -> notarize + staple (needs SIGN_IDENTITY)
set -euo pipefail
[ "$(uname)" = "Darwin" ] || { echo "error: build on macOS" >&2; exit 1; }
cd "$(dirname "$0")/.."
VERSION=$(python3 -c "import app_core; print(app_core.VERSION)")
python3 -m venv .build-venv && source .build-venv/bin/activate
pip install -q -r desktop/requirements-build.txt
# icon: PNG -> .icns (sips + iconutil are part of macOS)
ICONSET=desktop/icon/WorkReceipt.iconset; rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s desktop/icon/icon_1024.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) desktop/icon/icon_1024.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o desktop/icon/WorkReceipt.icns
rm -rf build dist
pyinstaller --noconfirm --clean desktop/WorkReceipt.spec
APP=dist/WorkReceipt.app
if [ -n "${SIGN_IDENTITY:-}" ]; then
  codesign --force --deep --timestamp --options runtime --entitlements desktop/entitlements.plist --sign "$SIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict "$APP"
else
  echo "NOTE: unsigned build. Gatekeeper will warn; open with right-click > Open. Not for distribution."
fi
STAGE=$(mktemp -d); cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
DMG="dist/WorkReceipt-$VERSION.dmg"
hdiutil create -volname "WorkReceipt $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"; rm -rf "$STAGE"
if [ -n "${SIGN_IDENTITY:-}" ]; then codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG"; fi
if [ -n "${NOTARY_PROFILE:-}" ] && [ -n "${SIGN_IDENTITY:-}" ]; then
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"; xcrun stapler validate "$DMG"
  echo "Notarized and stapled: $DMG"
else
  echo "NOT notarized."
fi
shasum -a 256 "$DMG" | tee "$DMG.sha256"
echo "Built $DMG"
