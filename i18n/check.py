"""Check i18n JSON consistency: same keys in zh_TW and zh_CN."""

import json
from pathlib import Path

_dir = Path(__file__).parent


def check():
    zh_tw = json.loads((_dir / "zh_TW.json").read_text(encoding="utf-8"))
    zh_cn = json.loads((_dir / "zh_CN.json").read_text(encoding="utf-8"))

    tw_keys = set(zh_tw.keys())
    cn_keys = set(zh_cn.keys())

    missing_cn = tw_keys - cn_keys
    extra_cn = cn_keys - tw_keys

    ok = True
    if missing_cn:
        print(f"[FAIL] {len(missing_cn)} keys in zh_TW but missing from zh_CN:")
        for k in sorted(missing_cn):
            print(f"  - {k}")
        ok = False
    if extra_cn:
        print(f"[WARN] {len(extra_cn)} keys in zh_CN but not in zh_TW:")
        for k in sorted(extra_cn):
            print(f"  + {k}")

    if ok and not extra_cn:
        print(f"[OK] {len(tw_keys)} keys match perfectly between zh_TW and zh_CN")

    return ok


if __name__ == "__main__":
    import sys

    sys.exit(0 if check() else 1)
