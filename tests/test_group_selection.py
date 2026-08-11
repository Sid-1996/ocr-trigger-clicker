from core.group_selection import build_entry, should_skip


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
