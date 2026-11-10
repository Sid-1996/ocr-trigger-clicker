import copy
import json
import sys
import tempfile
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from _loader import load_sibling  # noqa: E402
from core.rule_models import Rule, Step  # noqa: E402

_migration = load_sibling("rule_migration", "core/rule_migration.py")
_normalize_step_params = _migration._normalize_step_params
_validate_drag_endpoint = _migration.validate_drag_endpoint
_detect_drag_legacy_marker = _migration._detect_drag_legacy_marker
_STEP_DEFAULTS = _migration._STEP_DEFAULTS

_serial = load_sibling("rule_serialization", "core/rule_serialization.py")
_rule_to_dict = _serial._rule_to_dict
_dict_to_rule = _serial._dict_to_rule
load_rules = _serial.load_rules
save_rules = _serial.save_rules

_ml_mod = load_sibling("main_loop", "core/05_main_loop.py")
resolve_drag_end = _ml_mod.resolve_drag_end


# ── Raw JSON legacy 偵測（在 normalize 覆寫之前判斷）──


def test_legacy_detection_empty_no_marker():
    out = _normalize_step_params("drag", {})
    assert "_migration" not in out


def test_legacy_detection_dx0_dy0():
    out = _normalize_step_params("drag", {"dx": 0, "dy": 0})
    assert out["_migration"] == {
        "kind": "drag_endpoint",
        "status": "needs_repair",
        "reason": "legacy_px_offset",
    }


def test_legacy_detection_dx30_dy20():
    out = _normalize_step_params("drag", {"dx": 30, "dy": 20})
    assert out["_migration"]["reason"] == "legacy_px_offset"


def test_legacy_detection_only_dx_incomplete():
    out = _normalize_step_params("drag", {"dx": 30})
    assert out["_migration"]["reason"] == "incomplete_legacy_offset"


def test_legacy_detection_only_dy_incomplete():
    out = _normalize_step_params("drag", {"dy": 20})
    assert out["_migration"]["reason"] == "incomplete_legacy_offset"


def test_legacy_detection_complete_end_no_marker():
    out = _normalize_step_params("drag", {"end_x": 0.5, "end_y": 0.6})
    assert "_migration" not in out


def test_legacy_detection_only_end_x_no_marker():
    out = _normalize_step_params("drag", {"end_x": 0.5})
    assert "_migration" not in out


def test_legacy_detection_only_end_y_no_marker():
    out = _normalize_step_params("drag", {"end_y": 0.6})
    assert "_migration" not in out


def test_legacy_detection_mixed():
    out = _normalize_step_params("drag", {"dx": 0, "dy": 0, "end_x": 0.5, "end_y": 0.6})
    assert out["_migration"]["reason"] == "mixed_legacy_and_endpoint"


def test_legacy_detection_invalid_dx():
    out = _normalize_step_params("drag", {"dx": "bad"})
    assert out["_migration"]["reason"] == "invalid_legacy_offset"


def test_legacy_detection_invalid_dy():
    out = _normalize_step_params("drag", {"dy": "bad"})
    assert out["_migration"]["reason"] == "invalid_legacy_offset"


def test_illegal_end_not_silently_fixed():
    out = _normalize_step_params("drag", {"end_x": "bad", "end_y": 0.3})
    assert out.get("end_x") == "bad"
    assert out.get("end_y") == 0.3
    assert "_migration" not in out


def test_detect_drag_legacy_marker_return_shape():
    assert _detect_drag_legacy_marker({"dx": 30, "dy": 20}) == {
        "_migration": {
            "kind": "drag_endpoint",
            "status": "needs_repair",
            "reason": "legacy_px_offset",
        }
    }
    assert _detect_drag_legacy_marker({"end_x": 0.5, "end_y": 0.6}) is None


# ── Marker 持久化 ──


def test_marker_valid_not_overwritten():
    """合法 marker reason 不得被任意覆蓋（rule 8）。"""
    raw = {
        "dx": 30,
        "dy": 20,
        "_migration": {
            "kind": "drag_endpoint",
            "status": "needs_repair",
            "reason": "legacy_px_offset",
        },
    }
    out = _normalize_step_params("drag", raw)
    assert out["_migration"]["reason"] == "legacy_px_offset"


