from _loader import load_sibling

RuleMig = load_sibling("rule_migration", "core/rule_migration.py")
Ser = load_sibling("rule_serialization", "core/rule_serialization.py")
Models = load_sibling("rule_models", "core/rule_models.py")
MainLoopMod = load_sibling("main_loop", "core/05_main_loop.py")

Rule = Models.Rule
Step = Models.Step


def test_should_warn_loop_verify():
    f = MainLoopMod.should_warn_loop_verify
    # loop + long → warn
    assert f("loop", 10000, "long") is True
    # loop + 手寫 timeout 達 8s（preset 缺席）→ warn
    assert f("loop", 8000, "") is True
    assert f("loop", None, "long") is True
    # loop + 中/短 → quiet
    assert f("loop", 5000, "medium") is False
    assert f("loop", 2000, "short") is False
    # 非 loop 群組一律 quiet
    assert f("once", 10000, "long") is False
    assert f("repeat", 10000, "long") is False
    assert f("", 10000, "long") is False
    # 髒輸入不崩
    assert f("loop", "bad", "medium") is False
    assert f("loop", 0, "") is False


def test_verify_normalize_detect_valid():
    v = {
        "type": "detect",
        "text": " 新場景文字 ",
        "roi": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.3, "roi_coord": "client"},
        "timeout_ms": 3000,
        "poll_interval_ms": 300,
        "delay_before_ms": 0,
        "on_fail": {"action": "notify", "message": "fail", "stop_groups": []},
    }
    nv = RuleMig._normalize_verify(v)
    assert nv is not None
    assert nv["type"] == "detect"
    assert nv["text"] == "新場景文字"
    assert nv["roi"]["roi_coord"] == "client"
    assert nv["timeout_ms"] == 3000
    assert nv["on_fail"]["action"] == "notify"


def test_verify_normalize_match_image_valid():
    v = {
        "type": "match_image",
        "template_data": "abc==",
        "threshold": 0.85,
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
        "timeout_ms": 5000,
        "on_fail": {"action": "advance"},
    }
    nv = RuleMig._normalize_verify(v)
    assert nv is not None
    assert nv["type"] == "match_image"
    assert nv["threshold"] == 0.85


def test_verify_roundtrip_step_params():
    # Click with verify should survive _normalize_step_params
    params = {
        "target": "custom",
        "x": 0.5,
        "y": 0.5,
        "after_delay_ms": 250,
        "verify": {
            "type": "detect",
            "text": "戰鬥",
            "roi": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5, "roi_coord": "client"},
            "timeout_ms": 3000,
            "poll_interval_ms": 300,
            "delay_before_ms": 0,
            "on_fail": {"action": "notify", "message": "未進戰鬥"},
        },
    }
    out = RuleMig._normalize_step_params("click", params)
    assert out["verify"]["text"] == "戰鬥"
    assert out["verify"]["roi"]["x"] == 0.1
    assert out["after_delay_ms"] == 250


def test_verify_clamp():
    v = {
        "type": "detect",
        "text": "a",
        "timeout_ms": 99999,
        "poll_interval_ms": 1,
        "delay_before_ms": 99999,
    }
    nv = RuleMig._normalize_verify(v)
    assert nv["timeout_ms"] == 30000
    assert nv["poll_interval_ms"] == 50
    assert nv["delay_before_ms"] == 5000


def test_verify_plus_stop_invalid():
    for raw in [
        {"type": "detect", "text": "hi", "on_fail": "stop"},
        {"type": "detect", "text": "hi", "on_fail": {"action": "stop"}},
        {"type": "match_image", "template_data": "abc", "on_fail": "stop"},
    ]:
        assert RuleMig._normalize_verify(raw) is None
        # also dropped at step level
        out = RuleMig._normalize_step_params("click", {"verify": raw})
        assert "verify" not in out


def test_verify_invalid_empty_text_template():
    assert RuleMig._normalize_verify({"type": "detect", "text": "   "}) is None
    assert (
        RuleMig._normalize_verify({"type": "match_image", "template_data": "   ", "template": ""})
        is None
    )
    assert RuleMig._normalize_verify({"type": "detect"}) is None
    assert RuleMig._normalize_verify({"type": "unknown", "text": "hi"}) is None


