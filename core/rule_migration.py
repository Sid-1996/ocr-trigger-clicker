import math
from copy import deepcopy
from pathlib import Path

_STEP_DEFAULTS = {
    "detect": {
        "text": "",
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "match_mode": "fuzzy",
        "fuzzy_threshold": 0.8,
        "on_fail": "stop",
        "after_delay_ms": 0,
    },
    "click": {
        "target": "text_center",
        "x": 0,
        "y": 0,
        "button": "left",
        "random_offset": 3,
        "hold_ms": 0,
        "after_delay_ms": 0,
    },
    "key": {"key": "", "hold_ms": 0, "after_delay_ms": 0},
    "drag": {
        "target": "text_center",
        "x": 0,
        "y": 0,
        "button": "left",
        "after_delay_ms": 0,
    },
    "scroll": {"direction": "WheelDown", "amount": 1, "delay_ms": 30, "after_delay_ms": 0},
    "wait": {"ms": 500},
    "jump": {"rule_id": ""},
    "compare": {
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "pattern": r"-?\d+\.?\d*",
        "operator": ">=",
        "value": 0.0,
        "on_fail": "stop",
    },
    "match_image": {
        "template": "",
        "template_data": "",
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "threshold": 0.8,
        "match_color": False,
        "color_tolerance": 100,
        "on_fail": "stop",
        "after_delay_ms": 0,
    },
    "notify": {"message": ""},
    "sum": {"roi": {"x": 0, "y": 0, "w": 0, "h": 0}},
}


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError：int(float('inf')) 會拋出，任務 JSON 可帶 Infinity
        # （Python json 預設接受 Infinity/NaN），不可讓例外穿透載入流程。
        # NaN 走 ValueError 分支，兩者一律回退欄位既有 default。
        return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError：float(10**400) 這類超大整數會拋出
        return default
    if not math.isfinite(result):
        # NaN / ±Infinity：非有限值不得進入執行期參數
        # （NaN 讓所有比較恆 False，Infinity 讓門檻恆不成立）。
        # 回退各欄位自己的 default，不一律轉 0（0 在不同欄位語意不同）。
        return default
    return result


def _as_optional_float(value) -> float | None:
    """非有限值（NaN/±Infinity）、null 與非數值 → None（代表「無效值」）。

    僅用於需要區分「無效」與「預設值」的欄位（目前只有 compare.value）：
    無效值必須讓執行期安全失敗，而不是被當成 0.0 —— 0.0 在 ">=" / ">" / "!="
    之下會讓比較條件恆成立，等於無條件執行後續的點擊／按鍵動作。
    其他欄位仍走 _as_float 的 default 回退語義。
    """
    return _as_float(value, None)


