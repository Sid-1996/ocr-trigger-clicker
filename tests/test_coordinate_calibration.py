"""座標校正工具與主循環客戶區換算的純邏輯測試（不開視窗、不點滑鼠）。"""

import importlib

from conftest import make_main_loop

cal = importlib.import_module("devtools.coordinate_calibration")


def test_parse_size_accepts_presets_and_free_form():
    assert cal._parse_size("1600 × 900") == (1600, 900)
    assert cal._parse_size("1920x1080") == (1920, 1080)
    assert cal._parse_size("1284 x 720") == (1284, 720)
    assert cal._parse_size(None) == (1600, 900)


def test_card_hit_returns_deviation_from_card_center():
    hit = cal._card_hit(0.2 * 1600, 0.2 * 869, 1600, 869)
    assert hit is not None
    assert hit["id"] == "A"
    assert abs(hit["dx"]) <= 1 and abs(hit["dy"]) <= 1
    assert cal._card_hit(2, 2, 1600, 869) is None


def test_status_payload_and_roundtrip(tmp_path):
    path = tmp_path / "status.json"
    payload = cal._status_payload(
        session="s1",
        seq=3,
        frame_size=(1616, 908),
        client_size=(1600, 869),
        dpi=1.0,
        hits=[{"id": "A", "dx": 0, "dy": 0}],
        misses=1,
        last_click={"id": "A", "x": 320, "y": 174, "dx": 0, "dy": 0},
        hwnd=12345,
    )
    assert payload["schema"] == cal.STATUS_SCHEMA
    assert payload["hwnd"] == 12345
    assert payload["window"] == {"frame_w": 1616, "frame_h": 908, "client_w": 1600, "client_h": 869}
    assert payload["hit_ids"] == ["A"]

    cal._write_status_file(path, payload)
    assert cal._read_status(path) == payload


def test_client_ratio_uses_actual_client_size():
    ml = make_main_loop()
    ml._window_hwnd = None
    ml._frame_chrome = (8, 31)
    ml._frame_client_size = (1600, 869)
    rect = {"x": 100, "y": 50, "w": 1616, "h": 908}

    assert ml._resolve_point(0.8, 0.8, rect, "client") == (1288, 726)
    roi = ml._resolve_roi({"x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1, "roi_coord": "client"}, rect)
    assert roi == {"x": 328, "y": 205, "w": 160, "h": 87}


def test_client_ratio_falls_back_without_hwnd():
    ml = make_main_loop()
    ml._window_hwnd = None
    ml._frame_chrome = (8, 31)
    ml._frame_client_size = None
    rect = {"x": 0, "y": 0, "w": 1616, "h": 908}

    assert ml._client_size(rect) == (1600, 846)
