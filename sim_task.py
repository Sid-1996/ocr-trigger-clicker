"""任務模擬器：用隨機切換的實境截圖驅動真實規則引擎，蒐集可靠數據。

與 `tests/` 的整合測試不同——那些只斷言「優化路徑等價」；本工具是**真的跑規則**：
載入任務 JSON（預設 `tests/data/fixture_task.json`，StarSavior-跑馬輔助快照），
以固定 seed 隨機抽幀餵給 `MainLoop._process_rules()`，動作只計數不執行，
最後輸出每幀耗時、OCR 成本、每規則命中／未命中／未評估清單。

- 不開 GUI、不碰真視窗與滑鼠：MainLoop 由 `tests/conftest.py::make_main_loop()` 提供
  （動作函式已 stub），本檔再把 `_send_click/_send_key/_send_scroll/_activate_window`
  換成計數器。
- 同 seed → 同幀序 → 數據可重現（這是「可靠」的前提）；換 seed 可換一組抽樣。

用法：
    uv run python sim_task.py                          # 20 幀、核心 4 幀、seed 1
    uv run python sim_task.py --frames 120 --seed 7 --full
    uv run python sim_task.py --task "%APPDATA%/ocr-trigger-clicker/tasks/StarSavior-跑馬輔助.json"
    uv run python sim_task.py --out sim.json           # 另存統計供跨版本比較
    uv run python sim_task.py --self-check             # 只驗統計邏輯（不載模型，秒回）
"""

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for _p in (_ROOT, _ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cv2  # noqa: E402


class _TimeShim:
    """主循環模組專用的 time 代理：sleep 只累計不真的等。"""

    def __init__(self, real):
        self._real = real
        self.sleep_ms = 0.0

    def sleep(self, seconds):
        self.sleep_ms += float(seconds) * 1000.0

    def __getattr__(self, name):
        return getattr(self._real, name)


class _FakeEvent:
    """替代 _stop_event：wait() 立即返回，只累計被略過的等待毫秒。"""

    def __init__(self):
        self._set = False
        self.waited_ms = 0.0

    def set(self):
        self._set = True

    def clear(self):
        self._set = False

    def is_set(self):
        return self._set

    def wait(self, timeout=None):
        self.waited_ms += float(timeout or 0) * 1000.0
        return self._set


def _percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _summarize(frames_ms, ocr_calls, ocr_ms, rule_stats, actions, waits_ms, cycles) -> dict:
    evaluated = [s for s in rule_stats.values() if s["frames"] > 0]
    steady = frames_ms[1:]  # 首幀含 OCR 模型暖機，與實機跑分對齊時應排除
    name_counts = Counter(s["name"] for s in rule_stats.values())

    def _label(stat):
        if name_counts[stat["name"]] == 1:
            return stat["name"]
        return f"{stat['name']} [{stat['id'][-4:]}]"  # 同名規則以 id 後 4 碼區分

    return {
        "frames": len(frames_ms),
        "frame_ms": {
            "avg": round(sum(frames_ms) / len(frames_ms), 1) if frames_ms else 0.0,
            "steady_avg": round(sum(steady) / len(steady), 1) if steady else 0.0,
            "p50": round(_percentile(frames_ms, 0.5), 1),
            "p95": round(_percentile(frames_ms, 0.95), 1),
            "max": round(max(frames_ms), 1) if frames_ms else 0.0,
        },
        "frames_ms": [round(v, 1) for v in frames_ms],
        "ocr": {
            "calls": sum(ocr_calls),
            "calls_per_frame": round(sum(ocr_calls) / len(ocr_calls), 2) if ocr_calls else 0.0,
            "ms": round(sum(ocr_ms), 1),
            "ms_per_frame": round(sum(ocr_ms) / len(ocr_ms), 1) if ocr_ms else 0.0,
        },
        "actions": dict(actions),
        "skipped_wait_ms": round(waits_ms, 1),
        "group_cycles": cycles,
        "rules": {
            _label(s): {
                "id": s["id"],
                "frames": s["frames"],
                "triggered": s["triggered"],
                "jumped": s["jumped"],
                "ms_per_frame": round(s["ms"] / s["frames"], 2) if s["frames"] else 0.0,
                "last_step": s["last_step"],
            }
            for s in sorted(rule_stats.values(), key=lambda x: (-x["triggered"], -x["frames"]))
        },
        "never_triggered": [_label(s) for s in evaluated if s["triggered"] == 0],
        "never_evaluated": [_label(s) for s in rule_stats.values() if s["frames"] == 0],
    }


def _format_report(title: str, seed: int, pool, stats: dict) -> str:
    fm = stats["frame_ms"]
    ocr = stats["ocr"]
    lines = [
        f"== 任務模擬：{title} ==",
        f"seed {seed}｜幀 {stats['frames']}｜幀池 {len(pool)} 張：{', '.join(pool)}",
        f"幀耗 ms：穩態平均 {fm['steady_avg']}（已排除首幀模型暖機 {stats['frames_ms'][0]}）"
        f"｜p50 {fm['p50']}｜p95 {fm['p95']}｜最大 {fm['max']}",
        f"OCR：{ocr['calls_per_frame']} 次/幀、{ocr['ms_per_frame']} ms/幀（共 {ocr['calls']} 次）",
        "動作（攔截未執行）："
        + "、".join(f"{k} {v}" for k, v in sorted(stats["actions"].items()))
        + f"｜已略過等待 {stats['skipped_wait_ms']} ms",
        f"群組：啟用 {stats['groups']['enabled']}/{stats['groups']['total']}"
        + ("（全部 loop+parallel，每幀全跑）" if stats["groups"]["all_loop_parallel"] else "")
        + (f"｜佇列重跑 {stats['group_cycles']} 輪" if stats["group_cycles"] else ""),
        "",
        "規則（依命中次數）：",
    ]
    for name, r in stats["rules"].items():
        if r["frames"] == 0:
            continue
        lines.append(
            f"  {name:<28} 評估 {r['frames']:>4} 幀｜命中 {r['triggered']:>4}"
            f"｜jump {r['jumped']:>3}｜{r['ms_per_frame']} ms/幀"
        )
    if stats["never_triggered"]:
        lines.append("")
        lines.append(
            f"從未命中（{len(stats['never_triggered'])}）：" + "、".join(stats["never_triggered"])
        )
    if stats["never_evaluated"]:
        lines.append("")
        lines.append(
            f"從未被評估（被前面規則擋住，{len(stats['never_evaluated'])}）："
            + "、".join(stats["never_evaluated"])
        )
    return "\n".join(lines)


def _self_check():
    assert _percentile([], 0.5) == 0.0
    assert _percentile([100.0, 200.0, 300.0], 0.5) == 200.0
    assert abs(_percentile(list(range(1, 11)), 0.95) - 9.55) < 1e-9

    rule_stats = {
        "a": {
            "id": "rid-a",
            "name": "hit",
            "frames": 4,
            "triggered": 2,
            "jumped": 0,
            "ms": 40.0,
            "last_step": 1,
        },
        "b": {
            "id": "rid-b",
            "name": "miss",
            "frames": 4,
            "triggered": 0,
            "jumped": 1,
            "ms": 20.0,
            "last_step": 0,
        },
        "c": {
            "id": "rid-c",
            "name": "blocked",
            "frames": 0,
            "triggered": 0,
            "jumped": 0,
            "ms": 0.0,
            "last_step": -1,
        },
        "d": {
            "id": "rid-d4",
            "name": "miss",
            "frames": 2,
            "triggered": 1,
            "jumped": 0,
            "ms": 10.0,
            "last_step": 0,
        },
    }
    stats = _summarize(
        [100.0, 200.0, 300.0], [2, 3, 3], [5.0, 7.0, 9.0], rule_stats, {"click": 2}, 1500.0, 1
    )
    assert stats["frame_ms"] == {
        "avg": 200.0,
        "steady_avg": 250.0,
        "p50": 200.0,
        "p95": 290.0,
        "max": 300.0,
    }
    assert stats["frames_ms"] == [100.0, 200.0, 300.0]
    assert stats["ocr"]["calls_per_frame"] == 2.67 and stats["ocr"]["ms"] == 21.0
    assert list(stats["rules"]) == ["hit", "miss [d-d4]", "miss [id-b]", "blocked"], (
        "命中的排前面；同名規則以 id 後 4 碼區分"
    )
    assert stats["rules"]["hit"]["ms_per_frame"] == 10.0
    assert stats["never_evaluated"] == ["blocked"]
    assert "miss [id-b]" in stats["never_triggered"], "同名規則要用 id 後 4 碼區分"
    stats["groups"] = {"enabled": 4, "total": 5, "all_loop_parallel": True}
    text = _format_report("demo", 3, ["test.png"], stats)
    assert "hit" in text and "blocked" not in text.split("從未被評估")[0].split("規則")[-1]
    assert "從未命中（1）" in text and "從未被評估（被前面規則擋住，1）" in text
    print("self-check OK")


def _build_loop(task_path: Path, counts: dict, rule_stats: dict):
    from conftest import make_main_loop

    from _loader import load_sibling

    ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
    ml = make_main_loop()
    ml._rules_path = str(task_path)
    ml._load_rules()
    if not ml._rules:
        raise SystemExit(f"任務沒有規則：{task_path}")

    ml_mod.time = _TimeShim(time)
    ml._stop_event = _FakeEvent()

    def _counted(key, fn):
        def wrapper(*args, **kwargs):
            counts[key] = counts.get(key, 0) + 1
            return fn(*args, **kwargs)

        return wrapper

    ml._send_click = _counted("click", ml._send_click)
    ml._send_key = _counted("key", ml._send_key)
    ml._send_scroll = _counted("scroll", ml._send_scroll)
    ml._activate_window = _counted("activate", ml._activate_window)

    original_run_rule = ml._run_rule

    def _run_rule_spy(rule, img, rect, ctx=None, background=False):
        started = time.perf_counter()
        original_run_rule(rule, img, rect, ctx, background=background)
        stat = rule_stats.setdefault(
            rule.id,
            {
                "id": rule.id,
                "name": rule.name,
                "frames": 0,
                "triggered": 0,
                "jumped": 0,
                "ms": 0.0,
                "last_step": -1,
            },
        )
        stat["frames"] += 1
        stat["ms"] += (time.perf_counter() - started) * 1000.0
        stat["last_step"] = ctx.step_idx if ctx is not None else -1
        if ctx is not None and ctx.triggered:
            stat["triggered"] += 1
        if ctx is not None and ctx.jumped:
            stat["jumped"] += 1

    ml._run_rule = _run_rule_spy
    for rule in ml._rules:
        rule_stats.setdefault(
            rule.id,
            {
                "id": rule.id,
                "name": rule.name,
                "frames": 0,
                "triggered": 0,
                "jumped": 0,
                "ms": 0.0,
                "last_step": -1,
            },
        )
    return ml, ml_mod


def _load_frame(data_dir: Path, name: str):
    img = cv2.imread(str(data_dir / name))
    if img is None:
        raise SystemExit(f"讀不到截圖（檔名需為 ASCII）：{data_dir / name}")
    return img


def main():
    from data_frames import ALL_FRAMES, CORE_FRAMES

    parser = argparse.ArgumentParser(description="以隨機實境幀驅動任務，蒐集可靠數據")
    parser.add_argument("--task", default=str(_ROOT / "tests/data/fixture_task.json"))
    parser.add_argument("--frames", type=int, default=20, help="模擬幀數（預設 20）")
    parser.add_argument("--seed", type=int, default=1, help="隨機種子（同 seed 可重現）")
    parser.add_argument("--full", action="store_true", help="用全部實境幀（預設核心 4 幀）")
    parser.add_argument("--data-dir", default=str(_ROOT / "tests/data"))
    parser.add_argument("--out", default="", help="另存 JSON 統計")
    parser.add_argument("--self-check", action="store_true", help="只驗統計邏輯後結束")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return

    if hasattr(sys.stdout, "reconfigure"):  # 管線/重導向時仍輸出 UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    task_path = Path(args.task)
    if not task_path.exists():
        raise SystemExit(f"找不到任務檔：{task_path}")
    data_dir = Path(args.data_dir)
    pool = list(ALL_FRAMES if args.full else CORE_FRAMES)
    images = {name: _load_frame(data_dir, name) for name in pool}

    counts: dict = {}
    rule_stats: dict = {}
    ml, ml_mod = _build_loop(task_path, counts, rule_stats)
    active = [g.id for g in ml._groups if g.enabled]
    if not active:
        raise SystemExit("任務沒有啟用的群組（模擬需要至少一個）")
    ml.set_active_groups(active)

    rng = random.Random(args.seed)
    sequence = [rng.choice(pool) for _ in range(args.frames)]

    frames_ms, ocr_calls, ocr_ms = [], [], []
    cycles = 0
    rect = {"x": 0, "y": 0, "w": images[pool[0]].shape[1], "h": images[pool[0]].shape[0]}
    last_queue_idx = ml._group_queue_idx
    for name in sequence:
        # 佇列型群組（once/repeat/sequential）跑完一輪 = 一局結束 → 重啟再跑（模擬下一局）；
        # loop+parallel 群組不用佇列（set_active_groups 後 idx 就等於長度），此處不會誤計。
        if last_queue_idx < len(active) <= ml._group_queue_idx:
            ml.set_active_groups(active)
            cycles += 1
        last_queue_idx = ml._group_queue_idx
        started = time.perf_counter()
        ml._process_rules(images[name], dict(rect))
        frames_ms.append((time.perf_counter() - started) * 1000.0)
        profile = getattr(ml, "_frame_ocr_profile", None) or {"calls": 0, "ms": 0.0}
        ocr_calls.append(profile["calls"])
        ocr_ms.append(profile["ms"])

    waits_ms = ml_mod.time.sleep_ms + ml._stop_event.waited_ms
    stats = _summarize(frames_ms, ocr_calls, ocr_ms, rule_stats, counts, waits_ms, cycles)
    stats["task"] = str(task_path)
    stats["seed"] = args.seed
    stats["frame_pool"] = pool
    stats["groups"] = {
        "enabled": len(active),
        "total": len(ml._groups),
        "all_loop_parallel": all(
            g.mode == "loop" and g.order == "parallel" for g in ml._groups if g.enabled
        ),
    }
    stats["group_rounds"] = dict(ml._group_rounds_completed)
    report = _format_report(task_path.name, args.seed, pool, stats)
    print(report)
    if args.out:
        Path(args.out).write_text(
            json.dumps({"sequence": sequence, **stats}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n統計已寫入 {args.out}")


if __name__ == "__main__":
    main()
