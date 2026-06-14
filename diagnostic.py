import importlib.util
import sys
import time
from pathlib import Path

_here = Path(__file__).parent
_results: list[tuple[int, str, list[tuple[bool, str]]]] = []
_start_time = time.time()


def _import(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _check(result: bool, msg: str) -> tuple[bool, str]:
    return (result, msg)


def _import_package(name: str):
    try:
        __import__(name)
        return _check(True, f"{name} 已安裝")
    except ImportError:
        return _check(False, f"{name} 未安裝 → pip install {name}")


def step1_python() -> list[tuple[bool, str]]:
    items = []
    v = sys.version_info
    items.append(
        _check(v.major == 3 and v.minor >= 10, f"Python {v.major}.{v.minor}.{v.micro} (需要 3.10+)")
    )
    for pkg in ["mss", "pygetwindow", "numpy", "cv2", "rapidocr_onnxruntime", "PyQt6"]:
        items.append(_import_package(pkg))
    return items


def step2_screenshot() -> list[tuple[bool, str]]:
    items = []
    windows = []
    try:
        mod = _import("screenshot", _here / "01_screenshot.py")
        items.append(_check(True, "import 成功"))
    except Exception as e:
        items.append(_check(False, f"import 失敗 → {e}"))
        return items

    try:
        windows = mod.list_windows()
        items.append(_check(len(windows) > 0, f"list_windows() 回傳 {len(windows)} 個視窗"))
        if windows:
            for w in windows[:5]:
                items.append(_check(True, f"  視窗: {w[:60]}"))
    except Exception as e:
        items.append(_check(False, f"list_windows() 失敗 → {e}"))

    if windows:
        title = windows[0]
        try:
            rect = mod.get_window_rect(title)
            items.append(_check(rect is not None, f"get_window_rect({title[:40]}) = {rect}"))
        except Exception as e:
            items.append(_check(False, f"get_window_rect() 失敗 → {e}"))

        if rect:
            try:
                img = mod.capture(title)
                if img is not None:
                    items.append(_check(True, f"capture() → shape={img.shape} dtype={img.dtype}"))
                else:
                    items.append(_check(False, "capture() 回傳 None"))
            except Exception as e:
                items.append(_check(False, f"capture() 失敗 → {e}"))
    return items


def step3_ocr() -> list[tuple[bool, str]]:
    items = []
    try:
        mod = _import("ocr_engine", _here / "02_ocr_engine.py")
        items.append(_check(True, "import 成功"))
    except Exception as e:
        items.append(_check(False, f"import 失敗 → {e}"))
        return items

    try:
        t0 = time.time()
        mod.init_engine()
        t1 = time.time()
        items.append(_check(True, f"init_engine() 完成，耗時 {(t1 - t0) * 1000:.0f} ms"))
    except Exception as e:
        items.append(_check(False, f"init_engine() 失敗 → {e}"))
        return items

    try:
        ss_mod = _import("screenshot", _here / "01_screenshot.py")
        windows = ss_mod.list_windows()
        if windows:
            img = ss_mod.capture(windows[0])
            if img is not None:
                t0 = time.time()
                results = mod.recognize(img, max_side_len=640)
                t1 = time.time()
                items.append(
                    _check(
                        len(results) > 0,
                        f"recognize() → {len(results)} 筆結果，耗時 {(t1 - t0) * 1000:.0f} ms",
                    )
                )
                if results:
                    txt = results[0].text
                    found = mod.find_text(results, txt)
                    items.append(
                        _check(len(found) > 0, f"find_text({txt!r}) → 找到 {len(found)} 筆")
                    )
            else:
                items.append(_check(False, "capture() 回傳 None，無法測試 OCR"))
        else:
            items.append(_check(False, "無可用視窗，無法測試 OCR"))
    except Exception as e:
        items.append(_check(False, f"OCR 辨識測試失敗 → {e}"))
    return items


def step4_ahk() -> list[tuple[bool, str]]:
    items = []
    try:
        mod = _import("ahk_socket", _here / "03_ahk_socket.py")
        items.append(_check(True, "import 成功"))
    except Exception as e:
        items.append(_check(False, f"import 失敗 → {e}"))
        return items

    ahk_exe = None
    import shutil

    for exe in ["autohotkey.exe", "AutoHotkey64.exe", "AutoHotkey32.exe", "AutoHotkey.exe"]:
        if shutil.which(exe):
            ahk_exe = exe
            break
    if not ahk_exe:
        for p in Path("C:/Program Files/AutoHotkey").rglob("*.exe"):
            ahk_exe = p.name
            break
    items.append(
        _check(
            ahk_exe is not None,
            f"AHK 執行檔 {'找到: ' + ahk_exe if ahk_exe else '未找到 → 請安裝 AutoHotkey v2'}",
        )
    )

    ahk_script = mod._find_ahk()
    items.append(_check(Path(ahk_script).exists(), f"clicker.ahk 存在: {ahk_script}"))

    try:
        print("  注意：將對座標 (0,0) 執行測試點擊")
        ok = mod.init_ahk()
        items.append(_check(ok, f"init_ahk() 連線 {'成功' if ok else '失敗'}"))
        if ok:
            ok = mod.send_click(0, 0)
            items.append(_check(ok, f"send_click(0,0) → {'成功' if ok else '失敗'}"))
            ok = mod._send_cmd("PING")
            items.append(_check(ok, f"PING → {'回應正常' if ok else '無回應'}"))
    except Exception as e:
        items.append(_check(False, f"AHK 通訊測試失敗 → {e}"))
    finally:
        try:
            mod.shutdown()
            items.append(_check(True, "shutdown() 已關閉"))
        except Exception:
            pass
    return items


def step5_rule() -> list[tuple[bool, str]]:
    items = []
    try:
        mod = _import("rule_engine", _here / "04_rule_engine.py")
        items.append(_check(True, "import 成功"))
    except Exception as e:
        items.append(_check(False, f"import 失敗 → {e}"))
        return items

    rule = mod.Rule(
        id="diag_001",
        name="診斷測試",
        enabled=True,
        target_text="測試",
        fuzzy=False,
        fuzzy_threshold=0.8,
        roi={"x": 0, "y": 0, "w": 0, "h": 0},
        click_position="text_center",
        click_button="left",
        cooldown_ms=0,
        trigger_mode="once",
        max_triggers=1,
        random_offset=0,
    )
    items.append(_check(True, f"建立 Rule: {rule.name}"))

    fake_results = [
        mod.OcrResult(text="測試文字", x=10, y=20, w=80, h=20, confidence=0.95),
        mod.OcrResult(text="其他文字", x=100, y=200, w=60, h=20, confidence=0.80),
    ]

    hit, matched = mod.check_trigger(rule, fake_results)
    items.append(
        _check(
            hit and matched is not None,
            f"check_trigger() → 觸發={hit}, 文字={matched.text if matched else 'N/A'}",
        )
    )

    params = mod.apply_trigger(rule)
    items.append(_check(params["x"] == 0 and params["y"] == 0, f"apply_trigger() → {params}"))
    items.append(_check(rule.trigger_count == 1, f"trigger_count={rule.trigger_count}"))

    hit2, _ = mod.check_trigger(rule, fake_results)
    items.append(_check(not hit2, f"已達 max_triggers，再次檢查不觸發 (enabled={rule.enabled})"))

    tmp = _here / "_diag_rules.json"
    try:
        ok = mod.save_rules([rule], str(tmp))
        items.append(_check(ok, f"save_rules() → {'成功' if ok else '失敗'}"))
        loaded = mod.load_rules(str(tmp))
        items.append(
            _check(
                len(loaded) == 1 and loaded[0].id == "diag_001",
                f"load_rules() → {len(loaded)} 條規則",
            )
        )
        tmp.unlink(missing_ok=True)
    except Exception as e:
        items.append(_check(False, f"讀寫測試失敗 → {e}"))

    items.append(_check(rule.random_offset == 0, f"get_roi() → {mod.get_roi(rule)}"))
    return items


def step6_mainloop() -> list[tuple[bool, str]]:
    items = []
    try:
        mod = _import("main_loop", _here / "05_main_loop.py")
        items.append(_check(True, "import 成功"))
    except Exception as e:
        items.append(_check(False, f"import 失敗 → {e}"))
        return items

    try:
        ss_mod = _import("screenshot", _here / "01_screenshot.py")
        windows = ss_mod.list_windows()
    except Exception:
        windows = []

    if not windows:
        items.append(_check(False, "無可用視窗，無法測試 MainLoop"))
        return items

    rules_path = _here / "_diag_rules.json"
    try:
        r_mod = _import("rule_engine", _here / "04_rule_engine.py")
        diag_rule = r_mod.Rule(
            id="diag_ml",
            name="診斷ML",
            enabled=True,
            target_text="",
            fuzzy=False,
            fuzzy_threshold=0.8,
            roi={"x": 0, "y": 0, "w": 0, "h": 0},
            click_position="text_center",
            click_button="left",
            cooldown_ms=5000,
            trigger_mode="once",
            max_triggers=1,
            random_offset=0,
        )
        r_mod.save_rules([diag_rule], str(rules_path))
    except Exception as e:
        items.append(_check(False, f"建立測試規則失敗 → {e}"))
        return items

    try:
        loop = mod.MainLoop(str(rules_path), windows[0])
        items.append(_check(True, "MainLoop 初始化完成"))
    except Exception as e:
        items.append(_check(False, f"MainLoop 初始化失敗 → {e}"))
        rules_path.unlink(missing_ok=True)
        return items

    try:
        loop.start()
        time.sleep(0.5)
        items.append(_check(loop.is_running, f"start() → is_running={loop.is_running}"))

        loop.pause()
        time.sleep(0.2)
        items.append(_check(loop.is_paused, f"pause() → is_paused={loop.is_paused}"))

        loop.resume()
        time.sleep(0.2)
        items.append(_check(not loop.is_paused, f"resume() → is_paused={loop.is_paused}"))

        loop.stop()
        items.append(_check(True, "stop() 已關閉"))
    except Exception as e:
        items.append(_check(False, f"MainLoop 操作測試失敗 → {e}"))
        try:
            loop.stop()
        except Exception:
            pass

    rules_path.unlink(missing_ok=True)
    return items


def step8_entrypoint() -> list[tuple[bool, str]]:
    items = []

    try:
        from PyQt6 import QtWidgets

        items.append(_check(True, "PyQt6.QtWidgets import 成功"))
    except Exception as e:
        items.append(_check(False, f"PyQt6.QtWidgets import 失敗 → {e}"))
        return items

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    try:
        mod = _import("gui_main", _here / "06_gui_main.py")
        items.append(_check(True, "06_gui_main.py 載入成功"))
    except Exception as e:
        items.append(_check(False, f"06_gui_main.py 載入失敗 → {e}"))
        return items

    for cls_name in ["MainWindow", "InitWorker", "WorkerSignals"]:
        items.append(_check(hasattr(mod, cls_name), f"{cls_name} 類別存在"))

    try:
        _ = mod.MainLoop
        _ = mod.TriggerLog
        _import("gui_roi", _here / "07_gui_roi.py")
        _import("gui_log", _here / "08_gui_log.py")
        items.append(_check(True, "所有內部 import 可解析"))
    except Exception as e:
        items.append(_check(False, f"內部 import 解析失敗 → {e}"))

    return items


def step7_build() -> list[tuple[bool, str]]:
    items = []
    try:
        from build import get_data_path, get_resource_path

        items.append(_check(True, "import 成功"))
    except ImportError as e:
        items.append(_check(False, f"import 失敗 → {e}"))
        return items

    rp = get_resource_path("clicker.ahk")
    items.append(_check(rp.endswith("clicker.ahk"), f"get_resource_path() → {rp}"))

    dp = get_data_path("rules.json")
    items.append(_check("ocr-trigger-clicker" in dp, f"get_data_path() → {dp}"))

    p = Path(dp).parent
    items.append(
        _check(
            p.exists() or p.mkdir(parents=True, exist_ok=True) or True,
            f"資料目錄 {'存在' if p.exists() else '已建立'}: {p}",
        )
    )
    return items


_STEPS = [
    (1, "Python 環境", step1_python),
    (2, "01_screenshot.py", step2_screenshot),
    (3, "02_ocr_engine.py", step3_ocr),
    (4, "03_ahk_socket.py", step4_ahk),
    (5, "04_rule_engine.py", step5_rule),
    (6, "05_main_loop.py", step6_mainloop),
    (7, "build.py", step7_build),
    (8, "入口點 import 驗證", step8_entrypoint),
]


def main():
    for num, name, fn in _STEPS:
        t0 = time.time()
        print(f"\n{'=' * 50}")
        print(f"  Step {num}：{name}")
        print(f"{'=' * 50}")
        try:
            items = fn()
        except Exception as e:
            items = [(_check(False, f"未預期錯誤 → {e}"))]
        elapsed = time.time() - t0
        for ok, msg in items:
            icon = "✅" if ok else "❌"
            print(f"  {icon} {msg}")
        print(f"  ⏱ {(elapsed * 1000):.0f} ms")
        _results.append((num, name, items))

    total = 0
    passed = 0
    failed_steps = []
    for num, name, items in _results:
        for ok, _ in items:
            total += 1
            if ok:
                passed += 1
        if not all(ok for ok, _ in items):
            failed_steps.append(f"Step {num} — {name}")

    print(f"\n{'=' * 50}")
    print("  診斷結果")
    print(f"{'=' * 50}")
    print(f"  通過：{passed} / {total}")
    print(f"  總耗時：{(time.time() - _start_time) * 1000:.0f} ms")
    if failed_steps:
        print("  失敗：")
        for s in failed_steps:
            print(f"    ❌ {s}")
    else:
        print("  所有檢查通過！")


if __name__ == "__main__":
    print("OCR Trigger Clicker - 診斷工具")
    print(f"工作目錄: {Path.cwd()}")
    print(f"腳本目錄: {_here}")
    print()
    try:
        main()
    except Exception as e:
        print(f"\n❌ 診斷程式異常終止: {e}")
        import traceback

        traceback.print_exc()
