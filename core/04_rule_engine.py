import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from _loader import load_sibling

_ocr_mod = load_sibling("ocr_engine", "core/02_ocr_engine.py")
OcrResult = _ocr_mod.OcrResult
find_text = _ocr_mod.find_text


@dataclass
class Rule:
    id: str
    name: str
    enabled: bool
    target_text: str
    fuzzy: bool
    fuzzy_threshold: float
    roi: dict
    click_position: str
    click_button: str
    cooldown_ms: int
    trigger_mode: str
    max_triggers: int
    random_offset: int
    custom_x: int = 0
    custom_y: int = 0
    trigger_count: int = 0
    last_trigger_time: float = 0.0


_RUNTIME_FIELDS = {"trigger_count", "last_trigger_time"}

_FIELD_DEFAULTS = {
    "fuzzy": False,
    "fuzzy_threshold": 0.8,
    "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
    "click_position": "text_center",
    "click_button": "left",
    "cooldown_ms": 2000,
    "trigger_mode": "once",
    "max_triggers": -1,
    "random_offset": 3,
    "custom_x": 0,
    "custom_y": 0,
}


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sanitize_roi(roi: dict | None) -> dict:
    roi = roi if isinstance(roi, dict) else {}
    return {
        "x": max(0, _as_int(roi.get("x", 0))),
        "y": max(0, _as_int(roi.get("y", 0))),
        "w": max(0, _as_int(roi.get("w", 0))),
        "h": max(0, _as_int(roi.get("h", 0))),
    }


def _dict_to_rule(d: dict) -> Rule:
    merged = {**_FIELD_DEFAULTS, **(d if isinstance(d, dict) else {})}
    return Rule(
        id=str(merged.get("id", "")),
        name=str(merged.get("name", "")),
        enabled=bool(merged.get("enabled", True)),
        target_text=str(merged.get("target_text", "")).strip(),
        fuzzy=bool(merged.get("fuzzy", False)),
        fuzzy_threshold=max(0.0, min(1.0, _as_float(merged.get("fuzzy_threshold", 0.8), 0.8))),
        roi=_sanitize_roi(merged.get("roi")),
        click_position=str(merged.get("click_position", "text_center")),
        click_button=str(merged.get("click_button", "left")),
        cooldown_ms=max(0, _as_int(merged.get("cooldown_ms", 2000), 2000)),
        trigger_mode=str(merged.get("trigger_mode", "once")),
        max_triggers=_as_int(merged.get("max_triggers", -1), -1),
        random_offset=max(0, _as_int(merged.get("random_offset", 3), 3)),
        custom_x=_as_int(merged.get("custom_x", 0), 0),
        custom_y=_as_int(merged.get("custom_y", 0), 0),
    )


def _rule_to_dict(r: Rule) -> dict:
    d = asdict(r)
    for key in _RUNTIME_FIELDS:
        d.pop(key, None)
    return d


def load_rules(path: str) -> list[Rule]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, KeyError):
        return []
    rules: list[Rule] = []
    for raw in data.get("rules", []):
        try:
            rules.append(_dict_to_rule(raw))
        except Exception:
            continue
    return rules


