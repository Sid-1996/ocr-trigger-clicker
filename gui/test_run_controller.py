import re
import threading
import time
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox

from _loader import load_sibling
from i18n import T

_main_loop_mod = load_sibling("main_loop", "core/05_main_loop.py")
activate_window = _main_loop_mod.activate_window
capture = _main_loop_mod.capture
capture_window_content = getattr(_main_loop_mod, "capture_window_content", lambda title: None)
recognize = _main_loop_mod.recognize
find_text = _main_loop_mod.find_text
crop_roi = _main_loop_mod.crop_roi
get_window_rect = _main_loop_mod.get_window_rect
get_window_client_offset = getattr(_main_loop_mod, "get_window_client_offset", lambda title: None)

_rule_engine = load_sibling("rule_engine", "core/04_rule_engine.py")
get_capture_size = _rule_engine.get_capture_size


class TestRunController:
    def __init__(self, win, of_summary, resolve_rule_name):
        self._win = win
        self._of_summary = of_summary
        self._resolve_rule_name = resolve_rule_name

    # ── public entry ──

    def on_test_rule(self):
        win = self._win
        win._save_current_rule()
        rule = win._get_current_rule()
        if not rule:
            QMessageBox.warning(win, T("test.title"), T("test.select_rule"))
            return
        title = win._window_combo.currentText()
        if not title:
            QMessageBox.warning(win, T("test.title"), T("test.select_window"))
            return
        win._edit_test_btn.setEnabled(False)
        win._edit_test_btn.setText(T("test.testing"))
        QApplication.processEvents()
        win.showMinimized()
        QApplication.processEvents()
        time.sleep(0.08)
        activate_window(title)
        time.sleep(0.12)
        img = capture(title)
        if img is None:
            img = capture_window_content(title)
        win.showNormal()
        win.activateWindow()
        win._edit_stack.setCurrentIndex(1)
        if img is None:
            win._edit_test_btn.setEnabled(True)
            win._edit_test_btn.setText(T("ui.test"))
            QMessageBox.warning(win, T("test.title"), T("test.capture_failed", title=title))
            return
        t = threading.Thread(target=self._run_rule_test, args=(rule, img), daemon=True)
        t.start()

    # ── background thread ──

    def _run_rule_test(self, rule, img):
        result = {}
        try:
            markers, log_lines = self._run_dry_run(rule, img)
            annotated = self._draw_test_annotations(img.copy(), markers)
            result = {
                "image": annotated,
                "log": "\n".join(log_lines),
            }
        except Exception as e:
            result = {"error": T("test.exception", e=e)}
        self._win._signals.test_done_signal.emit(result)

    # ── dry-run core ──

    def _run_dry_run(self, rule, img):
        win = self._win
        of_summary = self._of_summary
        resolve_rule_name = self._resolve_rule_name

        def _resolve(roi):
            W, H = img.shape[1], img.shape[0]
            x, y, w, h = roi.get("x", 0), roi.get("y", 0), roi.get("w", 0), roi.get("h", 0)
            if x == 0 and y == 0 and w == 0 and h == 0:
                return roi
            if x <= 1.0 and y <= 1.0 and w <= 1.0 and h <= 1.0:
                if roi.get("roi_coord") == "client":
                    cx, cy = _chrome_offset
                    client_w = W - cx
                    client_h = H - cy
                    if client_w > 0 and client_h > 0:
                        px = {
                            "x": int(round(x * client_w)) + cx,
                            "y": int(round(y * client_h)) + cy,
                            "w": int(round(w * client_w)),
                            "h": int(round(h * client_h)),
                        }
                        return px
                px = {"x": int(x * W), "y": int(y * H), "w": int(w * W), "h": int(h * H)}
                return px
            return roi

        def _resolve_point(px, py, roi_coord=None):
            W, H = img.shape[1], img.shape[0]
            if isinstance(px, float) and px <= 1.0 and isinstance(py, float) and py <= 1.0:
                if roi_coord == "client":
                    cx, cy = _chrome_offset
                    client_w = W - cx
                    client_h = H - cy
                    if client_w > 0 and client_h > 0:
                        return int(round(px * client_w)) + cx, int(round(py * client_h)) + cy
                return int(round(px * W)), int(round(py * H))
            return int(px), int(py)

        _chrome_offset = get_window_client_offset(win._window_combo.currentText()) or (0, 0)
        markers = []
        log = []
        log.append(T("test.rule_header", name=rule.name, count=len(rule.steps)))
        log.append("─" * 40)

        last_center = None

        for idx, step in enumerate(rule.steps):
            try:
                if step.type == "detect":
                    p = step.params
                    text = p.get("text", "").strip()
                    if not text:
                        log.append(T("test.text_empty", idx=idx + 1))
                        continue
                    roi = _resolve(p.get("roi", {}))
                    use_roi = any(roi.get(k, 0) != 0 for k in ("x", "y", "w", "h"))
                    if use_roi:
                        roi_img = crop_roi(img, roi)
                        if roi_img is None:
                            log.append(T("test.roi_invalid", idx=idx + 1))
                            continue
                    else:
                        roi_img = img
                        roi = {"x": 0, "y": 0, "w": img.shape[1], "h": img.shape[0]}
                    results_ocr = recognize(
                        roi_img, preprocess=False, max_side_len=0, min_confidence=0.25
                    )
                    match_mode = p.get("match_mode", "fuzzy")
                    threshold = p.get("fuzzy_threshold", 0.8)
                    matches = find_text(results_ocr, text, match_mode, threshold)
                    rx = roi.get("x", 0)
                    ry = roi.get("y", 0)
                    if matches:
                        m = matches[0]
                        mx = rx + int(m.x)
                        my = ry + int(m.y)
                        mw = int(m.w)
                        mh = int(m.h)
                        cx = mx + mw // 2
                        cy = my + mh // 2
                        last_center = (cx, cy)
                        log.append(
                            T(
                                "test.detect_hit",
                                idx=idx + 1,
                                text=m.text,
                                confidence=f"{m.confidence:.2f}",
                                x=mx,
                                y=my,
                                w=mw,
                                h=mh,
                            )
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "rect",
                                "color": (0, 200, 0),
                                "x": mx,
                                "y": my,
                                "w": mw,
                                "h": mh,
                            }
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "point",
                                "color": (0, 200, 0),
                                "x": cx,
                                "y": cy,
                            }
                        )
                    else:
                        log.append(
                            T(
                                "test.detect_miss",
                                idx=idx + 1,
                                text=text,
                                mode=match_mode,
                                threshold=threshold,
                            )
                        )
                        of_hint = of_summary(p.get("on_fail", "stop"))
                        if of_hint:
                            log.append(f"  → {of_hint}")
                        rw = roi.get("w", img.shape[1])
                        rh = roi.get("h", img.shape[0])
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "rect",
                                "color": (0, 0, 200),
                                "x": rx,
                                "y": ry,
                                "w": rw,
                                "h": rh,
                            }
                        )
                        if results_ocr:
                            top5 = "、".join(
                                f"「{r.text}」({r.confidence:.2f})" for r in results_ocr[:5]
                            )
                            log.append(T("test.nearby_text", text=top5))
                            if len(results_ocr) > 5:
                                log.append(T("test.more_results", count=len(results_ocr) - 5))

                elif step.type == "click":
                    p = step.params
                    target = p.get("target", "text_center")
                    cx, cy = None, None
                    if target == "custom":
                        cx, cy = _resolve_point(p.get("x", 0), p.get("y", 0), p.get("roi_coord"))
                    elif target == "text_center":
                        if last_center:
                            cx, cy = last_center
                        else:
                            log.append(T("test.click_target_no_detect", idx=idx + 1))
                            continue
                    elif target == "click_text":
                        ct = p.get("text", "").strip()
                        if ct:
                            r = recognize(
                                img, preprocess=False, max_side_len=0, min_confidence=0.25
                            )
                            ms = find_text(r, ct, "contains", 0.8)
                            if ms:
                                m = ms[0]
                                cx = int(m.x + m.w / 2)
                                cy = int(m.y + m.h / 2)
                            else:
                                log.append(T("test.click_text_not_found", idx=idx + 1, text=ct))
                                continue
                    if cx is not None:
                        log.append(
                            T(
                                "test.click_action",
                                idx=idx + 1,
                                button=p.get("button", "left"),
                                x=cx,
                                y=cy,
                            )
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "click",
                                "color": (0, 0, 255),
                                "x": cx,
                                "y": cy,
                            }
                        )

                elif step.type == "drag":
                    p = step.params
                    target = p.get("target", "text_center")
                    sx, sy = None, None
                    if target == "custom":
                        sx, sy = _resolve_point(p.get("x", 0), p.get("y", 0), p.get("roi_coord"))
                    elif target == "text_center":
                        if last_center:
                            sx, sy = last_center
                        else:
                            log.append(T("test.drag_start_no_detect", idx=idx + 1))
                            continue
                    elif target == "click_text":
                        ct = p.get("text", "").strip()
                        if ct:
                            r = recognize(
                                img, preprocess=False, max_side_len=0, min_confidence=0.25
                            )
                            ms = find_text(r, ct, "contains", 0.8)
                            if ms:
                                m = ms[0]
                                sx = int(m.x + m.w / 2)
                                sy = int(m.y + m.h / 2)
                            else:
                                log.append(T("test.drag_text_not_found", idx=idx + 1, text=ct))
                                continue
                    if sx is not None:
                        dx = p.get("dx", 0)
                        dy = p.get("dy", 0)
                        ex = sx + dx
                        ey = sy + dy
                        log.append(
                            T(
                                "test.drag_action",
                                idx=idx + 1,
                                button=p.get("button", "left"),
                                sx=sx,
                                sy=sy,
                                ex=ex,
                                ey=ey,
                            )
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "drag",
                                "color": (255, 150, 0),
                                "x1": sx,
                                "y1": sy,
                                "x2": ex,
                                "y2": ey,
                            }
                        )

                elif step.type == "scroll":
                    p = step.params
                    dirs = {
                        "WheelDown": T("test.scroll_down"),
                        "WheelUp": T("test.scroll_up"),
                        "WheelLeft": T("test.scroll_left"),
                        "WheelRight": T("test.scroll_right"),
                    }
                    d = dirs.get(p.get("direction", "WheelDown"), p.get("direction", ""))
                    log.append(
                        T("test.scroll", idx=idx + 1, direction=d, amount=p.get("amount", 1))
                    )

                elif step.type == "notify":
                    msg = step.params.get("message", "")
                    log.append(
                        T("test.notify", idx=idx + 1, message=msg)
                        if msg
                        else T("test.notify_empty", idx=idx + 1)
                    )

                elif step.type == "compare":
                    p = step.params
                    op = p.get("operator", ">=")
                    val = p.get("value", 0.0)
                    pattern = p.get("pattern", r"-?\d+\.?\d*")

                    r = _resolve(p.get("roi", {}))
                    use_roi = any(r.get(k, 0) != 0 for k in ("x", "y", "w", "h"))
                    if use_roi:
                        roi_img = crop_roi(img, r)
                        if roi_img is None:
                            log.append(T("test.roi_invalid", idx=idx + 1))
                            continue
                    else:
                        roi_img = img
                        r = {"x": 0, "y": 0, "w": img.shape[1], "h": img.shape[0]}
                    results_ocr = recognize(
                        roi_img, preprocess=False, max_side_len=0, min_confidence=0.25
                    )
                    combined = " ".join(res.text for res in results_ocr)
                    m = re.search(pattern, combined)

                    rx = r.get("x", 0)
                    ry = r.get("y", 0)
                    rw = r.get("w", img.shape[1])
                    rh = r.get("h", img.shape[0])

                    if results_ocr:
                        first = results_ocr[0]
                        cx = rx + int(first.x) + int(first.w) // 2
                        cy = ry + int(first.y) + int(first.h) // 2
                        last_center = (cx, cy)

                    if not m:
                        log.append(T("test.compare_no_digit", idx=idx + 1, pattern=pattern))
                        if results_ocr:
                            top5 = "、".join(
                                f"「{res.text}」({res.confidence:.2f})" for res in results_ocr[:5]
                            )
                            log.append(T("test.ocr_text", text=top5))
                            if len(results_ocr) > 5:
                                log.append(T("test.more_results", count=len(results_ocr) - 5))
                        of_hint = of_summary(p.get("on_fail", "stop"))
                        if of_hint:
                            log.append(f"  → {of_hint}")
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "rect",
                                "color": (0, 0, 200),
                                "x": rx,
                                "y": ry,
                                "w": rw,
                                "h": rh,
                            }
                        )
                        continue

                    try:
                        num = float(m.group())
                    except (ValueError, TypeError):
                        log.append(
                            T("test.digit_invalid", idx=idx + 1, text=m.group(), pattern=pattern)
                        )
                        of_hint = of_summary(p.get("on_fail", "stop"))
                        if of_hint:
                            log.append(f"  → {of_hint}")
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "rect",
                                "color": (0, 0, 200),
                                "x": rx,
                                "y": ry,
                                "w": rw,
                                "h": rh,
                            }
                        )
                        continue

                    _cmp_ops = {
                        ">": lambda a, b: a > b,
                        "<": lambda a, b: a < b,
                        ">=": lambda a, b: a >= b,
                        "<=": lambda a, b: a <= b,
                        "==": lambda a, b: a == b,
                        "!=": lambda a, b: a != b,
                    }
                    passed = op in _cmp_ops and _cmp_ops[op](num, val)
                    status = "✅" if passed else "❌"
                    log.append(
                        f"[{idx + 1}] 🔢 {num} {op} {val}  {status}   OCR:「{combined[:40]}」"
                    )

                    markers.append(
                        {
                            "step": idx + 1,
                            "shape": "rect",
                            "color": (0, 200, 0) if passed else (0, 0, 200),
                            "x": rx,
                            "y": ry,
                            "w": rw,
                            "h": rh,
                        }
                    )

                    if not passed:
                        of_hint = of_summary(p.get("on_fail", "stop"))
                        if of_hint:
                            log.append(f"  → {of_hint}")

                elif step.type == "key":
                    p = step.params
                    k = p.get("key", "")
                    hm = p.get("hold_ms", 0)
                    s = T("test.key_hold", ms=hm) if hm else T("test.key_press")
                    log.append(T("test.key_action", idx=idx + 1, action=s, key=k))

                elif step.type == "wait":
                    p = step.params
                    log.append(T("test.wait", idx=idx + 1, ms=p.get("ms", 500)))

                elif step.type == "jump":
                    rid = step.params.get("rule_id", "")
                    name = resolve_rule_name(rid, lambda: list(win._rules))
                    log.append(T("test.jump", idx=idx + 1, name=name))

                elif step.type == "match_image":
                    p = step.params
                    tmpl_data = p.get("template_data", "")
                    tmpl_path = p.get("template", "")
                    if not tmpl_data.strip() and not tmpl_path.strip():
                        log.append(T("test.template_not_set", idx=idx + 1))
                        continue
                    roi = _resolve(p.get("roi", {}))
                    threshold = p.get("threshold", 0.8)
                    match_color = p.get("match_color", False)
                    color_tolerance = p.get("color_tolerance", 100)
                    task_path = (
                        str(_rule_engine.get_tasks_dir() / f"{win._current_task}.json")
                        if win._current_task
                        else None
                    )
                    cs = get_capture_size(task_path) if task_path else None
                    title = win._window_combo.currentText()
                    wr = get_window_rect(title) if title else None
                    chrome = get_window_client_offset(title) or (0, 0) if title else (0, 0)
                    if wr and chrome and chrome[0] >= 0 and chrome[1] >= 0:
                        cur_size = [wr["w"] - chrome[0], wr["h"] - chrome[1]]
                    else:
                        cur_size = None
                    results = _main_loop_mod.match_template(
                        img,
                        tmpl_path,
                        roi,
                        threshold,
                        template_data=tmpl_data or None,
                        capture_size=cs,
                        current_size=cur_size,
                        match_color=match_color,
                        color_tolerance=color_tolerance,
                    )
                    tmpl_name = (
                        T("test.template_embedded") if tmpl_data.strip() else Path(tmpl_path).stem
                    )
                    if results:
                        m = results[0]
                        cx, cy = m.center_x, m.center_y
                        last_center = (cx, cy)
                        log.append(
                            T(
                                "test.template_hit",
                                idx=idx + 1,
                                name=tmpl_name,
                                confidence=f"{m.confidence:.2f}",
                                x=m.x,
                                y=m.y,
                                w=m.w,
                                h=m.h,
                            )
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "rect",
                                "color": (0, 200, 0),
                                "x": m.x,
                                "y": m.y,
                                "w": m.w,
                                "h": m.h,
                            }
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "point",
                                "color": (0, 200, 0),
                                "x": cx,
                                "y": cy,
                            }
                        )
                    else:
                        rx, ry = roi.get("x", 0), roi.get("y", 0)
                        rw = roi.get("w", img.shape[1]) or img.shape[1]
                        rh = roi.get("h", img.shape[0]) or img.shape[0]
                        of_hint = of_summary(p.get("on_fail", "stop"))
                        of_suffix = f" → {of_hint}" if of_hint else ""
                        log.append(
                            T(
                                "test.template_miss",
                                idx=idx + 1,
                                name=tmpl_name,
                                threshold=threshold,
                                suffix=of_suffix,
                            )
                        )
                        markers.append(
                            {
                                "step": idx + 1,
                                "shape": "rect",
                                "color": (0, 0, 200),
                                "x": rx,
                                "y": ry,
                                "w": rw,
                                "h": rh,
                            }
                        )

                else:
                    log.append(T("test.unknown_step", idx=idx + 1, type=step.type))

            except Exception as e:
                log.append(f"[{idx + 1}] ⚠ {type(e).__name__}: {e}")

        return markers, log

    # ── annotation drawing ──

    def _draw_test_annotations(self, img, markers):
        import cv2

        h, w = img.shape[:2]
        overlay = np.zeros_like(img, dtype=np.uint8)

        for m in markers:
            color = m.get("color", (0, 255, 0))
            shape = m.get("shape", "")
            if shape == "rect":
                x = max(0, m["x"])
                y = max(0, m["y"])
                rw = min(w - x, m["w"])
                rh = min(h - y, m["h"])
                if rw > 0 and rh > 0:
                    cv2.rectangle(overlay, (x, y), (x + rw, y + rh), color, -1)
            elif shape == "point":
                cv2.circle(overlay, (m["x"], m["y"]), 6, color, -1)
            elif shape == "click":
                cx, cy = m["x"], m["y"]
                cv2.line(overlay, (cx - 15, cy), (cx + 15, cy), color, 3)
                cv2.line(overlay, (cx, cy - 15), (cx, cy + 15), color, 3)
                cv2.circle(overlay, (cx, cy), 6, color, -1)
            elif shape == "drag":
                cv2.arrowedLine(overlay, (m["x1"], m["y1"]), (m["x2"], m["y2"]), color, 2)
                cv2.circle(overlay, (m["x1"], m["y1"]), 4, color, -1)

        target = img.copy()
        cv2.addWeighted(overlay, 0.25, target, 0.75, 0, target)

        for m in markers:
            color = m.get("color", (0, 255, 0))
            step = m.get("step", 0)
            shape = m.get("shape", "")
            if shape == "rect":
                x = max(0, m["x"])
                y = max(0, m["y"])
                rw = min(w - x, m["w"])
                rh = min(h - y, m["h"])
                if rw > 0 and rh > 0:
                    cv2.rectangle(target, (x, y), (x + rw - 1, y + rh - 1), color, 2)
                    if step:
                        cv2.putText(
                            target,
                            str(step),
                            (x + 4, y + 16),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            (255, 255, 255),
                            2,
                        )
                        cv2.putText(
                            target,
                            str(step),
                            (x + 4, y + 16),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.55,
                            color,
                            1,
                        )
            elif shape == "click":
                if step:
                    cx, cy = m["x"], m["y"]
                    cv2.putText(
                        target,
                        str(step),
                        (cx + 14, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 255, 255),
                        2,
                    )
                    cv2.putText(
                        target,
                        str(step),
                        (cx + 14, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        color,
                        1,
                    )
            elif shape == "drag":
                if step:
                    sx, sy = m["x1"], m["y1"]
                    cv2.putText(
                        target,
                        str(step),
                        (sx + 6, sy - 6),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 255, 255),
                        2,
                    )
                    cv2.putText(
                        target,
                        str(step),
                        (sx + 6, sy - 6),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        color,
                        1,
                    )

        return target