def test_verify_allowed_on_parent_only():
    # detect step must not keep verify
    out = RuleMig._normalize_step_params(
        "detect", {"text": "hi", "verify": {"type": "detect", "text": "x"}}
    )
    assert "verify" not in out
    # match_image must not keep verify (ADR-0005 收斂至動作四類)
    out_mi = RuleMig._normalize_step_params(
        "match_image",
        {
            "template_data": "abc==",
            "verify": {"type": "detect", "text": "x"},
        },
    )
    assert "verify" not in out_mi
    # wait must not
    out2 = RuleMig._normalize_step_params(
        "wait", {"ms": 100, "verify": {"type": "detect", "text": "x"}}
    )
    assert "verify" not in out2


def test_match_image_verify_dropped_on_normalize():
    # 舊任務若誤存 match_image.verify，normalize 直接丟棄（開發期無遷移期）
    out = RuleMig._normalize_step_params(
        "match_image",
        {
            "template_data": "abc==",
            "threshold": 0.8,
            "verify": {
                "type": "match_image",
                "template_data": "xyz==",
                "threshold": 0.8,
                "timeout_ms": 3000,
            },
        },
    )
    assert "verify" not in out
    # _normalize_verify 本身仍合法（僅 step 層收斂），但 step 層已攔截
    assert RuleMig._normalize_verify({"type": "match_image", "template_data": "xyz=="}) is not None


def test_backward_compat_no_verify():
    # old task without verify stays unchanged
    out = RuleMig._normalize_step_params("click", {"target": "custom", "x": 0.2, "y": 0.3})
    assert "verify" not in out
    assert out["target"] == "custom"


def test_serialization_roundtrip():
    rule = Rule(
        id="r1",
        name="抽抽樂串",
        enabled=True,
        steps=[
            Step(
                type="detect",
                params={
                    "text": "抽抽樂",
                    "roi": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "roi_coord": "client"},
                },
            ),
            Step(
                type="click",
                params={
                    "target": "custom",
                    "x": 0.5,
                    "y": 0.5,
                    "verify": {
                        "type": "detect",
                        "text": "新的場景文字",
                        "roi": {"x": 0.3, "y": 0.4, "w": 0.2, "h": 0.2, "roi_coord": "client"},
                        "timeout_ms": 3000,
                        "poll_interval_ms": 300,
                        "delay_before_ms": 0,
                        "on_fail": {"action": "notify", "message": "驗證失敗"},
                    },
                },
            ),
        ],
    )
    # simulate save/load via _normalize_step_params roundtrip
    for s in rule.steps:
        norm = RuleMig._normalize_step_params(s.type, s.params)
        s.params = norm
    assert rule.steps[1].params["verify"]["text"] == "新的場景文字"
    assert rule.steps[1].params["verify"]["roi"]["x"] == 0.3
    assert rule.steps[0].params["roi"]["x"] == 0.1
    # verify ROI independent from detect ROI
    assert rule.steps[0].params["roi"]["x"] != rule.steps[1].params["verify"]["roi"]["x"]


def test_verify_gui_independent_roi_smoke():
    # headless verify widget independent ROI
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    _VerifyWidget = m._VerifyWidget
    counter = [0]

    class Sig:
        def emit(self):
            counter[0] += 1

    parent = type("P", (), {})()
    parent.steps_changed = Sig()
    step = Step(type="click", params={})
    w = _VerifyWidget(parent, step)
    w.show()
    app.processEvents()
    # enable verify and pick different ROI
    w._enable.setChecked(True)
    app.processEvents()
    assert not w._container.isHidden()
    # simulate picking verify ROI B different from detect ROI A
    step_detect = Step(
        type="detect",
        params={
            "text": "抽抽樂",
            "roi": {"x": 0.01, "y": 0.01, "w": 0.2, "h": 0.2, "roi_coord": "client"},
        },
    )
    # verify ROI B
    w._step.params["verify"]["roi"] = {
        "x": 0.3,
        "y": 0.4,
        "w": 0.2,
        "h": 0.2,
        "roi_coord": "client",
    }
    w._update_roi_label()
    assert step_detect.params["roi"]["x"] == 0.01
    assert w._step.params["verify"]["roi"]["x"] == 0.3
    # toggle not emit
    assert counter[0] == 0
    w.deleteLater()
    QApplication.instance().processEvents()


