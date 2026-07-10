import os


def _replace_file(tmp_path: str, dst: str) -> None:
    try:
        os.unlink(dst)
    except FileNotFoundError:
        pass
    try:
        os.rename(tmp_path, dst)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
