"""啟動群組選擇的狀態決策（Qt-free，供 GUI 與測試共用）。

語意：對話框每次開啟預設全部啟用群組打勾；只有使用者上次勾了「下次直接使用
這些群組」且記憶仍有效時，才會跳過詢問直接沿用。
"""


def should_skip(saved: dict, valid_ids: list) -> bool:
    """上次勾了「記住」且記憶的群組仍存在且有效 → 跳過詢問直接沿用。"""
    return bool(saved and saved.get("skip") and valid_ids)


def build_entry(selected_ids: list, remember: bool, known_group_ids: list | None = None) -> dict:
    """依本次對話結果產出要寫入 config 的 group_selection 條目。

    remember 為真且確實有選到群組才記憶；否則清空（下次啟動照常詢問、
    預設全勾），避免空選擇留下無效的 skip=true。

    known_group_ids：當下任務的全部群組 id 快照（含停用者）。供
    selection_stale() 偵測日後的結構變動（刪除/重建/新增群組）；
    未提供則不寫入該欄位（舊格式條目會被視為 stale 一次性重問）。
    """
    entry = {
        "group_ids": list(selected_ids),
        "skip": bool(remember and selected_ids),
    }
    if known_group_ids is not None:
        entry["known_group_ids"] = list(known_group_ids)
    return entry


def selection_stale(entry: dict, current_all_ids: set, current_enabled_ids: set) -> bool:
    """任務群組結構自記憶後是否已變動（變動 → 應忽略 skip、重新詢問）。

    - 舊格式條目（無 known_group_ids）→ stale：無從判別，一次性重問以治癒
      「刪除重建群組後被永久排除」的歷史受害設定
    - known 中有任何 id 已不存在 → stale（群組被刪除/重建）
    - 當前 enabled 有任何 id 不在 known → stale（新增了群組）
    - 刻意排除部分現存群組不算變動——「下次直接使用」的子集選擇照樣生效
    """
    known = entry.get("known_group_ids") if entry else None
    if not isinstance(known, list):
        return True
    if any(rid not in current_all_ids for rid in known):
        return True
    return any(eid not in known for eid in current_enabled_ids)
