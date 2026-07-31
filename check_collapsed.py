import json
import os

tasks_dir = os.path.expandvars(r"%APPDATA%\ocr-trigger-clicker\tasks")
path = os.path.join(tasks_dir, "StarSavior-每日任務.json")

with open(path, "r", encoding="utf-8") as f:
    d = json.load(f)

groups = d.get("groups", [])
collapsed = set(d.get("_collapsed_groups", []))
print(f"groups count: {len(groups)}")
print(f"collapsed count: {len(collapsed)}")
print()
print("=== 群組順序與摺疊狀態 ===")
for i, g in enumerate(groups):
    gid = g.get("id", "")
    name = g.get("name", "")
    status = "COLLAPSED" if gid in collapsed else "EXPANDED"
    print(f"{i:2d}. {gid:20s} {name:30s} {status}")

print()
print("=== collapsed 中但不在 groups 的 ID ===")
for gid in collapsed:
    if not any(g.get("id") == gid for g in groups):
        print(f"  {gid}")

print()
print("=== groups 中但不在 collapsed 的 ID ===")
for g in groups:
    if g.get("id") not in collapsed:
        print(f"  {g.get('id')}")
