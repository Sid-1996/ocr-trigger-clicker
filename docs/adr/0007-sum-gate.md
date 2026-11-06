# 數字加總閘門：把 `sum` 從顯示擴充成可判定條件的步驟

Status: accepted（2026-11-07）

## 問題

`sum` 原本只把總和顯示在浮層／日誌（ADR-0006），使用者想「總和夠大才繼續」時只能再拉一個 `compare` 對同一區域重新 OCR：多一次辨識、多一組 ROI、而且 `compare` 只取第一個數字，無法 reuse 已經算好的加總。社群工具（Macro Handler 的 `OCR_VALUE`／`MATH_EVAL`／`COMPARE`、Osenpa Counter Reader、Sum Snip）都把「讀值→存值→比對→分支」視為同一條流程，內嵌門檻是常見做法。

## 決策

在同一個 `sum` 步驟內提供**選用**的閘門，不新增步驟類型：

- **開關**：`params.gate` 布林值，預設 false。關閉時行為與 ADR-0006 完全相同，舊任務零改動。
- **參數**：`operator`（`>` `<` `>=` `<=` `==` `!=`）、`value`（整數門檻）、`gate_timeout_sec`（等待上限，GUI 只給短 2／中 5／長 10 秒）、`on_fail`（沿用既有失敗處理，GUI 只給三種：這次先跳過 stop／跳過此規則 advance／通知並停止群組 notify）。
- **三態讀值**：讀到（至少一個整數）／空區域（OCR 完全沒文字）／讀不出（有文字但沒有可加總整數）。後兩態**不當 0**、不立即判失敗。
- **只吃穩定值**：沿用 0.35 秒去抖；值還在跳動時不算通過也不走 `on_fail`。
- **等待是獨立路徑**：等待中新增 `StepResult("wait")`，`_run_rule` 直接結束本次規則、**不清加總候選值**、不觸發 `on_fail`、不推進規則指標，下一幀重試。不可用既有 `stop` 表達等待——`_run_rule` 的 stop 分支會呼叫 `_clear_sum()`，候選值被清掉就永遠等不到穩定。
- **逾時才算失敗**：空區域／讀不出／持續跳動超過 `gate_timeout_sec` 後，走 `on_fail`，執行日誌顯示「等不到可判定的數字」。這是「等待」與「失敗」的分界，避免使用者以為規則卡死。
- **不符合條件**：穩定值算出後才比對；不符合走 `on_fail`，執行日誌顯示總和與門檻。
- **閘門不產生偵測目標**：成功時不寫 `ctx.matched_text`（與 `compare` 不同）。因此 `[gate sum → click(text_center)]` 必須在前面另有 `detect`／`match_image` 才能點；preflight 直接阻擋這種規則。
- **偵測語意**：閘門開啟時，`sum` 視同偵測步驟（`_DETECT_STEP_TYPES` 的動態判定），才有 `ctx.matched_ns` 與 `notify` 去重；關閉時維持原本的呈現步驟語意。
- **負號**：維持只取絕對值（`core/21_number_sum.py`），不做正負抵銷；UI 與文件明寫，避免使用者誤以為 `-45` 會扣分。

## 考慮過的選項

- **新增 `sum_compare` 步驟類型**：參數與表單幾乎和 `sum` 重複，使用者還要多拉一步；內嵌閘門少一個步驟類型、少一次 OCR。
- **用 `operator`／`value` 是否存在推斷閘門**：`value` 預設 0 會讓 `>=0` 恆真，無法區分「使用者真的要 0」與「只是預設值」；顯式 `gate` 布林值才不會誤開。
- **等待也走 `on_fail`**：會讓短暫的空區域或動畫中途值立即中斷規則，違反「讀不出 ≠ 失敗」；獨立等待路徑＋有限逾時才是社群共通做法。
- **讀不到當 0**：`>=` 門檻會把「還沒讀到」判成不成立，導致一閃而過的誤觸發／誤中斷。

## 後果

- `core/05_main_loop.py`：`_handle_sum` 三態與閘門、`StepResult("wait")` 專用路徑、`_is_detect_step()` 動態判定、`_sum_gate_wait` 等待計時（閒置一幀即重新計時）。
- `core/rule_migration.py`：`sum` 正規化 `gate`／`operator`／`value`／`gate_timeout_sec`／`on_fail`；`value` 無效時保留 `None`（執行期安全失敗，不可用 0 取代）。
- `core/rule_preflight.py`：閘門開啟但未框 ROI、門檻無效、或之後直接 `click(text_center)` 卻沒有前置偵測步驟 → blocked。
- `gui/06_gui_main.py`：`_SumStepForm` 改為白話五欄；閘門關閉時不動任何既有參數。
- i18n：新增閘門欄位、等待時間、失敗選項與執行日誌原因／細節字串（zh_TW／en／ja）。
- 舊任務與既有測試不受影響（`gate` 預設關閉，行為與 ADR-0006 相同）。
