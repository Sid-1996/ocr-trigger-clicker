from pathlib import Path

from PyQt6.QtWidgets import QApplication

from _loader import load_sibling

_main_loop_mod = load_sibling("main_loop", "core/05_main_loop.py")
activate_window = _main_loop_mod.activate_window
get_window_rect = _main_loop_mod.get_window_rect
get_window_client_offset = getattr(_main_loop_mod, "get_window_client_offset", lambda title: None)
capture = _main_loop_mod.capture

_tmpl_mod = load_sibling("template_matching", "core/11_template_matching.py")
img_to_b64 = _tmpl_mod.img_to_b64


def _tasks_dir() -> str:
    mod = load_sibling("rule_engine", "core/04_rule_engine.py")
    return str(mod.get_tasks_dir())


def _pixels_to_ratio_expanded(
    px: int, py: int, pw: int, ph: int, ww: int, wh: int, margin: float = 0.2
) -> dict:
    margin_w = max(pw * margin, ww * 0.01)
    margin_h = max(ph * margin, wh * 0.01)
    return {
        "x": max(0.0, min(1.0, (px - margin_w) / ww)),
        "y": max(0.0, min(1.0, (py - margin_h) / wh)),
        "w": max(0.0, min(1.0, (pw + 2 * margin_w) / ww)),
        "h": max(0.0, min(1.0, (ph + 2 * margin_h) / wh)),
    }


class ScreenshotController:
    def __init__(self, win):
        self._win = win

    def open_roi_selector(self):
        win = self._win
        title = win._window_combo.currentText()
        if title:
            activate_window(title)
        mod = load_sibling("roi", "gui/07_gui_roi.py")
        result = mod.select_roi(parent_window=win)
        if not result:
            return None
        if title:
            screen = QApplication.primaryScreen()
            ratio = screen.devicePixelRatio()
            result["x"] = int(result["x"] * ratio)
            result["y"] = int(result["y"] * ratio)
            wr = get_window_rect(title)
            if wr:
                result["x"] -= wr["x"]
                result["y"] -= wr["y"]
        win._edit_stack.setCurrentIndex(1)
        win._status_bar.showMessage(
            f"已選取偵測區域: ({result['x']},{result['y']}) {result['w']}×{result['h']}"
        )
        if title and wr and wr["w"] > 0 and wr["h"] > 0:
            chrome = get_window_client_offset(title) or (0, 0)
            cx, cy = chrome
            client_w = wr["w"] - cx
            client_h = wr["h"] - cy
            if client_w > 0 and client_h > 0:
                result = {
                    "x": max(0.0, (result["x"] - cx) / client_w),
                    "y": max(0.0, (result["y"] - cy) / client_h),
                    "w": min(1.0, result["w"] / client_w),
                    "h": min(1.0, result["h"] / client_h),
                    "roi_coord": "client",
                }
            else:
                result = {
                    "x": result["x"] / wr["w"],
                    "y": result["y"] / wr["h"],
                    "w": result["w"] / wr["w"],
                    "h": result["h"] / wr["h"],
                }
        return result

    def _capture_rect_to_roi(self, rect: dict, title: str) -> dict | None:
        if not title:
            return None
        wr = get_window_rect(title)
        if not wr or wr["w"] <= 0 or wr["h"] <= 0:
            return None
        cx, cy = rect["x"] + rect["w"] // 2, rect["y"] + rect["h"] // 2
        dpr = 1.0
        for screen in QApplication.screens():
            g = screen.geometry()
            if g.x() <= cx < g.x() + g.width() and g.y() <= cy < g.y() + g.height():
                dpr = screen.devicePixelRatio()
                break
        px = int(rect["x"] * dpr) - wr["x"]
        py = int(rect["y"] * dpr) - wr["y"]
        pw = int(rect["w"] * dpr)
        ph = int(rect["h"] * dpr)
        chrome = get_window_client_offset(title) or (0, 0)
        client_px = px - chrome[0]
        client_py = py - chrome[1]
        client_w = wr["w"] - chrome[0]
        client_h = wr["h"] - chrome[1]
        if client_w <= 0 or client_h <= 0:
            return _pixels_to_ratio_expanded(px, py, pw, ph, wr["w"], wr["h"])
        roi = _pixels_to_ratio_expanded(client_px, client_py, pw, ph, client_w, client_h)
        roi["roi_coord"] = "client"
        return roi

    def open_capture_region(self):
        win = self._win
        title = win._window_combo.currentText()
        if title:
            activate_window(title)
        mod = load_sibling("capture_region", "gui/14_capture_region.py")
        task_path = (
            str(Path(_tasks_dir()) / f"{win._current_task}.json") if win._current_task else ""
        )
        rect = mod.capture_region(parent_window=win, task_path=task_path, window_title=title)
        if not rect:
            return None
        b64 = rect.get("template_b64")
        if b64:
            win._status_bar.showMessage("已截取範本")
            win._edit_stack.setCurrentIndex(1)
            roi_ratio = self._capture_rect_to_roi(rect, title)
            return {"b64": b64, "roi": roi_ratio} if roi_ratio else {"b64": b64}
        if title:
            screen = QApplication.primaryScreen()
            ratio = screen.devicePixelRatio()
            rx = int(rect["x"] * ratio)
            ry = int(rect["y"] * ratio)
            rw = int(rect["w"] * ratio)
            rh = int(rect["h"] * ratio)
            wr = get_window_rect(title)
            if wr:
                rx -= wr["x"]
                ry -= wr["y"]
            if wr:
                chrome = get_window_client_offset(title) or (0, 0)
                client_rx = rx - chrome[0]
                client_ry = ry - chrome[1]
                client_w = wr["w"] - chrome[0]
                client_h = wr["h"] - chrome[1]
                if client_w > 0 and client_h > 0:
                    roi_ratio = _pixels_to_ratio_expanded(
                        client_rx, client_ry, rw, rh, client_w, client_h
                    )
                    roi_ratio["roi_coord"] = "client"
                else:
                    roi_ratio = _pixels_to_ratio_expanded(rx, ry, rw, rh, wr["w"], wr["h"])
            else:
                roi_ratio = None
            img = capture(title)
            if img is not None and img.shape[0] >= ry + rh and img.shape[1] >= rx + rw:
                crop = img[ry : ry + rh, rx : rx + rw]
                b64 = img_to_b64(crop)
                win._status_bar.showMessage(f"已截取範本 ({crop.shape[1]}×{crop.shape[0]})")
                win._edit_stack.setCurrentIndex(1)
                return {"b64": b64, "roi": roi_ratio} if roi_ratio else {"b64": b64}
        return None
