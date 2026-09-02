# Verify 僅屬於動作四類（click/key/drag/scroll），match_image 不提供驗證入口

Status: accepted（2026-09-02）
Context: v0.4.3 後未發版，開發期內無線上用戶兼容包袱

## 問題
`verify` 初版允許 `click/key/drag/scroll/match_image` 五類（`core/rule_migration.py:199` / `core/05_main_loop.py:1429`）。但 `match_image` 本質是偵測步驟（`detect` 同類），驗證語意為「偵測的驗證」——與 `動作後驗證是動作的 post-condition`（`CONTEXT.md:94`）定義矛盾，且可由兩步順序 `match_image A → detect/match_image B` 直觀替代。

## 決策
收斂至動作四類：`click / key / drag / scroll` 保留 `VerifyWidget`；`match_image` 移除驗證入口，舊 JSON 中 `match_image.verify` 視為無效直接丟棄（`rule_migration._normalize_step_params` `warning dropped`，無 UI 橫幅、無遷移期）。

## 考慮過的選項
- **全保留**：維持五類，僅補 hint 引導改綁 click — 名不符實，持續增加術語負擔
- **旗標隱藏**：引擎保留白名單，GUI 摺疊隱藏並標 deprecated — 為 0 使用率保留分支，不符 YAGNI
- **動作四類收斂（採用）**：回到單一職責，表單簡化 15 控件，舊檔開發期可直接重建

## 後果
- `core/rule_migration.py:199` / `core/05_main_loop.py:1429` 白名單刪 `match_image`
- `gui/06_gui_main.py:_MatchImageStepForm` 移除 `VerifyWidget`（`_after_delay` 下註記替代寫法）
- 重試語意差異：`match_image` 的「重試原圖」需改為 rule 層 `loop` + `fail_duration` + 第二步 `on_fail=advance` 替代；此為極少數閃爍圖場景，開發期可接受
- 測試：`tests/test_verify.py` 補 `test_match_image_verify_dropped` 負向斷言
