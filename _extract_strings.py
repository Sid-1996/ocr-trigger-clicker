"""一次性腳本：提取所有 GUI 檔案中的中文字串，輸出為 JSON。"""

import json
import re
from pathlib import Path

files = [
    "gui/06_gui_main.py",
    "gui/09_ocr_debug.py",
    "gui/group_settings_controller.py",
    "gui/07_gui_roi.py",
    "gui/13_gui_click_picker.py",
    "gui/14_capture_region.py",
    "gui/screenshot_controller.py",
]

CJK = re.compile(r"[\u4e00-\u9fff]")

# Match strings: triple-quoted, double-quoted, single-quoted
STR = re.compile(
    r'"""(.*?)"""|\'\'\'(.*?)\'\'\'|"([^"]*)"|\'([^\']*)\'',
    re.DOTALL,
)

results = {}
for f in files:
    path = Path(f)
    if not path.exists():
        continue
    content = path.read_text(encoding="utf-8")
    strings = set()
    for m in STR.finditer(content):
        s = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        if s and CJK.search(s) and len(s.strip()) > 0:
            strings.add(s.strip())
    results[f] = sorted(strings)

# Output as JSON for easy processing
print(json.dumps(results, ensure_ascii=False, indent=2))
