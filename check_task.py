import glob
import json
import os

tasks_dir = os.path.expandvars(r"%APPDATA%\ocr-trigger-clicker\tasks")
files = glob.glob(os.path.join(tasks_dir, "*.json"))
print("Task files:")
for f in files:
    print(" ", os.path.basename(f), "size=", os.path.getsize(f))
    with open(f, "r", encoding="utf-8") as fp:
        d = json.load(fp)
    if "_collapsed_groups" in d:
        print("    _collapsed_groups:", d["_collapsed_groups"])
    else:
        print("    _collapsed_groups: NOT FOUND")
