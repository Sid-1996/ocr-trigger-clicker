"""Check i18n JSON consistency: all languages share the same keys."""

import json
from pathlib import Path

_dir = Path(__file__).parent


def check():
    zh_tw = json.loads((_dir / "zh_TW.json").read_text(encoding="utf-8"))
    zh_cn = json.loads((_dir / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((_dir / "en.json").read_text(encoding="utf-8"))

    tw_keys = set(zh_tw.keys())
    cn_keys = set(zh_cn.keys())
    en_keys = set(en.keys())

    ok = True

    for name, keys in [("zh_CN", cn_keys), ("en", en_keys)]:
        missing = tw_keys - keys
        extra = keys - tw_keys
        if missing:
            print(f"[FAIL] {len(missing)} keys in zh_TW but missing from {name}:")
            for k in sorted(missing):
                print(f"  - {k}")
            ok = False
        if extra:
            print(f"[WARN] {len(extra)} keys in {name} but not in zh_TW:")
            for k in sorted(extra):
                print(f"  + {k}")

    if ok:
        print(
            f"[OK] zh_TW={len(tw_keys)}, zh_CN={len(cn_keys)}, en={len(en_keys)} — all keys match"
        )
    return ok


if __name__ == "__main__":
    import sys

    sys.exit(0 if check() else 1)
