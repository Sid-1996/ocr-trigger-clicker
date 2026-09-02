from _loader import load_sibling

RuleCC = load_sibling(
    "rule_config_controller", "gui/rule_config_controller.py"
).RuleConfigController
SS = load_sibling("screenshot", "core/01_screenshot.py")


def test_calc_outer_size():
    assert SS._calc_outer_size(1600, 900, 16, 39) == (1616, 939)
    assert SS._calc_outer_size(800, 600, 0, 0) == (800, 600)
    # chrome diff is outer-client; check reverse
    c_w, c_h = 1600, 900
    chrome_w, chrome_h = 16, 39
    outer = SS._calc_outer_size(c_w, c_h, chrome_w, chrome_h)
    assert outer[0] - chrome_w == c_w
    assert outer[1] - chrome_h == c_h


def test_calc_centered_pos():
    # work 1920x1080, outer 1616x939 -> centered
    x, y = SS._calc_centered_pos(0, 0, 1920, 1080, 1616, 939)
    assert x == (1920 - 1616) // 2
    assert y == (1080 - 939) // 2
    # work offset (multi-monitor)
    x2, y2 = SS._calc_centered_pos(1920, 0, 1920, 1080, 1616, 939)
    assert x2 == 1920 + (1920 - 1616) // 2
    assert y2 == (1080 - 939) // 2
    # outer larger than work -> clamp to work origin
    x3, y3 = SS._calc_centered_pos(0, 0, 1920, 1080, 2000, 1200)
    assert x3 == 0
    assert y3 == 0


def test_rects_equal_fullscreen():
    # window covers monitor
    assert SS._rects_equal_fullscreen(0, 0, 1920, 1080, 0, 0, 1920, 1080) is True
    # window larger than monitor (overscan) also fullscreen
    assert SS._rects_equal_fullscreen(-1, -1, 1921, 1081, 0, 0, 1920, 1080) is True
    # window smaller -> not fullscreen
    assert SS._rects_equal_fullscreen(0, 0, 1600, 900, 0, 0, 1920, 1080) is False
    assert (
        SS._rects_equal_fullscreen(10, 10, 1930, 1090, 0, 0, 1920, 1080) is False
    )  # offset but same size not cover
    assert SS._rects_equal_fullscreen(0, 0, 1919, 1080, 0, 0, 1920, 1080) is False


def test_invalid_not_found():
    # bogus title should not crash, returns not_found / None
    assert SS.get_window_client_size("__NO_SUCH_WINDOW_9f3a__") is None
    assert SS.is_window_fullscreen("__NO_SUCH_WINDOW_9f3a__") is False
    assert SS.resize_window_to_client("__NO_SUCH_WINDOW_9f3a__", 1600, 900) == "not_found"
    assert SS.resize_window_to_client("__NO_SUCH_WINDOW_9f3a__", 0, 900) == "failed"
    assert SS.resize_window_to_client("__NO_SUCH_WINDOW_9f3a__", -1, 900) == "failed"


def test_setting_default_false(tmp_path):
    ctrl = RuleCC()

    # fake win with _config_path pointing to tmp
    class Win:
        _config_path = str(tmp_path / "config.json")

    w = Win()
    assert ctrl.get_setting(w, "auto_resize_standard", None) is False
    # also DEFAULTS
    assert ctrl.DEFAULTS["auto_resize_standard"] is False


def test_old_config_load_not_crash(tmp_path):
    import json

    cfg_path = tmp_path / "config.json"
    # old config without new key
    cfg_path.write_text(
        json.dumps({"close_behavior": "tray", "language": "zh_TW"}), encoding="utf-8"
    )
    ctrl = RuleCC()
    ctrl._config_cache = None

    class Win:
        _config_path = str(cfg_path)

    w = Win()
    data = ctrl.load_config(w)
    assert "close_behavior" in data
    # get_setting should fallback to DEFAULTS false without crash
    assert ctrl.get_setting(w, "auto_resize_standard", False) is False
    # set then load
    ctrl.set_setting(w, "auto_resize_standard", True)
    ctrl._config_cache = None
    data2 = ctrl.load_config(w)
    assert data2["auto_resize_standard"] is True
    # reset to false should persist
    ctrl.set_setting(w, "auto_resize_standard", False)
    ctrl._config_cache = None
    assert ctrl.get_setting(w, "auto_resize_standard") is False