def test_marker_invalid_replaced_safe():
    """marker 結構不合法時不靜默當作沒有問題，改為安全的 needs_repair。"""
    raw = {"dx": 30, "dy": 20, "_migration": {"kind": "drag_endpoint", "status": "weird"}}
    out = _normalize_step_params("drag", raw)
    assert out["_migration"]["reason"] == "legacy_px_offset"


def test_marker_serialize_reload_roundtrip(tmp_path):
    rule = Rule(
        id="r1",
        name="R1",
        enabled=True,
        steps=[
            Step(type="drag", params={"target": "custom", "x": 0.2, "y": 0.3, "dx": 30, "dy": 20})
        ],
    )
    # Normalize first so marker is added to params
    rule.steps[0].params = _normalize_step_params("drag", rule.steps[0].params, rule_name="test")
    d = _rule_to_dict(rule)
    raw_params = d["steps"][0]["params"]
    assert raw_params["_migration"]["reason"] == "legacy_px_offset"

    p = Path(tempfile.mkdtemp()) / "task.json"
    assert save_rules([rule], str(p)) is True
    loaded = load_rules(str(p))
    assert len(loaded) == 1
    assert loaded[0].steps[0].params["_migration"]["reason"] == "legacy_px_offset"
    assert loaded[0].steps[0].params.get("dx") == 30
    assert loaded[0].steps[0].params.get("dy") == 20
    assert loaded[0].steps[0].params.get("end_x") is None


def test_marker_step_copy():
    rule = _dict_to_rule(
        {
            "id": "r",
            "name": "R",
            "enabled": True,
            "steps": [{"type": "drag", "params": {"dx": 30, "dy": 20}}],
        }
    )
    step_copy = copy.deepcopy(rule.steps[0])
    assert step_copy.params["_migration"]["reason"] == "legacy_px_offset"


def test_marker_rule_copy():
    rule = _dict_to_rule(
        {
            "id": "r",
            "name": "R",
            "enabled": True,
            "steps": [{"type": "drag", "params": {"dx": 30, "dy": 20}}],
        }
    )
    rule_copy = copy.deepcopy(rule)
    assert rule_copy.steps[0].params["_migration"]["reason"] == "legacy_px_offset"


def test_marker_export_import_path(tmp_path):
    """匯出路徑（raw JSON 複製）保留 step.params 含 marker。"""
    rule = Rule(
        id="r1",
        name="R1",
        enabled=True,
        steps=[Step(type="drag", params={"dx": 30, "dy": 20})],
    )
    # Normalize first so marker is added to params (marker is built in _normalize_step_params)
    rule.steps[0].params = _normalize_step_params("drag", rule.steps[0].params, rule_name="test")
    d = {"rules": [_rule_to_dict(rule)]}
    dest = Path(tempfile.mkdtemp()) / "exported.json"
    dest.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["rules"][0]["steps"][0]["params"]["_migration"]["reason"] == "legacy_px_offset"
    reloaded = _dict_to_rule(data["rules"][0])
    assert reloaded.steps[0].params["_migration"]["reason"] == "legacy_px_offset"


# ── Drag 終點資料驗證 ──


def test_validation_valid():
    r = _validate_drag_endpoint({"end_x": 0.5, "end_y": 0.6})
    assert r["status"] == "valid"
    assert r["reason"] == "valid"


def test_validation_unset():
    r = _validate_drag_endpoint({})
    assert r["status"] == "unset"
    assert r["reason"] == "unset"


def test_validation_incomplete_end_x():
    r = _validate_drag_endpoint({"end_x": 0.5})
    assert r["status"] == "incomplete"


def test_validation_incomplete_end_y():
    r = _validate_drag_endpoint({"end_y": 0.5})
    assert r["status"] == "incomplete"


def test_validation_invalid_numeric():
    r = _validate_drag_endpoint({"end_x": "bad", "end_y": 0.5})
    assert r["status"] == "invalid"


def test_validation_invalid_nan_inf():
    r = _validate_drag_endpoint({"end_x": float("nan"), "end_y": 0.5})
    assert r["status"] == "invalid"
    r = _validate_drag_endpoint({"end_x": 0.5, "end_y": float("inf")})
    assert r["status"] == "invalid"


