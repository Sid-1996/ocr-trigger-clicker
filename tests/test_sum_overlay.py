from _loader import load_sibling

_overlay = load_sibling("sum_overlay", "gui/sum_overlay.py")


def test_physical_to_logical_primary_high_dpi():
    assert _overlay._physical_to_logical(1200, 800, 100, 50, 0, 0, 2.0, 0, 0) == (
        600.0,
        400.0,
        50.0,
        25.0,
    )


def test_physical_to_logical_secondary_monitor():
    assert _overlay._physical_to_logical(2200, 300, 200, 100, 1920, 0, 2.0, 1920, 0) == (
        2060.0,
        150.0,
        100.0,
        50.0,
    )


def test_physical_to_logical_defaults_bad_dpr():
    assert _overlay._physical_to_logical(10, 20, 30, 40, 0, 0, 0, 0, 0) == (
        10.0,
        20.0,
        30.0,
        40.0,
    )