def test_pick_roi_callback_dict():
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841 - keep ref
    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    _VerifyWidget = m._VerifyWidget

    def roi_dict():
        return {"x": 0.11, "y": 0.22, "w": 0.33, "h": 0.44, "roi_coord": "client"}

    parent = type("P", (), {"steps_changed": type("S", (), {"emit": lambda self: None})()})()
    step = Step(type="click", params={})
    w = _VerifyWidget(parent, step, roi_cb=roi_dict)
    w._pick_roi()
    assert w._step.params["verify"]["roi"]["x"] == 0.11
    assert w._step.params["verify"]["roi"]["roi_coord"] == "client"
    w.deleteLater()
    from PyQt6.QtWidgets import QApplication as _QA

    _QA.instance().processEvents()


def test_pick_roi_callback_tuple():
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841
    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    _VerifyWidget = m._VerifyWidget

    def roi_tuple():
        return (0.2, 0.3, 0.1, 0.15)

    parent = type("P", (), {"steps_changed": type("S", (), {"emit": lambda self: None})()})()
    step = Step(type="click", params={})
    w = _VerifyWidget(parent, step, roi_cb=roi_tuple)
    w._pick_roi()
    assert abs(w._step.params["verify"]["roi"]["x"] - 0.2) < 1e-9
    assert w._step.params["verify"]["roi"]["roi_coord"] == "client"
    assert abs(w._step.params["verify"]["roi"]["h"] - 0.15) < 1e-9
    w.deleteLater()
    from PyQt6.QtWidgets import QApplication as _QA2

    _QA2.instance().processEvents()


def test_verify_match_mode_roundtrip():
    v = {
        "type": "detect",
        "text": "hi",
        "match_mode": "exact",
        "roi": {"x": 0, "y": 0, "w": 0, "h": 0},
    }
    nv = RuleMig._normalize_verify(v)
    assert nv["match_mode"] == "exact"
    # via GUI save
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841
    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    _VerifyWidget = m._VerifyWidget
    parent = type("P", (), {"steps_changed": type("S", (), {"emit": lambda self: None})()})()
    step = Step(
        type="click",
        params={
            "verify": {
                "type": "detect",
                "text": "hi",
                "match_mode": "exact",
                "fuzzy_threshold": 0.8,
            }
        },
    )
    w = _VerifyWidget(parent, step)
    w._enable.setChecked(True)
    idx = w._vf_match_mode.findData("exact")
    w._vf_match_mode.setCurrentIndex(idx)
    w._text.setText("hi")
    w.save()
    assert w._step.params["verify"]["match_mode"] == "exact"
    # normalize preserves
    nv2 = RuleMig._normalize_verify(w._step.params["verify"])
    assert nv2["match_mode"] == "exact"
    w.deleteLater()
    from PyQt6.QtWidgets import QApplication as _QA3

    _QA3.instance().processEvents()


def test_verify_fuzzy_threshold_roundtrip():
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841
    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    _VerifyWidget = m._VerifyWidget
    parent = type("P", (), {"steps_changed": type("S", (), {"emit": lambda self: None})()})()
    step = Step(type="click", params={})
    w = _VerifyWidget(parent, step)
    w._enable.setChecked(True)
    idx = w._vf_match_mode.findData("fuzzy")
    w._vf_match_mode.setCurrentIndex(idx)
    w._vf_fuzzy.setValue(0.65)
    w._text.setText("hello")
    w.save()
    assert abs(w._step.params["verify"]["fuzzy_threshold"] - 0.65) < 1e-9
    nv = RuleMig._normalize_verify(w._step.params["verify"])
    assert abs(nv["fuzzy_threshold"] - 0.65) < 1e-9
    w.deleteLater()
    from PyQt6.QtWidgets import QApplication as _QA4

    _QA4.instance().processEvents()


def test_invalid_template_data_not_crash():
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841
    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    _VerifyWidget = m._VerifyWidget
    parent = type("P", (), {"steps_changed": type("S", (), {"emit": lambda self: None})()})()
    # corrupted base64
    step = Step(
        type="click",
        params={
            "verify": {"type": "match_image", "template_data": "!!!not_base64!!!", "threshold": 0.8}
        },
    )
    w = _VerifyWidget(parent, step)
    # should not raise
    try:
        w._update_thumb()
    except Exception as e:
        assert False, f"_update_thumb crashed on invalid base64: {e}"
    # should fallback to clear
    assert w._thumb.pixmap() is None or w._thumb.pixmap().isNull()
    w.deleteLater()
    from PyQt6.QtWidgets import QApplication as _QA5

    _QA5.instance().processEvents()


_QT_APP_REF = None


