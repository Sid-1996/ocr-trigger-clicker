from core.group_selection import build_entry, selection_stale, should_skip


def test_should_skip_true_only_when_remembered_and_valid():
    assert should_skip({"group_ids": ["a", "b"], "skip": True}, ["a"])
    assert not should_skip({"group_ids": ["a", "b"], "skip": True}, [])
    assert not should_skip({"group_ids": ["a", "b"], "skip": False}, ["a"])
    assert not should_skip({}, [])
    assert not should_skip({"group_ids": [], "skip": True}, [])


def test_build_entry_remembers_only_when_checked_with_selection():
    assert build_entry(["a", "b"], True) == {"group_ids": ["a", "b"], "skip": True}
    assert build_entry(["a"], False) == {"group_ids": ["a"], "skip": False}
    # 空選擇即使勾「記住」也不應留下無效 skip=true
    assert build_entry([], True) == {"group_ids": [], "skip": False}
    assert build_entry([], False) == {"group_ids": [], "skip": False}


def test_build_entry_returns_copy():
    ids = ["a"]
    entry = build_entry(ids, True)
    ids.append("b")
    assert entry["group_ids"] == ["a"]


def test_build_entry_with_known_snapshot():
    entry = build_entry(["a"], True, known_group_ids=["a", "b"])
    assert entry["known_group_ids"] == ["a", "b"]
    assert entry["skip"] is True
    # 未提供快照 → 不寫入欄位（舊格式，與既有行為相容）
    assert "known_group_ids" not in build_entry(["a"], True)


# ── selection_stale：任務群組結構變動偵測 ──

_ALL = {"a", "b", "c"}
_ENABLED = {"a", "b"}  # c 存在但停用


def test_stale_legacy_entry_without_snapshot():
    # 舊格式（無 known_group_ids）→ 一次性重問治癒歷史受害設定
    assert selection_stale({"group_ids": ["a"], "skip": True}, _ALL, _ENABLED)
    assert selection_stale({}, _ALL, _ENABLED)


def test_stale_when_known_group_deleted():
    # 刪除/重建群組：known 含已消失的 id
    entry = build_entry(["a"], True, known_group_ids=["a", "gone"])["known_group_ids"]
    assert selection_stale(
        {"group_ids": ["a"], "skip": True, "known_group_ids": entry}, _ALL, _ENABLED
    )


def test_stale_when_new_enabled_group_added():
    # 新增啟用群組：enabled 有 id 不在 known
    known = ["a"]  # 建立當下只有 a；後來新增了 b
    entry = {"group_ids": ["a"], "skip": True, "known_group_ids": known}
    all_now = {"a", "b"}
    enabled_now = {"a", "b"}
    assert selection_stale(entry, all_now, enabled_now)


def test_not_stale_for_deliberate_subset_or_disabled_toggle():
    # 刻意排除現存群組（選 a 略過 b）→ 子集記憶照樣生效
    entry = {"group_ids": ["a"], "skip": True, "known_group_ids": ["a", "b"]}
    assert not selection_stale(entry, _ALL, _ENABLED)
    # 停用→再啟用的群組一直在 known（含停用者）→ 不算新增
    entry_full = {"group_ids": ["a"], "skip": True, "known_group_ids": ["a", "b", "c"]}
    assert not selection_stale(entry_full, _ALL, {"a", "b"})
    assert not selection_stale(entry_full, _ALL, {"a", "b", "c"})
