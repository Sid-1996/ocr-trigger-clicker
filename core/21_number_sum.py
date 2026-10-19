"""把 OCR 文字裡的整數抓出來加總（數字加總步驟用）。

只接受整數；逗號視為千位分隔（1,234）。含英文字母、小數點或百分比的
token 一律略過（2G、1.2K、26% 都不算），避免把單位或比例誤加。
全形字元先經 NFKC 正規化（＋２６ → +26）。
"""

import re
import unicodedata

# 邊界只排除 ASCII 英數與 , . %：允許「共26」「+26」這種前後有符號/中文的寫法。
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9.,])(\d{1,3}(?:,\d{3})+|\d+)(?![A-Za-z0-9.,%])")


def parse_numbers(text: str) -> list[int]:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    numbers = []
    for match in _NUMBER_RE.finditer(normalized):
        try:
            numbers.append(int(match.group(1).replace(",", "")))
        except ValueError:
            continue
    return numbers


def sum_numbers(text: str) -> tuple[int, int]:
    """回傳 (總和, 數字個數)；沒有可加總數字時為 (0, 0)。"""
    numbers = parse_numbers(text)
    return sum(numbers), len(numbers)


if __name__ == "__main__":
    assert parse_numbers("+26") == [26]
    assert parse_numbers("+26 +9 +20") == [26, 9, 20]
    assert parse_numbers("1,234") == [1234]
    assert parse_numbers("1,234,567") == [1234567]
    assert parse_numbers("2G") == []
    assert parse_numbers("26%") == []
    assert parse_numbers("1.2K") == []
    assert parse_numbers("2,26") == []  # 逗號後非三位數 → 不當千位分隔
    assert parse_numbers("＋２６") == [26]
    assert parse_numbers("－５") == [5]  # 符號略過，只取絕對值
    assert parse_numbers("共 26 個") == [26]
    assert sum_numbers("+26 +9 +20") == (55, 3)
    assert sum_numbers("") == (0, 0)
    assert sum_numbers("no numbers here") == (0, 0)
    print("  [OK] number_sum parse/sum")
    print("\n=== All checks passed ===")
