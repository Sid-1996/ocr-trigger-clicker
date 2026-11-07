"""UX 2B-10：工具列常用／次要按鈕分組。

以真實 MainWindow 驗證：主要操作直接可見、任務管理與次要功能收納至
選單、原按鈕物件與 handler 連接保留、啟用/停用條件同步。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QAction  # noqa: E402


def _toolbar_widgets(win):
    """主視窗 central layout 第一個 item 即頂部工具列（QHBoxLayout）。"""
    layout = win.centralWidget().layout()
    toolbar = layout.itemAt(0).layout()
    widgets = []
    for i in range(toolbar.count()):
        item = toolbar.itemAt(i)
        if item.widget() is not None:
            widgets.append(item.widget())
    return widgets


def test_primary_actions_directly_in_toolbar(real_mainwindow):
    win = real_mainwindow
    widgets = _toolbar_widgets(win)
    for attr in (
        "_window_combo",
        "_task_combo",
        "_task_new_btn",
        "_task_rename_btn",
        "_task_del_btn",
        "_task_menu_btn",
        "_btn_toggle",
        "_debug_btn",
        "_record_btn",
        "_more_menu_btn",
    ):
        assert getattr(win, attr) in widgets, f"{attr} 必須直接在工具列"
    # 主要操作不得有選單（不增加點擊層級）
    assert win._btn_toggle.menu() is None
    assert win._debug_btn.menu() is None
    assert win._record_btn.menu() is None


def test_managed_buttons_not_directly_in_toolbar(real_mainwindow):
    win = real_mainwindow
    widgets = _toolbar_widgets(win)
    for attr in (
        "_task_import_btn",
        "_task_export_btn",
        "_task_share_btn",
        "_sponsor_btn",
        "_settings_btn",
        "_about_btn",
        "_guide_btn",
        "_update_btn",
    ):
        assert getattr(win, attr) not in widgets, f"{attr} 已收納，不應直接在工具列"
        # 原按鈕物件仍存在且保留文字/tooltip
        assert getattr(win, attr).text() != ""
        assert getattr(win, attr).toolTip() != ""


def test_task_menu_structure(real_mainwindow):
    win = real_mainwindow
    assert win._task_menu_btn.menu() is win._task_menu
    actions = win._task_menu.actions()
    assert win._task_import_action in actions
    assert win._task_export_action in actions
    assert win._task_import_action.text() == win._task_import_btn.text()
    assert win._task_export_action.text() == win._task_export_btn.text()
    # 分享子選單
    submenus = [a.menu() for a in actions if a.menu() is not None]
    assert len(submenus) == 1
    share_actions = submenus[0].actions()
    assert len(share_actions) == 2
    assert all(isinstance(a, QAction) and a.isEnabled() for a in share_actions)


def test_more_menu_structure(real_mainwindow):
    win = real_mainwindow
    assert win._more_menu_btn.menu() is win._more_menu
    pairs = [
        (win._sponsor_action, win._sponsor_btn),
        (win._settings_action, win._settings_btn),
        (win._about_action, win._about_btn),
        (win._guide_action, win._guide_btn),
        (win._update_action, win._update_btn),
    ]
    assert win._more_menu.actions() == [action for action, _ in pairs]
    for action, button in pairs:
        assert action.text() == button.text()


def test_menu_actions_trigger_original_buttons(real_mainwindow):
    win = real_mainwindow
    fired = []
    # 斷開原 handler（部分 handler 會開對話框/選單而阻擋），只留 spy 驗證
    # 「選單項目 → 原按鈕 click()」這條轉發鏈；handler 本身的連接在
    # _connect_signals 未動，結構測試已確認按鈕物件與文字/tooltip 保留。
    for name in ("_task_import_btn", "_task_export_btn", "_sponsor_btn"):
        button = getattr(win, name)
        button.clicked.disconnect()
        button.clicked.connect(lambda _=False, n=name: fired.append(n))

    win._task_import_action.trigger()
    assert fired == ["_task_import_btn"], "選單項目必須只觸發對應原按鈕"

    fired.clear()
    win._task_export_action.trigger()
    assert fired == ["_task_export_btn"]

    fired.clear()
    win._sponsor_action.trigger()
    assert fired == ["_sponsor_btn"]


def test_share_submenu_actions_trigger_handlers(real_mainwindow, monkeypatch):
    win = real_mainwindow
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    share_menu = [a.menu() for a in win._task_menu.actions() if a.menu() is not None][0]
    go_website = share_menu.actions()[1]
    go_website.trigger()
    assert opened == [
        "https://github.com/Sid-1996/ocr-trigger-clicker/discussions/categories/"
        "%E4%BB%BB%E5%8B%99%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB"
    ]


def test_enable_disable_syncs_menu_actions(real_mainwindow):
    win = real_mainwindow
    fired = []
    win._task_import_btn.clicked.disconnect()
    win._task_import_btn.clicked.connect(lambda: fired.append("import"))

    win._update_edit_enabled(False)
    assert not win._task_import_btn.isEnabled()
    assert not win._task_export_btn.isEnabled()
    assert not win._task_import_action.isEnabled()
    assert not win._task_export_action.isEnabled()
    assert not win._debug_btn.isEnabled()
    # 停用狀態下觸發選單項目不得執行原功能
    win._task_import_action.trigger()
    assert fired == []

    win._update_edit_enabled(True)
    assert win._task_import_btn.isEnabled()
    assert win._task_import_action.isEnabled()
    assert win._task_export_action.isEnabled()
    assert win._debug_btn.isEnabled()
    win._task_import_action.trigger()
    assert fired == ["import"]
