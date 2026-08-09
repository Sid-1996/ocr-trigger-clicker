# OCR Trigger Clicker Quick Start

Not a manual. The shortest path from download to running.

---

## Path A: Import a task and go

Someone already made a task file (JSON). You just load it and run.

### ① Download the tool

[GitHub Releases](https://github.com/Sid-1996/ocr-trigger-clicker/releases) → download `ocr-trigger-clicker.zip`

Extract it, run `ocr-trigger-clicker.exe`

> Usually it works fine without admin rights. If nothing happens when the tool runs, try **right-click → Run as Administrator**.

### ② Download a task

Available tasks (Discussions):

- [StarSavior Daily Quests](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/1)
- [StarSavior Racing Assist](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/1)

Save the `.json` file somewhere on your PC.

### ③ Import + start

The tool looks like this when opened:

![Main UI](docs/images/gui-main.png)

Find these on screen:

1. **Toolbar → Import Task** — pick the JSON you downloaded
2. **Dropdown** — select the game window you want to control (e.g. StarSavior)
3. **Group list** — check which groups you want to run
4. **"Start" button** — click it and you're off

---

## Path B: Create your own rules

Want to build your own automation from scratch? Four steps:

### ① Download the tool

Same as above — [download ZIP](https://github.com/Sid-1996/ocr-trigger-clicker/releases) → extract → run exe

### ② Meet the UI

- **Left panel** = group list (your workflow outline)
- **Right panel** = rule editor (details of each step)
- **Toolbar** = import/export, start/stop, OCR diagnostic

### ③ Create your first rule

1. Right-click → New Group (name it "test")
2. Right-click the group → New Rule
3. Add a step: choose "**detect**" → enter the text to find
4. Add another step: choose "**click**" → pick where to click
5. Hit "▶Test" to verify it works

> 💡 **Fastest way:** open "OCR Diagnostic" to see every text found on screen, find your target, click "Create as new rule" — detection text and position are filled in automatically. You only need to add the action.

### ④ Start

Click "Start" → check the groups you want → go.

For detailed tutorials, see the [documentation site](https://sid-1996.github.io/ocr-trigger-clicker/).

---

## Share your tasks

Once you've built and tested a task, share it with others:

Click **Export Task** in the toolbar → save as JSON → post it in the [Task file sharing category](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/%E4%BB%BB%E5%8B%99%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB). Others download it, click **Import Task**, and it loads instantly — coordinates auto-adapt to any resolution.

> The exported JSON is a plain-text file and contains no personal settings or data.

---

## FAQ

### Nothing happens when I start?

First check: is the right window selected? Is the tool actually running? If both are fine, try **right-click → Run as Administrator** and start again.

### My resolution isn't 1920×1080?

Ratio coordinates auto-adapt to different resolutions, but ROI positions may need tweaking. Use "OCR Diagnostic" to check whether text is being detected.

### Where are task files stored?

`%APPDATA%\ocr-trigger-clicker\` — delete the exe and your settings stay.

### Background capture is black / background mode doesn't work?

Black screenshot → restart the tool **as Administrator** (right-click → Run as Administrator). Most Unity games don't support background control (a game-engine limitation, not a tool issue) — switch back to foreground mode.

### More questions?

→ [Full FAQ](https://sid-1996.github.io/ocr-trigger-clicker/#faq)
→ [GitHub Discussions](https://github.com/Sid-1996/ocr-trigger-clicker/discussions)

---

## Quick Links

| Item | URL |
|---|---|
| Download | https://github.com/Sid-1996/ocr-trigger-clicker/releases |
| Documentation | https://sid-1996.github.io/ocr-trigger-clicker/ |
| Task Sharing | https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/任務檔案分享 |
| Bug Reports | https://github.com/Sid-1996/ocr-trigger-clicker/issues |
