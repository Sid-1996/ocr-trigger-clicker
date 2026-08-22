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

## Path C: Record actions

Don't want to set up rules one by one? Record once and the tool converts it into rules automatically.

> 🎬 Want to see it in action? [Watch the recording demo video](https://www.dailymotion.com/video/xaxgcfq).

### ① Prepare

1. Select the target window
2. Click the "**Record actions**" button (or press **F9**) to start recording

> Recording doesn't steal focus — keep using the game window normally while recording.

### ② Demonstrate once

Click through the actions in the game as you normally would. The tool records every click's position and mouse button (left / right / middle).

> ⚠️ **Note: only mouse clicks are recorded.** Keyboard keys, drags, and scroll wheel are not captured — if you want to wait for the screen to change, just slow down your clicking instead of pressing keys.

> 💡 **Recording tips**: aim your clicks at **UI text** or **icons / buttons** that have recognizable features — the conversion quality is best there; avoid clicking empty areas (they can only become fixed-wait clicks, which drift out of position after a resolution change).

### ③ Stop → convert into a task

1. Press F9 again (or click "Stop") to finish recording
2. Choose whether to **create a new task** or **merge into an existing task** (each recording segment becomes one group)
3. Click "Start" to run it

> 💡 Clicks on text become "wait for text to appear, then click"; clicks with no text underneath try icon matching; otherwise they become a fixed wait then click. Coordinates are always stored as window ratios, so switching between same-aspect-ratio (16:9) resolutions needs no re-configuring; a different aspect ratio requires re-framing the regions.

---

## Share your tasks

Once you've built and tested a task, share it with others:

Click **Export Task** in the toolbar → save as JSON → post it in the [Task file sharing category](https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/%E4%BB%BB%E5%8B%99%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB) (mention the source resolution). Others download it, click **Import Task**, and it loads instantly — coordinates auto-adapt between same-aspect-ratio (16:9) resolutions.

> The exported JSON is a plain-text file and contains no personal settings or data.

---

## FAQ

### Nothing happens when I start?

First check: is the right window selected? Is the tool actually running? If both are fine, try **right-click → Run as Administrator** and start again.

### My resolution isn't 1920×1080?

Ratio coordinates auto-adapt between same-aspect-ratio (16:9) resolutions — for example 1920×1080 and 1600×900 work interchangeably with no re-configuring. A different aspect ratio re-layouts the game UI, shifting ROI / click positions, so re-frame them. Image matching (match_image) only scales templates within about 0.5–2×, so very large resolution gaps may fail; text detection (OCR) has no such limit. Use "OCR Diagnostic" to confirm text is being detected.

### Where are task files stored?

`%APPDATA%\ocr-trigger-clicker\` — delete the exe and your settings stay.

### Background capture is black / background mode doesn't work?

Black screenshot → restart the tool **as Administrator** (right-click → Run as Administrator). Most Unity games don't support background control (a game-engine limitation, not a tool issue) — in that case try **Hybrid mode**: detection runs on background captures with zero disturbance, and only when a click / key is needed does the tool briefly bring the game to the foreground and restore your previous window and mouse position afterwards. Great for low-frequency idle tasks; for frequent actions, plain foreground mode is smoother.

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
