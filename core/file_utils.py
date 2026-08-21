import os


def _replace_file(tmp_path: str, dst: str) -> None:
    # os.replace：Windows 原子覆蓋語意，消除 unlink→rename 之間 dst 不存在的窗口
    try:
        os.replace(tmp_path, dst)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