def _is_finite_number(value: object) -> bool:
    """value 是否為有限數值（非 bool、非 NaN/±Infinity、可轉 float）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


_VALID_MIGRATION_REASONS = frozenset(
    {
        "legacy_px_offset",
        "incomplete_legacy_offset",
        "mixed_legacy_and_endpoint",
        "invalid_legacy_offset",
    }
)


def _is_valid_migration(marker: object) -> bool:
    """_migration marker 是否為合法的 drag_endpoint 待修復標記。"""
    return (
        isinstance(marker, dict)
        and marker.get("kind") == "drag_endpoint"
        and marker.get("status") == "needs_repair"
        and marker.get("reason") in _VALID_MIGRATION_REASONS
    )


def _detect_drag_legacy_marker(params: dict) -> dict | None:
    """依據「原始 JSON params」偵測 Drag 舊 PX offset，回傳 _migration marker 或 None。

    偵測發生在 normalize 覆寫之前，故不會因 normalize 產生的預設值而誤判。
    不會自動把 dx/dy 換算成 end_x/end_y，也不會刪除原始 dx/dy。

    回傳 None 表示「不建立 legacy marker」（含現有合法 marker 維持不動、
    以及純新格式/無舊 PX 欄位的情形）。
    """
    if not isinstance(params, dict):
        return None

    # rule 8：資料已存在合法 marker，不可任意覆蓋原有 reason → 回 None 表示保留現有。
    if _is_valid_migration(params.get("_migration")):
        return None

    has_dx = "dx" in params
    has_dy = "dy" in params
    dx_val = params.get("dx")
    dy_val = params.get("dy")

    dx_valid = has_dx and _is_finite_number(dx_val)
    dy_valid = has_dy and _is_finite_number(dy_val)

    # rule 5：非法舊 PX 欄位優先分類為 invalid_legacy_offset。
    if (has_dx and not dx_valid) or (has_dy and not dy_valid):
        return {
            "_migration": {
                "kind": "drag_endpoint",
                "status": "needs_repair",
                "reason": "invalid_legacy_offset",
            }
        }

    # rule 7：無舊 PX 欄位 → 不建立 legacy marker（end 欄位由終點驗證判定）。
    if not has_dx and not has_dy:
        return None

    has_end_x = "end_x" in params and params["end_x"] is not None
    has_end_y = "end_y" in params and params["end_y"] is not None
    end_complete = has_end_x and has_end_y

    # rule 4：同時存在舊 PX 欄位與完整 end_x/end_y → mixed。
    if end_complete:
        return {
            "_migration": {
                "kind": "drag_endpoint",
                "status": "needs_repair",
                "reason": "mixed_legacy_and_endpoint",
            }
        }

    # rule 2：dx/dy 都存在且合法 → legacy_px_offset。
    if has_dx and has_dy:
        return {
            "_migration": {
                "kind": "drag_endpoint",
                "status": "needs_repair",
                "reason": "legacy_px_offset",
            }
        }

    # rule 3：只有一邊存在 → incomplete_legacy_offset。
    return {
        "_migration": {
            "kind": "drag_endpoint",
            "status": "needs_repair",
            "reason": "incomplete_legacy_offset",
        }
    }


def _validation_result(status: str, reason: str, message: str) -> dict:
    return {"status": status, "reason": reason, "message": message}


def validate_drag_endpoint(params: dict) -> dict:
    """純函式：判斷 Drag 終點資料狀態。

    回傳 {"status", "reason", "message"}，status in {
        "valid", "unset", "incomplete", "invalid", "needs_repair"
    }。

    unset/incomplete/invalid 不等於 needs_repair；新建但尚未設定終點的 Drag
    不會被錯誤標記為 legacy。僅讀取 params，不會修改原始資料。
    """
    params = params if isinstance(params, dict) else {}

    migration = params.get("_migration")
    if _is_valid_migration(migration):
        # rule 8：合法 marker 直接信任，不重新分類也不覆寫 reason。
        return _validation_result(
            "needs_repair",
            migration.get("reason", "legacy_px_offset"),
            f"Drag 終點待修復（{migration.get('reason')}）。",
        )

    has_dx = "dx" in params
    has_dy = "dy" in params
    end_x = params.get("end_x")
    end_y = params.get("end_y")
    has_end_x = "end_x" in params and end_x is not None
    has_end_y = "end_y" in params and end_y is not None

    # 存在舊 PX 欄位 → needs_repair（與 valid/incomplete/invalid 並列，不等於它們）。
    if has_dx or has_dy:
        dx_valid = has_dx and _is_finite_number(params.get("dx"))
        dy_valid = has_dy and _is_finite_number(params.get("dy"))
        if not dx_valid or not dy_valid:
            return _validation_result(
                "needs_repair", "invalid_legacy_offset", "舊版 PX offset 不合法。"
            )
        if has_end_x and has_end_y:
            return _validation_result(
                "needs_repair",
                "mixed_legacy_and_endpoint",
                "新舊終點格式混合。",
            )
        if has_dx and has_dy:
            return _validation_result("needs_repair", "legacy_px_offset", "使用舊版 PX offset。")
        return _validation_result(
            "needs_repair",
            "incomplete_legacy_offset",
            "舊版 PX offset 僅設定一軸。",
        )

    # 無舊 PX：依 end_x/end_y 判斷。
    if not has_end_x and not has_end_y:
        return _validation_result("unset", "unset", "Drag 終點尚未設定。")
    if has_end_x != has_end_y:
        return _validation_result("incomplete", "incomplete", "Drag 僅設定一端終點。")
    # 兩端皆設定：數值、範圍、end_roi_coord 必須都合法。
    if not _is_finite_number(end_x) or not _is_finite_number(end_y):
        return _validation_result("invalid", "invalid_value", "終點座標不是合法數值。")
    xf, yf = float(end_x), float(end_y)
    if not (0.0 <= xf <= 1.0 and 0.0 <= yf <= 1.0):
        return _validation_result("invalid", "out_of_range", "終點座標超出有效比例範圍（0~1）。")
    end_coord = params.get("end_roi_coord")
    if end_coord is not None and end_coord != "client":
        return _validation_result("invalid", "invalid_end_roi_coord", "end_roi_coord 不合法。")
    return _validation_result("valid", "valid", "Drag 終點完整。")


def _sanitize_roi(roi: dict | None) -> dict:
    roi = roi if isinstance(roi, dict) else {}
    result = {
        "x": max(0.0, _as_float(roi.get("x", 0))),
        "y": max(0.0, _as_float(roi.get("y", 0))),
        "w": max(0.0, _as_float(roi.get("w", 0))),
        "h": max(0.0, _as_float(roi.get("h", 0))),
    }
    if roi.get("roi_coord") == "client":
        result["roi_coord"] = "client"
    return result


def _sanitize_capture_size(raw: object) -> list[int] | None:
    """模板來源解析度；無效值回 None（回退任務級 capture_size）。"""
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    try:
        w, h = int(raw[0]), int(raw[1])
    except (TypeError, ValueError, OverflowError):
        # OverflowError：int(float('inf')) — 非法尺寸回 None（回退任務級 capture_size）
        return None
    if not (0 < w <= 100000 and 0 < h <= 100000):
        return None
    return [w, h]


def _sanitize_color_mask(raw: object) -> dict | None:
    """顏色範圍遮罩（RGB）；無效或空值回 None，不讓匯入任務帶壞資料。"""
    if not isinstance(raw, dict):
        return None
    colors = raw.get("colors")
    if not isinstance(colors, (list, tuple)):
        return None
    result = []
    seen = set()
    for color in colors[:8]:
        if not isinstance(color, (list, tuple)) or len(color) != 3:
            continue
        try:
            r, g, b = (max(0, min(255, int(v))) for v in color)
        except (TypeError, ValueError, OverflowError):
            # OverflowError：int(float('inf')) — 非法色碼略過該色
            continue
        key = (r, g, b)
        if key in seen:
            continue
        seen.add(key)
        result.append([r, g, b])
    if not result:
        return None
    mode = str(raw.get("mode", "ignore")).strip().lower()
    if mode not in ("ignore", "keep"):
        mode = "ignore"
    return {
        "colors": result,
        "tolerance": max(0, min(255, _as_int(raw.get("tolerance", 30), 30))),
        "mode": mode,
    }


def _normalize_action(action: dict | None, default_type: str = "key") -> dict:
    action = action if isinstance(action, dict) else {}
    action_type = str(action.get("type", default_type))
    if action_type == "click":
        return {
            "type": "click",
            "target": str(action.get("target", "text_center")),
            "x": _as_int(action.get("x", 0), 0),
            "y": _as_int(action.get("y", 0), 0),
            "button": str(action.get("button", "left")),
        }
    if action_type == "jump":
        return {"type": "jump", "rule_id": str(action.get("rule_id", ""))}
    return {"type": "key", "key": str(action.get("key", ""))}


def _normalize_on_fail(raw: object, allow_skip: bool = False) -> str | dict:
    if isinstance(raw, dict):
        action = str(raw.get("action", "stop"))
        fd = _as_float(raw.get("fail_duration_sec", 0), 0.0)
        if action == "notify":
            stop_groups = raw.get("stop_groups", [])
            if not isinstance(stop_groups, (list, tuple)):
                stop_groups = []
            result: dict = {
                "action": "notify",
                "message": str(raw.get("message", "")).strip(),
                "stop_groups": [str(g) for g in stop_groups if g],
            }
        elif action == "key":
            result = {"action": "key", "key": str(raw.get("key", ""))}
        elif action == "skip" and allow_skip:
            result = {"action": "skip", "skip_to": max(0, _as_int(raw.get("skip_to", 0), 0))}
        elif action == "jump":
            result = {"action": "jump", "rule_id": str(raw.get("rule_id", ""))}
        elif action == "advance":
            result = {"action": "advance"}
        elif action == "stop":
            # stop 搭配容忍期：GUI 寫入 {"action":"stop","fail_duration_sec":N}，
            # 不可壓成裸字串 "stop"，否則容忍期在重新載入後被靜默丟棄，
            # 使用者設定的「持續失敗 N 秒」會在存檔再開後失效。
            # fd == 0 時維持既有向下相容寫法（純字串 "stop"）。
            if fd > 0:
                return {"action": "stop", "fail_duration_sec": fd}
            return "stop"
        else:
            return "stop"
        if fd > 0:
            result["fail_duration_sec"] = fd
        return result
    return str(raw) if str(raw) in ("key", "stop") else "stop"


def _normalize_verify(raw: object, rule_name: str = "") -> dict | None:
    if not isinstance(raw, dict):
        return None
    vtype = str(raw.get("type", "")).strip()
    if vtype not in ("detect", "match_image"):
        return None
    preset = str(raw.get("preset", "")).strip()
    if preset not in ("short", "medium", "long"):
        preset = "medium"
    timeout_ms = max(0, min(30000, _as_int(raw.get("timeout_ms", 5000), 5000)))
    poll_ms = max(50, min(2000, _as_int(raw.get("poll_interval_ms", 300), 300)))
    delay_ms = max(0, min(5000, _as_int(raw.get("delay_before_ms", 0), 0)))
    expect = str(raw.get("expect", "present")).strip() or "present"
    if expect not in ("present", "absent"):
        expect = "present"
    retries = max(0, min(3, _as_int(raw.get("retries", 1), 1)))
    retry_delay_ms = max(0, min(5000, _as_int(raw.get("retry_delay_ms", 500), 500)))
    roi = _sanitize_roi(raw.get("roi", {"x": 0, "y": 0, "w": 0, "h": 0}))
    on_fail_raw = raw.get("on_fail", None)
    # verify + stop is forbidden (would retry Action each loop) -> mark invalid
    if isinstance(on_fail_raw, str) and on_fail_raw == "stop":
        return None
    if isinstance(on_fail_raw, dict) and str(on_fail_raw.get("action", "")) == "stop":
        return None
    # 缺省／None／無效純量一律採 advance：verify 已禁止 stop，若 runtime 再回退
    # stop 會讓動作每幀重送。明確 stop 仍在上方視為無效 verify。
    if on_fail_raw is None:
        on_fail: str | dict = {"action": "advance"}
    elif isinstance(on_fail_raw, str) and on_fail_raw == "advance":
        on_fail = {"action": "advance"}  # 舊 JSON 可能存字串
    elif not isinstance(on_fail_raw, (str, dict)):
        on_fail = {"action": "advance"}  # 無效型別 → 預設 advance，避免落到 stop
    else:
        on_fail = _normalize_on_fail(on_fail_raw, allow_skip=True)
        # _normalize may coerce unknown to "stop" — treat that as invalid too
        if on_fail == "stop" or (isinstance(on_fail, dict) and on_fail.get("action") == "stop"):
            # if user explicitly passed stop-like value, reject
            if isinstance(on_fail_raw, (str, dict)):
                return None
        # 空 key 會讓 _handle_on_fail 不送按鍵卻回 continue，改走 advance。
        # 舊格式 "key" 經 _normalize_on_fail 後也是字串，需一併涵蓋。
        if on_fail == "key" or (
            isinstance(on_fail, dict)
            and on_fail.get("action") == "key"
            and (
                not str(on_fail.get("key", "")).strip()
                or (isinstance(on_fail_raw, dict) and on_fail_raw.get("key") is None)
            )
        ):
            try:
                import logging

                logging.getLogger("rule_migration").warning(
                    "規則「%s」動作後驗證 on_fail=key 缺少有效按鍵，已改為 advance: %r",
                    rule_name or "?",
                    raw,
                )
            except Exception:
                pass
            on_fail = {"action": "advance"}
    result: dict = {
        "type": vtype,
        "preset": preset,
        "expect": expect,
        "roi": roi,
        "timeout_ms": timeout_ms,
        "poll_interval_ms": poll_ms,
        "delay_before_ms": delay_ms,
        "retries": retries,
        "retry_delay_ms": retry_delay_ms,
    }
    result["on_fail"] = on_fail
    if vtype == "detect":
        result["text"] = str(raw.get("text", "")).strip()
        result["match_mode"] = str(raw.get("match_mode", "fuzzy"))
        result["fuzzy_threshold"] = max(
            0.0, min(1.0, _as_float(raw.get("fuzzy_threshold", 0.8), 0.8))
        )
        if not result["text"]:
            return None
    else:  # match_image
        result["template"] = str(raw.get("template", "")).strip()
        result["template_data"] = str(raw.get("template_data", ""))
        result["threshold"] = max(0.0, min(1.0, _as_float(raw.get("threshold", 0.8), 0.8)))
        result["match_color"] = bool(raw.get("match_color", False))
        result["color_tolerance"] = max(0, min(255, _as_int(raw.get("color_tolerance", 100), 100)))
        cm = _sanitize_color_mask(raw.get("color_mask"))
        if cm:
            result["color_mask"] = cm
        cs = _sanitize_capture_size(raw.get("capture_size"))
        if cs:
            result["capture_size"] = cs
        if not result["template"].strip() and not result["template_data"].strip():
            return None
    return result


def _normalize_step_params(step_type: str, params: dict | None, rule_name: str = "") -> dict:
    base = deepcopy(_STEP_DEFAULTS.get(step_type, {}))
    params = params if isinstance(params, dict) else {}
    base.update(params)

    # Drag 舊 PX offset 偵測：必須在 normalize 覆寫之前，依據原始 params 判斷，
    # 並將 _migration marker 寫入 params，貫穿 serialize / save / reload / 複製。
    if step_type == "drag":
        _legacy_marker = _detect_drag_legacy_marker(params)
        if _legacy_marker is not None:
            base["_migration"] = _legacy_marker["_migration"]

    # verify is action-only optional; normalize after base merge — 僅動作四類，match_image 已收斂（追溯 ADR-0005）
    if step_type in ("click", "key", "drag", "scroll"):
        raw_verify = params.get("verify", None)
        if raw_verify is not None:
            v = _normalize_verify(raw_verify, rule_name=rule_name)
            if v is None:
                # invalid verify (e.g. verify+stop or missing text/template) -> drop with log
                base.pop("verify", None)
                try:
                    import logging

                    logging.getLogger("rule_migration").warning(
                        "規則「%s」動作後驗證無效已移除（verify+stop 不支援或缺文字/圖片）: %r",
                        rule_name or "?",
                        raw_verify,
                    )
                except Exception:
                    pass
            else:
                base["verify"] = v
        elif "verify" in base:
            base.pop("verify", None)
    else:
        if params.get("verify", None) is not None:
            try:
                import logging

                logging.getLogger("rule_migration").warning(
                    "規則「%s」步驟類型 %s 不支援動作後驗證，已移除: %r",
                    rule_name or "?",
                    step_type,
                    params.get("verify"),
                )
            except Exception:
                pass
        base.pop("verify", None)

    if step_type == "detect":
        base["text"] = str(base.get("text", "")).strip()
        base["roi"] = _sanitize_roi(base.get("roi"))
        base["match_mode"] = str(base.get("match_mode", "fuzzy"))
        base["fuzzy_threshold"] = max(
            0.0, min(1.0, _as_float(base.get("fuzzy_threshold", 0.8), 0.8))
        )
        base["on_fail"] = _normalize_on_fail(base.get("on_fail", "stop"), allow_skip=True)
        base["after_delay_ms"] = max(0, _as_int(base.get("after_delay_ms", 0), 0))
    elif step_type in ("click", "drag"):
        base["target"] = str(base.get("target", "text_center"))
        base["x"] = _as_float(base.get("x", 0), 0)
        base["y"] = _as_float(base.get("y", 0), 0)
        base["button"] = str(base.get("button", "left"))
        base["hold_ms"] = max(0, _as_int(base.get("hold_ms", 0), 0))
        base["after_delay_ms"] = max(0, _as_int(base.get("after_delay_ms", 0), 0))
        if step_type == "click":
            base["random_offset"] = max(0, _as_int(base.get("random_offset", 3), 3))
        else:
            # drag：不再自動注入 dx/dy 預設。raw dx/dy 若存在已由 base.update(params)
            # 保留（不自動改成 0、不換算、不刪除）；不存在則不補值。
            pass
    elif step_type == "key":
        base["key"] = str(base.get("key", ""))
        base["hold_ms"] = max(0, _as_int(base.get("hold_ms", 0), 0))
        base["after_delay_ms"] = max(0, _as_int(base.get("after_delay_ms", 0), 0))
    elif step_type == "scroll":
        base["direction"] = str(base.get("direction", "WheelDown"))
        base["amount"] = max(1, _as_int(base.get("amount", 1), 1))
        base["delay_ms"] = max(0, _as_int(base.get("delay_ms", 30), 30))
        base["after_delay_ms"] = max(0, _as_int(base.get("after_delay_ms", 0), 0))
    elif step_type == "wait":
        base["ms"] = max(0, _as_int(base.get("ms", 500), 500))
    elif step_type == "jump":
        base["rule_id"] = str(base.get("rule_id", ""))
    elif step_type == "compare":
        base["roi"] = _sanitize_roi(base.get("roi"))
        base["pattern"] = str(base.get("pattern", r"-?\d+\.?\d*"))
        base["operator"] = str(base.get("operator", ">="))
        # 無效值（NaN/±Infinity/null）→ None：執行期據此安全失敗，不可用 0.0 代替
        base["value"] = _as_optional_float(base.get("value", 0.0))
        base["on_fail"] = _normalize_on_fail(base.get("on_fail", "stop"), allow_skip=True)
    elif step_type == "sum":
        base["roi"] = _sanitize_roi(base.get("roi"))
    elif step_type == "match_image":
        base["template"] = str(base.get("template", "")).strip()
        base["template_data"] = str(base.get("template_data", ""))
        base["roi"] = _sanitize_roi(base.get("roi"))
        base["threshold"] = max(0.0, min(1.0, _as_float(base.get("threshold", 0.8), 0.8)))
        base["match_color"] = bool(base.get("match_color", False))
        base["color_tolerance"] = max(0, min(255, _as_int(base.get("color_tolerance", 100), 100)))
        cm = _sanitize_color_mask(base.get("color_mask"))
        if cm:
            base["color_mask"] = cm
        else:
            base.pop("color_mask", None)
        base["on_fail"] = _normalize_on_fail(base.get("on_fail", "stop"), allow_skip=True)
        base["after_delay_ms"] = max(0, _as_int(base.get("after_delay_ms", 0), 0))
        cs = _sanitize_capture_size(base.pop("capture_size", None))
        if cs:
            base["capture_size"] = cs
        if base["template"] and not base["template_data"]:
            p = Path(base["template"])
            if p.exists():
                import base64 as _b64

                import cv2 as _cv2

                _tmp_img = _cv2.imread(str(p), _cv2.IMREAD_COLOR)
                if _tmp_img is not None:
                    _, _buf = _cv2.imencode(".png", _tmp_img)
                    base["template_data"] = _b64.b64encode(_buf).decode("ascii")
    return base


def _parse_depends_on(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value:
        return [value]
    return []


def _build_detect_params(old: dict) -> dict:
    if "match_mode" in old:
        match_mode_ = str(old["match_mode"])
    elif "fuzzy" in old:
        match_mode_ = "fuzzy" if bool(old["fuzzy"]) else "contains"
    else:
        match_mode_ = "contains"
    on_fail = old.get("on_fail", "stop")
    if isinstance(on_fail, dict):
        action = str(on_fail.get("action", "stop"))
        if action == "key":
            on_fail = {"action": "key", "key": str(on_fail.get("key", ""))}
        else:
            on_fail = "stop"
    else:
        on_fail = str(on_fail) if str(on_fail) in ("key", "stop") else "stop"
    return {
        "text": str(old.get("target_text", "")).strip(),
        "roi": _sanitize_roi(old.get("roi")),
        "match_mode": match_mode_,
        "fuzzy_threshold": max(0.0, min(1.0, _as_float(old.get("fuzzy_threshold", 0.8), 0.8))),
        "on_fail": on_fail,
    }


def _build_confirm_action(old: dict) -> dict:
    if str(old.get("confirm_action_type", "key")) == "click":
        return {
            "type": "click",
            "x": _as_int(old.get("confirm_x", 0), 0),
            "y": _as_int(old.get("confirm_y", 0), 0),
            "button": str(old.get("click_button", "left")),
        }
    return {"type": "key", "key": str(old.get("confirm_key", ""))}


def _migrate_v1_to_v2(old: dict) -> dict:
    steps: list[dict] = []

    if str(old.get("rule_type", "trigger")) == "compare":
        if str(old.get("target_text", "")).strip():
            steps.append({"type": "detect", "params": _build_detect_params(old)})

        confirm_action = _build_confirm_action(old)
        if confirm_action["type"] == "click":
            steps.append({"type": "click", "params": confirm_action})
        elif confirm_action.get("key", ""):
            steps.append({"type": "key", "params": confirm_action})
    else:
        steps.append({"type": "detect", "params": _build_detect_params(old)})

        sub_text = str(old.get("sub_target_text", "")).strip()
        if sub_text:
            sub_roi = _sanitize_roi(old.get("sub_roi"))
            if all(sub_roi.get(k, 0) == 0 for k in ("x", "y", "w", "h")):
                sub_roi = _sanitize_roi(old.get("roi"))
            sub_params = _build_detect_params(old)
            sub_params["text"] = sub_text
            sub_params["roi"] = sub_roi
            steps.append({"type": "detect", "params": sub_params})

        if str(old.get("action_type", "click")) == "key" and str(old.get("key", "")):
            steps.append({"type": "key", "params": {"key": str(old.get("key", ""))}})
        else:
            steps.append(
                {
                    "type": "click",
                    "params": {
                        "target": str(old.get("click_position", "text_center")),
                        "x": _as_int(old.get("custom_x", 0), 0),
                        "y": _as_int(old.get("custom_y", 0), 0),
                        "button": str(old.get("click_button", "left")),
                        "random_offset": max(0, _as_int(old.get("random_offset", 3), 3)),
                    },
                }
            )

        post_delay = max(0, _as_int(old.get("post_delay_ms", 0), 0))
        if post_delay > 0:
            steps.append({"type": "wait", "params": {"ms": post_delay}})

    return {
        "id": str(old.get("id", "")),
        "name": str(old.get("name", "")),
        "enabled": bool(old.get("enabled", True)),
        "steps": steps,
    }


def migrate_v2_to_v3(data: dict) -> dict:
    mode = str(data.get("run_mode", "once"))
    if mode not in ("once", "repeat", "loop"):
        mode = "once"
    repeat_times = _as_int(data.get("repeat_times", 1), 1)
    between_rounds_sec = _as_int(data.get("between_rounds_sec", 0), 0)

    normal_ids = []
    for r in data.get("rules", []):
        if isinstance(r, dict) and not r.get("background", False):
            normal_ids.append(str(r.get("id", "")))

    data["groups"] = [
        {
            "id": "__default__",
            "name": "Default",
            "mode": mode,
            "repeat_times": repeat_times,
            "between_rounds_sec": between_rounds_sec,
            "rule_ids": normal_ids,
            "order": "sequential",
        }
    ]
    data.pop("run_mode", None)
    data.pop("repeat_times", None)
    data.pop("between_rounds_sec", None)
    return data


def _migrate_roi_to_ratio(data: dict) -> dict:
    cap = data.get("capture_size")
    if not cap or len(cap) < 2:
        return data
    W, H = cap[0], cap[1]
    if W <= 0 or H <= 0:
        return data

    for rule in data.get("rules", []):
        for step in rule.get("steps", []):
            if step.get("type") in ("detect", "compare", "match_image"):
                if "roi" in step.get("params", {}):
                    roi = step["params"]["roi"]
                    x, y, w, h = roi.get("x", 0), roi.get("y", 0), roi.get("w", 0), roi.get("h", 0)
                    if not (x <= 1.0 and y <= 1.0 and w <= 1.0 and h <= 1.0):
                        step["params"]["roi"] = {"x": x / W, "y": y / H, "w": w / W, "h": h / H}
            elif step.get("type") == "click":
                p = step.get("params", {})
                px, py = p.get("x", 0), p.get("y", 0)
                if not (px <= 1.0 and py <= 1.0):
                    step["params"] = {**p, "x": px / W, "y": py / H}
            elif step.get("type") == "drag":
                p = step.get("params", {})
                px, py = p.get("x", 0), p.get("y", 0)
                if px > 1.0 or py > 1.0:
                    step["params"] = {**p, "x": px / W, "y": py / H}
                ex, ey = p.get("end_x"), p.get("end_y")
                if (
                    ex is not None
                    and ey is not None
                    and not isinstance(ex, bool)
                    and not isinstance(ey, bool)
                    and isinstance(ex, (int, float))
                    and isinstance(ey, (int, float))
                ):
                    try:
                        ex_f, ey_f = float(ex), float(ey)
                    except (OverflowError, ValueError):
                        ex_f = ey_f = float("nan")
                    if math.isfinite(ex_f) and math.isfinite(ey_f) and (ex_f > 1.0 or ey_f > 1.0):
                        # 以最新的 step["params"] 為基礎，否則會蓋掉上面剛算好的 x/y
                        step["params"] = {
                            **step["params"],
                            "end_x": ex_f / W,
                            "end_y": ey_f / H,
                        }
    data["ratio_coords"] = True
    return data


def _migrate_roi_coord(data: dict) -> dict:
    for rule in data.get("rules", []):
        for step in rule.get("steps", []):
            if step.get("type") not in ("detect", "compare", "match_image"):
                continue
            roi = step.get("params", {}).get("roi", {})
            if not isinstance(roi, dict):
                continue
            if "roi_coord" in roi:
                continue
            x = roi.get("x", 0)
            if not (isinstance(x, (int, float)) and x <= 1.0 and x >= 0):
                continue
            roi["roi_coord"] = "client"
    return data
