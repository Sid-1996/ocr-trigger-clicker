"""Rule-level preflight — pure logic validation, no side effects.

Only validates Rule structure and basic step parameters.
Does NOT read StepContext, interaction mode, HWND, OCR, or any
input backend state.

Does NOT access:
- ctx (StepContext)
- mode (interaction_mode)
- HWND or window handles
- OCR or screenshot data
- Input backends (pynput/frida/hybrid)
- _run_rule() execution flow
- GUI modules
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _loader import load_sibling

_models = load_sibling("rule_models", "core/rule_models.py")
Rule = _models.Rule
Step = _models.Step

# target 白名單在 core 的資料契約層（rule_migration 只依賴標準函式庫，無循環依賴）。
_migration = load_sibling("rule_migration", "core/rule_migration.py")


@dataclass
class PreflightResult:
    """Preflight validation result.

    Attributes
    ----------
    status
        "passed" if no blocking issue found, "blocked" if execution should stop.
    problems
        List of issues that definitely prevent execution (may be empty).
    warnings
        List of issues that do not prevent execution but are worth noting (may be empty).
    """

    status: Literal["passed", "blocked"]
    problems: list[str]
    warnings: list[str]


# Valid step types recognised by the core _run_step dispatcher.
_VALID_STEP_TYPES = frozenset(
    {
        "detect",
        "click",
        "key",
        "wait",
        "jump",
        "drag",
        "scroll",
        "match_image",
        "compare",
        "sum",
        "notify",
    }
)

_SUM_GATE_OPERATORS = frozenset({">", "<", ">=", "<=", "==", "!="})
_MATCH_SOURCE_STEP_TYPES = frozenset({"detect", "match_image", "compare"})


def _finite_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _roi_configured(roi) -> bool:
    if not isinstance(roi, dict):
        return False
    try:
        return float(roi.get("w", 0)) > 0 and float(roi.get("h", 0)) > 0
    except (TypeError, ValueError):
        return False


def rule_preflight(rule: Rule) -> PreflightResult:
    """Run Rule-level preflight validation.

    Only examines the Rule object's own data (steps, params).
    Does NOT read StepContext, interaction mode, HWND, OCR, or any
    input backend state.

    Parameters
    ----------
    rule
        The Rule to validate.

    Returns
    -------
    PreflightResult
        Validation result with status, problems and warnings.
    """
    problems: list[str] = []
    warnings: list[str] = []

    # ── 0. Rule 結構防護 ────────────────────────────────────────────────
    if rule is None:
        problems.append("invalid_rule")
        return PreflightResult(status="blocked", problems=problems, warnings=warnings)

    if not isinstance(getattr(rule, "steps", None), list):
        # 步驟列表非 list（可能為 None、dict 等），直接 blocked，不嘗試遍歷
        problems.append("invalid_steps")
        return PreflightResult(status="blocked", problems=problems, warnings=warnings)

    # ── 1. Step 物件結構與內容防護 ──────────────────────────────────────
    # 加總閘門防呆：閘門開啟後，這條規則的成敗靠它，設定不完整就直接不執行。
    gate_sum_seen = False
    match_source_seen = False
    for idx, step in enumerate(rule.steps):
        # 必須是 canonical Step 類別的實例。Step 取自 load_sibling("rule_models", ...)
        # 的共用模組實例，與 core/05_main_loop.py 的 fingerprint 判定的是同一個
        # class object，因此兩邊判定一致。不可改用類別名稱比對：一般 import 的
        # core.rule_models 是另一個 module 物件（另一個 class object），
        # 會被誤認為合法 Step，卻讓 fingerprint 回 None、cache 與 blocked 日誌靜默失效。
        if not isinstance(step, Step):
            problems.append("invalid_step")
            continue

        step_type = step.type if isinstance(step.type, str) else "invalid"
        # params 型態檢查：非 dict 時視為空 dict，但在 Detect 檢查中
        # 會產生 invalid_detect_text 問題
        params = step.params if isinstance(step.params, dict) else {}

        # ── 2. Detect 文字驗證 ────────────────────────────────────────
        if step_type == "detect":
            # 明確檢查 key 是否存在，避免 .get() 混淆「缺 key」與「值為 None」
            if "text" not in params:
                problems.append("empty_detect_text")
            else:
                text = params.get("text")
                if text is None:
                    problems.append("invalid_detect_text")
                elif not isinstance(text, str):
                    problems.append("invalid_detect_text")
                elif text == "":
                    problems.append("empty_detect_text")
                elif text.strip() == "":
                    problems.append("empty_detect_text")
            # 若 text 為非空白字串，則不產生任何問題

        # ── 3. 未知 Step 類型檢查 ───────────────────────────────────────
        if step_type not in _VALID_STEP_TYPES:
            problems.append("unknown_step_type")
            # 一旦發現未知類型標記 blocked，但繼續累積其他問題
            # 我們不 break，是為為累積其他潛在問題；但跳過後續 type-specific 檢查
            continue

        # ── 3b. 加總閘門防呆 ──────────────────────────────────────────
        if step_type == "sum" and params.get("gate"):
            gate_sum_seen = True
            if not _roi_configured(params.get("roi")):
                problems.append("sum_gate_roi_unset")
            if (
                not _finite_number(params.get("value"))
                or str(params.get("operator", ">=")) not in _SUM_GATE_OPERATORS
            ):
                problems.append("sum_gate_value_invalid")
        elif step_type in _MATCH_SOURCE_STEP_TYPES:
            match_source_seen = True
        # 閘門成功不寫 ctx.matched_text（與 compare 不同），後續點擊辨識目標
        # 必須有前面的偵測步驟；否則一定 no_target，存檔即擋下。
        if (
            gate_sum_seen
            and not match_source_seen
            and step_type in ("click", "drag")
            and params.get("target", "text_center") == "text_center"
        ):
            problems.append("gate_sum_click_no_target")

        # ── 3c. Click／Drag 目標值合法性 ──────────────────────────────
        # 白名單來自 core/rule_migration（唯一事實來源），本模組不另寫一份。
        # 未知 target 在執行期只會 stop（unknown_click_target／unknown_drag_target），
        # 事前擋下可讓使用者在開始前就看到要改哪個欄位。
        if step_type in ("click", "drag"):
            target = params.get("target", "text_center")
            if not _migration.is_known_step_target(step_type, target):
                problems.append(f"unknown_{step_type}_target")

        # ── 4. Custom Click (0,0) 警告 ────────────────────────────────
        if (
            step_type == "click"
            and params.get("target") == "custom"
            and isinstance(params.get("x"), (int, float))
            and isinstance(params.get("y"), (int, float))
            and params.get("x") == 0
            and params.get("y") == 0
        ):
            warnings.append("custom_click_at_origin")
            # status 不變為 blocked，僅記錄警告

    # ── 5. 保序去重 ────────────────────────────────────────────────────
    problems = list(dict.fromkeys(problems))
    warnings = list(dict.fromkeys(warnings))

    # ── 6. 判斷最終狀態 ────────────────────────────────────────────────
    if problems:
        status = "blocked"
    else:
        status = "passed"

    return PreflightResult(status=status, problems=problems, warnings=warnings)