def _make_verify_widget(step_idx=-1, step_count=0):
    global _QT_APP_REF
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    # ponytail: keep a global ref — a local-only QApplication wrapper may be
    # gc'd on helper return, taking the widget C++ tree with it.
    _QT_APP_REF = QApplication.instance() or QApplication([])
    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    parent = type("P", (), {"steps_changed": type("S", (), {"emit": lambda self: None})()})()
    step = Step(type="click", params={})
    w = m._VerifyWidget(parent, step, step_idx=step_idx, step_count=step_count)
    return w


def test_preset_change_preserves_hand_tuned_ms():
    w = _make_verify_widget()
    assert w._last_preset == "medium"
    # hand-tuned values differ from medium defaults (5000/300) → must survive
    w._timeout.setValue(3000)
    w._poll.setValue(150)
    w._preset.setCurrentIndex(w._preset.findData("long"))
    assert w._timeout.value() == 3000
    assert w._poll.value() == 150
    assert w._last_preset == "long"
    w.deleteLater()


def test_preset_change_follows_when_untouched():
    w = _make_verify_widget()
    assert (w._timeout.value(), w._poll.value()) == (5000, 300)
    w._preset.setCurrentIndex(w._preset.findData("long"))
    assert (w._timeout.value(), w._poll.value()) == (10000, 500)
    w._preset.setCurrentIndex(w._preset.findData("short"))
    assert (w._timeout.value(), w._poll.value()) == (2000, 100)
    w.deleteLater()


def _enable_verify(w):
    w._enable.setChecked(True)
    from PyQt6.QtWidgets import QApplication as _QA

    _QA.instance().processEvents()
    return w


def test_empty_text_save_keeps_draft_and_warns():
    w = _enable_verify(_make_verify_widget())
    w._text.setText("")
    assert w._validate_verify_input() is False
    # offscreen widget is never shown: assert explicit hidden flag + text
    assert not w._err_hint.isHidden() and w._err_hint.text() != ""
    w.save()
    # draft kept, not silently dropped
    assert isinstance(w._step.params.get("verify"), dict)
    assert w._step.params["verify"].get("text", "") == ""
    w.deleteLater()


def test_filled_text_save_writes_and_clears_hint():
    w = _enable_verify(_make_verify_widget())
    w._text.setText("戰鬥")
    assert w._validate_verify_input() is True
    assert w._err_hint.isHidden() and w._err_hint.text() == ""
    w.save()
    assert w._step.params["verify"]["text"] == "戰鬥"
    w.deleteLater()


def test_verify_on_fail_defaults_to_advance():
    w = _make_verify_widget()
    assert w._on_fail.currentData() == "advance"
    w.deleteLater()


def test_verify_advanced_toggle():
    w = _make_verify_widget()
    # offscreen: assert explicit hidden flag, not isVisible()
    assert w._vf_adv_container.isHidden()
    w._vf_adv_btn.click()
    assert not w._vf_adv_container.isHidden()
    assert "▼" in w._vf_adv_btn.text()
    w._vf_adv_btn.click()
    assert w._vf_adv_container.isHidden()
    assert "▶" in w._vf_adv_btn.text()
    w.deleteLater()


def _combo_datas(combo):
    return [combo.itemData(i) for i in range(combo.count())]


def test_on_fail_order_canonical():
    w = _make_verify_widget()
    assert _combo_datas(w._on_fail) == ["advance", "skip", "jump", "key", "notify"]
    w.deleteLater()


def test_detect_skip_roundtrip():
    global _QT_APP_REF
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    _QT_APP_REF = QApplication.instance() or QApplication([])
    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    # _DetectStepForm forwards parent_list to QWidget: pass None headless
    step = Step(type="detect", params={"text": "hi"})
    f = m._DetectStepForm(None, step, 0, None, step_count=3)
    assert _combo_datas(f._of_action) == ["stop", "advance", "skip", "jump", "key", "notify"]
    f._of_action.setCurrentIndex(f._of_action.findData("skip"))
    assert not f._of_skip_row.isHidden()
    f._of_skip_combo.setCurrentIndex(f._of_skip_combo.findData(1))
    f.save()
    assert step.params["on_fail"]["action"] == "skip"
    assert step.params["on_fail"]["skip_to"] == 1
    f.deleteLater()


