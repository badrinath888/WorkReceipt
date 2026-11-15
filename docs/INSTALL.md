# Installing WorkReceipt (macOS, Apple Silicon)

1. Open `WorkReceipt-<version>.dmg`, drag **WorkReceipt** to **Applications**.
2. First launch: if the build is not notarized, macOS will warn. Right-click the app, choose **Open**, then **Open** again. (Notarized releases open normally.)
3. Git must be available: if you have never used developer tools, macOS offers to install the Command Line Tools the first time; accept it.
4. Pick a project folder (or try the demo). Allow access to the folder if macOS asks.

No Python, Terminal or Chrome is needed. Reports are saved to `~/Documents/WorkReceipt Reports`; settings and history live in `~/Library/Application Support/WorkReceipt`. Everything stays on your Mac. To update: install the new DMG over the old app. To uninstall: delete the app and those two folders.

Shortcuts: ⌘1–5 screens, ⌘, Settings, ⌘O Add Project, ⌘R Refresh, ⌘P Preview, ⌘E Export.

## Building (maintainers)
`./desktop/build_macos.sh` on a Mac. Optional env: `SIGN_IDENTITY` (Developer ID Application) and `NOTARY_PROFILE` (from `xcrun notarytool store-credentials`). Nothing secret is stored in the repo. Without them the output is an unsigned development build.