def save_rules(rules: list[Rule], path: str) -> bool:
    try:
        data = {"rules": [_rule_to_dict(r) for r in rules]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def check_trigger(
    rule: Rule,
    ocr_results: list[OcrResult],
) -> tuple[bool, Optional[OcrResult]]:
    if not rule.enabled:
        return False, None
    if not rule.target_text.strip():
        return False, None
    elapsed_ms = (time.monotonic() - rule.last_trigger_time) * 1000
    if elapsed_ms < rule.cooldown_ms:
        return False, None
    if rule.trigger_mode == "once" and rule.trigger_count > 0:
        return False, None
    if rule.max_triggers > 0 and rule.trigger_count >= rule.max_triggers:
        return False, None
    matches = find_text(ocr_results, rule.target_text, rule.fuzzy, rule.fuzzy_threshold)
    if not matches:
        return False, None
    return True, matches[0]


def apply_trigger(rule: Rule) -> dict:
    rule.trigger_count += 1
    rule.last_trigger_time = time.monotonic()
    if 0 < rule.max_triggers <= rule.trigger_count:
        rule.enabled = False
    off = rule.random_offset
    dx = random.randint(-off, off) if off else 0
    dy = random.randint(-off, off) if off else 0
    return {"x": rule.custom_x + dx, "y": rule.custom_y + dy, "button": rule.click_button}


def get_roi(rule: Rule) -> Optional[dict]:
    if all(rule.roi.get(k, 0) == 0 for k in ("x", "y", "w", "h")):
        return None
    return dict(rule.roi)


# ── Task management ──

def _tasks_base() -> Path:
    try:
        from build import get_data_path
        raw = get_data_path("_")
        return Path(raw).parent
    except ImportError:
        return Path(__file__).resolve().parent.parent


def get_tasks_dir() -> Path:
    tasks_dir = _tasks_base() / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    return tasks_dir


def list_tasks() -> list[str]:
    names = []
    for f in sorted(get_tasks_dir().glob("*.json")):
        if f.stem:
            names.append(f.stem)
    return names


def load_task(name: str) -> list[Rule]:
    return load_rules(str(get_tasks_dir() / f"{name}.json"))


def save_task(name: str, rules: list[Rule]) -> bool:
    return save_rules(rules, str(get_tasks_dir() / f"{name}.json"))


def delete_task(name: str) -> bool:
    try:
        (get_tasks_dir() / f"{name}.json").unlink(missing_ok=True)
        return True
    except OSError:
        return False


def rename_task(old_name: str, new_name: str) -> bool:
    old_p = get_tasks_dir() / f"{old_name}.json"
    new_p = get_tasks_dir() / f"{new_name}.json"
    if new_p.exists():
        return False
    try:
        old_p.rename(new_p)
        return True
    except OSError:
        return False


def export_task(name: str, dest_path: str) -> bool:
    src = get_tasks_dir() / f"{name}.json"
    if not src.exists():
        return False
    try:
        import shutil
        shutil.copy2(str(src), dest_path)
        return True
    except OSError:
        return False


def import_task(src_path: str) -> Optional[str]:
    src = Path(src_path)
    if not src.exists():
        return None
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "rules" not in data:
            return None
    except (json.JSONDecodeError, OSError):
        return None
    name = src.stem
    dest = get_tasks_dir() / f"{name}.json"
    suffix = 1
    while dest.exists():
        dest = get_tasks_dir() / f"{name}_{suffix}.json"
        suffix += 1
    try:
        dest.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return dest.stem
    except OSError:
        return None


def migrate_old_rules():
    if any(get_tasks_dir().iterdir()):
        return
    try:
        from build import get_data_path
        old_path = Path(get_data_path("rules.json"))
    except ImportError:
        old_path = _tasks_base() / "rules.json"
    if old_path.exists():
        rules = load_rules(str(old_path))
        save_task("預設任務", rules)


if __name__ == "__main__":
    json_path = str(Path(__file__).resolve().parent.parent / "rules.json")

    test_rules = [
        Rule(
            id="rule_001",
            name="確認按鈕",
            enabled=True,
            target_text="確認",
            fuzzy=False,
            fuzzy_threshold=0.8,
            roi={"x": 100, "y": 200, "w": 300, "h": 100},
            click_position="text_center",
            click_button="left",
            cooldown_ms=2000,
            trigger_mode="once",
            max_triggers=-1,
            random_offset=3,
        ),
        Rule(
            id="rule_002",
            name="按按鈕",
            enabled=True,
            target_text="確認",
            fuzzy=False,
            fuzzy_threshold=0.8,
            roi={"x": 0, "y": 0, "w": 0, "h": 0},
            click_position="custom",
            click_button="right",
            cooldown_ms=0,
            trigger_mode="repeat",
            max_triggers=2,
            random_offset=0,
            custom_x=500,
            custom_y=600,
        ),
    ]

    save_rules(test_rules, json_path)
    print(f"已寫入 {json_path}")

    loaded = load_rules(json_path)
    print(f"\n=== 載入 {len(loaded)} 條規則 ===")
    for r in loaded:
        print(
            f"  [{r.id}] {r.name}  enabled={r.enabled}  target={r.target_text!r}  "
            f"fuzzy={r.fuzzy}  roi={r.roi}  click={r.click_position}  "
            f"mode={r.trigger_mode}  max={r.max_triggers}  "
            f"cooldown={r.cooldown_ms}ms  offset={r.random_offset}"
        )

    fake_results = [
        OcrResult(text="取消", x=10, y=10, w=50, h=20, confidence=0.95),
        OcrResult(text="確認", x=100, y=200, w=50, h=20, confidence=0.98),
        OcrResult(text="關閉視窗", x=300, y=400, w=80, h=20, confidence=0.90),
    ]

    rule_a = loaded[0]
    print(f"\n=== check_trigger 測試 (rule: {rule_a.name}) ===")
    for i in range(3):
        hit, ocr = check_trigger(rule_a, fake_results)
        if hit:
            params = apply_trigger(rule_a)
            print(
                f"  第 {i + 1} 次: 觸發 → {params}  "
                f"count={rule_a.trigger_count}  enabled={rule_a.enabled}"
            )
        else:
            reason = "冷卻中" if rule_a.enabled else "已停用"
            print(
                f"  第 {i + 1} 次: 未觸發 ({reason})  "
                f"count={rule_a.trigger_count}  enabled={rule_a.enabled}"
            )

    rule_b = loaded[1]
    print(f"\n=== max_triggers 測試 (rule: {rule_b.name}, max={rule_b.max_triggers}) ===")
    for i in range(3):
        hit, ocr = check_trigger(rule_b, fake_results)
        if hit:
            params = apply_trigger(rule_b)
            print(
                f"  第 {i + 1} 次: 觸發 → {params}  "
                f"count={rule_b.trigger_count}  enabled={rule_b.enabled}"
            )
        else:
            reason = "已停用 (達上限)" if not rule_b.enabled else "冷卻中"
            print(
                f"  第 {i + 1} 次: 未觸發 ({reason})  "
                f"count={rule_b.trigger_count}  enabled={rule_b.enabled}"
            )

    ok = save_rules(loaded, json_path)
    print(f"\n儲存結果: {'成功' if ok else '失敗'}")
    with open(json_path, encoding="utf-8") as f:
        saved_content = json.load(f)
    print("JSON 內容:")
    print(json.dumps(saved_content, indent=2, ensure_ascii=False))

    trigger_count_in_json = any("trigger_count" in r for r in saved_content["rules"])
    print(f"\nJSON 包含 trigger_count: {trigger_count_in_json} (應為 False)")

    print("\nROI 測試:")
    print(f"  rule_001 ROI: {get_roi(rule_a)} (應非 None)")
    print(f"  rule_002 ROI: {get_roi(rule_b)} (應為 None)")