def test_verify_skip_target_roundtrip():
    w = _make_verify_widget(step_idx=0, step_count=3)
    w._enable.setChecked(True)
    w._text.setText("hi")
    datas = [w._vf_skip_combo.itemData(i) for i in range(w._vf_skip_combo.count())]
    assert datas == [3, 1, 2]  # rule end, step 2, step 3 (forward-only)
    w._on_fail.setCurrentIndex(w._on_fail.findData("skip"))
    w._vf_skip_combo.setCurrentIndex(w._vf_skip_combo.findData(1))
    w.save()
    assert w._step.params["verify"]["on_fail"] == {"action": "skip", "skip_to": 1}
    w.deleteLater()


def test_verify_skip_legacy_9999_falls_back_to_rule_end():
    global _QT_APP_REF
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    _QT_APP_REF = QApplication.instance() or QApplication([])
    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    parent = type("P", (), {"steps_changed": type("S", (), {"emit": lambda self: None})()})()
    step = Step(
        type="click",
        params={
            "verify": {
                "type": "detect",
                "text": "hi",
                "on_fail": {"action": "skip", "skip_to": 9999},
            }
        },
    )
    w = m._VerifyWidget(parent, step, step_idx=0, step_count=3)
    assert w._vf_skip_combo.currentIndex() == 0
    w.save()
    assert w._step.params["verify"]["on_fail"]["skip_to"] == 3
    w.deleteLater()


def test_verify_notify_row_label_hidden_when_not_notify():
    # QFormLayout label and field are separate items: hiding the field must
    # hide the label too (previously left orphan "通知文字/停止群組" labels).
    w = _enable_verify(_make_verify_widget())
    w._text.setText("hi")
    w._on_fail.setCurrentIndex(w._on_fail.findData("advance"))
    lbl = w._vf_form.labelForField(w._vf_notify_msg)
    assert lbl is not None and lbl.isHidden()
    assert w._vf_form.labelForField(w._vf_notify_groups).isHidden()
    w._on_fail.setCurrentIndex(w._on_fail.findData("notify"))
    assert not w._vf_form.labelForField(w._vf_notify_msg).isHidden()
    assert not w._vf_notify_msg.isHidden()
    w.deleteLater()


def test_detect_notify_row_label_hidden_when_not_notify():
    global _QT_APP_REF
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    _QT_APP_REF = QApplication.instance() or QApplication([])
    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    step = Step(type="detect", params={"text": "hi"})
    f = m._DetectStepForm(None, step, 0, None, step_count=3)
    assert f._of_form.labelForField(f._of_notify_msg).isHidden()
    f._of_action.setCurrentIndex(f._of_action.findData("notify"))
    assert not f._of_form.labelForField(f._of_notify_msg).isHidden()
    f.deleteLater()


def test_pick_dialog_screen_relative_size():
    global _QT_APP_REF
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    _QT_APP_REF = QApplication.instance() or QApplication([])
    import numpy as np

    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    ag = QApplication.primaryScreen().availableGeometry()
    img = np.zeros((600, 800, 3), dtype=np.uint8)
    dlg = m._VerifyTextPickDialog(None, img, [])
    assert dlg.width() == max(820, int(ag.width() * 0.8))
    assert dlg.height() == max(560, int(ag.height() * 0.85))
    assert dlg._image_label.minimumWidth() >= 560
    from PyQt6.QtWidgets import QSizePolicy as _SP

    assert dlg._image_label.sizePolicy().horizontalPolicy() == _SP.Policy.Expanding
    dlg.deleteLater()


def test_pick_dialog_image_grows_with_label():
    # regression: pixmap was rendered once at construction size and never
    # re-rendered when the splitter stretched the label (image looked small
    # inside a big dialog). Read synchronously: QWidget.resize() delivers the
    # resize event immediately, before the splitter layout can reset it.
    global _QT_APP_REF
    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    _QT_APP_REF = QApplication.instance() or QApplication([])
    import numpy as np

    from _loader import load_sibling as _ls

    m = _ls("gui_main", "gui/06_gui_main.py")
    img = np.zeros((600, 800, 3), dtype=np.uint8)
    dlg = m._VerifyTextPickDialog(None, img, [])
    dlg.show()
    QApplication.instance().processEvents()
    QApplication.instance().processEvents()
    p1 = dlg._image_label.pixmap()
    assert p1 is not None and not p1.isNull()
    dlg._image_label.resize(1000, 700)
    p2 = dlg._image_label.pixmap()
    assert p2 is not None and not p2.isNull()
    assert p2.width() > p1.width()
    dlg.deleteLater()


def teardown_module(module):
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.processEvents()
            # do not delete QApplication itself; let process exit handle it
            # just ensure no pending deleteLater widgets remain
    except Exception:
        pass
