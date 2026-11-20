# macOS menu-bar widget (v0.8.0)

Opt-in (Settings > Menu bar). Shows counts only for the projects you explicitly select: new Git commits since you last marked them seen, recent sessions, findings waiting for review, and the last export date.
- Never shows source code, prompts, commit text, paths or secrets, in the menu or in notifications. Project names are hidden ("Project 1") unless you turn on "Show project folder names".
- Notifications are generic ("2 new commits in your selected projects") and off by default.
- "Generate Report…" opens Report Studio, so privacy review and Client-Safe approval still apply; the widget never exports on its own.
- Everything is local; nothing is uploaded. Logic: `menubar.py` (tested). AppKit shell: `desktop/menubar_mac.py`.
