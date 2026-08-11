"""啟動群組選擇的狀態決策（Qt-free，供 GUI 與測試共用）。

語意：對話框每次開啟預設全部啟用群組打勾；只有使用者上次勾了「下次直接使用
這些群組」且記憶仍有效時，才會跳過詢問直接沿用。
"""


def should_skip(saved: dict, valid_ids: list) -> bool:
    """上次勾了「記住」且記憶的群組仍存在且有效 → 跳過詢問直接沿用。"""
    return bool(saved and saved.get("skip") and valid_ids)


def build_entry(selected_ids: list, remember: bool) -> dict:
    """依本次對話結果產出要寫入 config 的 group_selection 條目。

    remember 為真且確實有選到群組才記憶；否則清空（下次啟動照樣詢問、
    預設全勾），避免空選擇留下無效的 skip=true。
    """
    return {
        "group_ids": list(selected_ids),
        "skip": bool(remember and selected_ids),
    }