def test_validation_out_of_range():
    r = _validate_drag_endpoint({"end_x": 1.5, "end_y": 0.5})
    assert r["status"] == "invalid"
    assert r["reason"] == "out_of_range"
    r = _validate_drag_endpoint({"end_x": -0.1, "end_y": 0.5})
    assert r["status"] == "invalid"


def test_validation_invalid_end_roi_coord():
    r = _validate_drag_endpoint({"end_x": 0.5, "end_y": 0.5, "end_roi_coord": "bad"})
    assert r["status"] == "invalid"
    assert r["reason"] == "invalid_end_roi_coord"


def test_validation_needs_repair_marker():
    r = _validate_drag_endpoint(
        {
            "_migration": {
                "kind": "drag_endpoint",
                "status": "needs_repair",
                "reason": "legacy_px_offset",
            }
        }
    )
    assert r["status"] == "needs_repair"
    assert r["reason"] == "legacy_px_offset"


def test_validation_mixed_legacy_new():
    r = _validate_drag_endpoint({"dx": 0, "dy": 0, "end_x": 0.5, "end_y": 0.6})
    assert r["status"] == "needs_repair"
    assert r["reason"] == "mixed_legacy_and_endpoint"


def test_validation_needs_repair_not_confused_with_incomplete():
    """unset/incomplete/invalid 不等於 needs_repair。"""
    assert _validate_drag_endpoint({})["status"] != "needs_repair"
    assert _validate_drag_endpoint({"end_x": 0.5})["status"] != "needs_repair"
    assert _validate_drag_endpoint({"end_x": "bad", "end_y": 0.5})["status"] != "needs_repair"


def test_validation_legacy_reason_matches_detector():
    """validator 與 detector 的分類必須一致（GUI 以 validator 為唯一判定來源）。

    「只缺一軸」是 incomplete，不是 invalid（欄位不存在 ≠ 值不合法）；
    「有值但不合法」才是 invalid。兩邊不一致會讓 GUI 顯示錯誤的原因。
    """
    cases = [
        ({"dx": 30}, "incomplete_legacy_offset"),
        ({"dy": 20}, "incomplete_legacy_offset"),
        ({"dx": 30, "dy": 20}, "legacy_px_offset"),
        ({"dx": "bad", "dy": 20}, "invalid_legacy_offset"),
        ({"dx": 30, "dy": None}, "invalid_legacy_offset"),
        ({"dx": 30, "dy": 20, "end_x": 0.5, "end_y": 0.6}, "mixed_legacy_and_endpoint"),
    ]
    for params, reason in cases:
        detected = _detect_drag_legacy_marker(dict(params))
        detected_reason = detected["_migration"]["reason"] if detected else None
        assert _validate_drag_endpoint(dict(params))["reason"] == reason
        assert detected_reason == reason


# ── PX 終點退役 ──


def test_new_drag_no_dx_dy_injection():
    out = _normalize_step_params("drag", {})
    assert "dx" not in out
    assert "dy" not in out


def test_resolve_drag_end_no_dx_dy_fallback():
    p = {"end_x": None, "end_y": None, "dx": 30, "dy": 40}
    try:
        resolve_drag_end(p, (100, 200), lambda px, py, roi: (px, py))
        raise AssertionError("unset drag end must raise, not fall back to dx/dy")
    except ValueError:
        pass


def test_old_dx_dy_not_auto_converted():
    out = _normalize_step_params("drag", {"dx": 30, "dy": 20})
    assert out.get("dx") == 30
    assert out.get("dy") == 20
    assert out.get("end_x") is None
    assert out.get("end_y") is None
    assert out["_migration"]["reason"] == "legacy_px_offset"


def test_other_step_types_unaffected():
    assert _STEP_DEFAULTS["scroll"] == {
        "direction": "WheelDown",
        "amount": 1,
        "delay_ms": 30,
        "after_delay_ms": 0,
    }
    assert "dx" not in _STEP_DEFAULTS["scroll"]
    assert "dy" not in _STEP_DEFAULTS["scroll"]
    assert _STEP_DEFAULTS["click"]["random_offset"] == 3
    assert _STEP_DEFAULTS["click"]["button"] == "left"
