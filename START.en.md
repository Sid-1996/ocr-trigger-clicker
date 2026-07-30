# OCR Trigger Clicker Quick Start

Not a manual. The shortest path from download to running.

---

## Path A: Import a task and go

Someone already made a task file (JSON). You just load it and run.

### ① Download the tool

[GitHub Releases](https://github.com/Sid-1996/ocr-trigger-clicker/releases) → download `ocr-trigger-clicker.zip`

Extract it, run `ocr-trigger-clicker.exe`

> If your target app runs as Administrator (most games do), **right-click → Run as Administrator** on this exe too, or clicks won't register.

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

### ④ Start

Click "Start" → check the groups you want → go.

For detailed tutorials, see the [documentation site](https://sid-1996.github.io/ocr-trigger-clicker/).

---

## FAQ

### Nothing happens when I start?

Most common cause: **not running as Administrator**. Games usually run with admin rights; the tool needs the same level to send clicks. Close it, right-click → Run as Administrator.

### My resolution isn't 1920×1080?

Ratio coordinates auto-adapt to different resolutions, but ROI positions may need tweaking. Use "OCR Diagnostic" to check whether text is being detected.

### Where are task files stored?

`%APPDATA%\ocr-trigger-clicker\` — delete the exe and your settings stay.

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
