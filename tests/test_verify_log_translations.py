import pytest
from conftest import make_main_loop as _make_ml


@pytest.mark.parametrize("language, marker", [("zh_TW", "共耗時"), ("en", "total"), ("ja", "合計")])
def test_verify_log_translations(monkeypatch, language, marker):
    import i18n

    monkeypatch.setattr(i18n, "_current", language)
    ml = _make_ml()
    for vtype in ("detect", "match_image", "unknown"):
        hint = ml._verify_timeout_hint(
            {"type": vtype, "text": "target", "preset": "short", "retries": 2}
        )
        assert "short" in hint and "2" in hint
        assert "verify." not in hint
        for action in ("advance", "notify", "jump", "key", "skip"):
            message = i18n.T(
                "verify.timeout_log",
                rule="rule",
                hint=hint,
                onfail=ml._on_fail_hint({"action": action}),
                total_s=1.25,
            )
            assert marker in message and "1.2" in message
            assert "verify." not in message and "{" not in message
    assert ml._on_fail_hint({"action": "unknown"}) == "unknown"
    assert ml._on_fail_hint("stop") == "stop"
