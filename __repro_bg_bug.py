"""
真實程式碼重現測試：常駐監控規則消失
使用專案實際的 load_rules/save_rules/load_groups/save_groups 與 _persist_collapsed 邏輯
"""

import json
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))

from _loader import load_sibling

rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")

TASK_NAME = "旅程輔助"
tasks_dir = rule_mod.get_tasks_dir()
task_path = tasks_dir / f"{TASK_NAME}.json"
backup_path = Path.home() / "Desktop" / "repro_before.json"

print(f"[任務檔案路徑] {task_path}")
if not task_path.exists():
    print("!! 找不到任務檔，中止")
    sys.exit(1)

shutil.copy(task_path, backup_path)
print(f"[備份完成] {backup_path}")

# ── 場景一：正常路徑（建立規則 -> 設 background=True -> flush_save 等價操作）──
rules = rule_mod.load_rules(str(task_path))
groups = rule_mod.load_groups(str(task_path))
print(f"[場景一 載入] rules={len(rules)}, groups={len(groups)}")

new_rule = rule_mod.Rule(
    id=str(uuid.uuid4()),
    name="__repro_test_rule__",
    enabled=True,
    steps=[],
    background=True,
)
rules.append(new_rule)
# 對應 _on_background_changed: background=True 時要從所有 group.rule_ids 移除（新規則本來就不在任何 group 裡，略過)

ok1 = rule_mod.save_rules(rules, str(task_path))
ok2 = rule_mod.save_groups(groups, str(task_path))
print(f"[場景一 flush_save] save_rules={ok1}, save_groups={ok2}")

# 模擬「重啟」：全新讀取
rules_after = rule_mod.load_rules(str(task_path))
found = next((r for r in rules_after if r.id == new_rule.id), None)
print(
    f"[場景一 重啟後] rules={len(rules_after)}, 新規則存在={found is not None}, background={getattr(found, 'background', None)}"
)


# ── 場景二：_persist_collapsed 競態 ──
# 模擬使用者在「flush_save 尚未觸發」前，展開/折疊了某個群組節點，
# 導致 _persist_collapsed() 被呼叫（它直接讀『目前磁碟上的檔案』，而不是記憶體中的 self._rules）
def simulate_persist_collapsed(task_path, collapsed_ids):
    """完全複製 06_gui_main.py::_persist_collapsed 的邏輯"""
    if task_path.exists():
        with open(task_path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}
    data["_collapsed_groups"] = list(collapsed_ids)
    tmp = task_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(task_path)


# 還原到備份，重新開始場景二
shutil.copy(backup_path, task_path)
rules2 = rule_mod.load_rules(str(task_path))
groups2 = rule_mod.load_groups(str(task_path))
print(f"\n[場景二 還原後載入] rules={len(rules2)}")

new_rule2 = rule_mod.Rule(
    id=str(uuid.uuid4()),
    name="__repro_test_rule_2__",
    enabled=True,
    steps=[],
    background=True,
)
rules2.append(new_rule2)
print("[場景二] 新增規則到記憶體中的 self._rules（尚未 flush_save）")

# 此時「使用者手滑」展開了某個群組節點 → 觸發 _on_rule_item_expanded → _persist_collapsed()
simulate_persist_collapsed(task_path, {"__default__"})
print("[場景二] 觸發 _persist_collapsed()（讀磁碟舊資料 + 寫回，新規則此時尚未落盤）")

# 接著才真正 flush_save（使用者勾選「常駐監控」）
ok1 = rule_mod.save_rules(rules2, str(task_path))
ok2 = rule_mod.save_groups(groups2, str(task_path))
print(f"[場景二 flush_save] save_rules={ok1}, save_groups={ok2}")

rules2_after = rule_mod.load_rules(str(task_path))
found2 = next((r for r in rules2_after if r.id == new_rule2.id), None)
print(
    f"[場景二 重啟後] rules={len(rules2_after)}, 新規則存在={found2 is not None}, background={getattr(found2, 'background', None)}"
)

with open(task_path, encoding="utf-8") as f:
    final_keys = list(json.load(f).keys())
print(f"[場景二 最終檔案 keys] {final_keys}")

# 還原備份，不污染使用者真實任務檔
shutil.copy(backup_path, task_path)
print("\n[已還原原始任務檔]")
