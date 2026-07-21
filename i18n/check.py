"""Check i18n JSON consistency: all language files share the same keys."""

import json
from pathlib import Path

_dir = Path(__file__).parent


def _load_all() -> dict[str, dict[str, str]]:
    result = {}
    for f in sorted(_dir.glob("*.json")):
        result[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return result


def check():
    langs = _load_all()
    if not langs:
        print("[FAIL] No language files found")
        return False

    names = list(langs.keys())
    ref_name = names[0]
    ref_keys = set(langs[ref_name].keys())

    ok = True
    for name in names[1:]:
        keys = set(langs[name].keys())
        missing = ref_keys - keys
        extra = keys - ref_keys
        if missing:
            print(f"[FAIL] {len(missing)} keys in {ref_name} but missing from {name}:")
            for k in sorted(missing):
                print(f"  - {k}")
            ok = False
        if extra:
            print(f"[WARN] {len(extra)} keys in {name} but not in {ref_name}:")
            for k in sorted(extra):
                print(f"  + {k}")

    if ok:
        details = ", ".join(f"{n}={len(langs[n])}" for n in names)
        print(f"[OK] {details} — all keys match")
    return ok


if __name__ == "__main__":
    import sys

    sys.exit(0 if check() else 1)
