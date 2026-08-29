import os
import re
import sys
from pathlib import Path


def get_resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)


def get_data_path(relative_path: str) -> str:
    base = os.environ.get(
        "OCR_TRIGGER_DATA",
        os.path.join(os.environ.get("APPDATA", Path.home()), "ocr-trigger-clicker"),
    )
    path = os.path.join(base, relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def main():
    try:
        import PyInstaller.__main__
    except ImportError:
        print("請先同步開發依賴: uv sync --dev")
        sys.exit(1)

    here = Path(__file__).parent

    # 更新 feed 選擇：--feed test 烘入測試庫，預設正式庫（用戶端據此檢查更新）
    feeds = {
        "prod": "https://github.com/Sid-1996/ocr-trigger-clicker",
        "test": "https://github.com/Sid-1996/ocr-trigger-clicker-release-test",
    }
    feed = "prod"
    if "--feed" in sys.argv:
        i = sys.argv.index("--feed")
        feed = sys.argv[i + 1]
    if feed not in feeds:
        print(f"❌ 不支援的 --feed 值: {feed}（可選 prod/test）")
        sys.exit(1)
    feed_url = feeds[feed]
    print(f"更新 feed: {feed} → {feed_url}")

    print("搜尋 RapidOCR 模型檔案...")
    try:
        import rapidocr_onnxruntime
    except ModuleNotFoundError:
        print("\n❌ 找不到 rapidocr_onnxruntime 模組")
        print(f"   當前 Python: {sys.executable}")
        print(f"   工作目錄: {Path.cwd()}")
        print()
        print("   請確認已在正確的 Python 環境中執行：")
        print("   1. 同步依賴：uv sync --dev")
        print("   2. 直接在專案目錄執行：")
        print(f'      cd "{here}"')
        print("      uv run python build.py")
        sys.exit(1)

    rap_path = Path(rapidocr_onnxruntime.__file__).parent

    datas = []
    pkg_dir = rap_path.name  # "rapidocr_onnxruntime"
    for pattern in ["*.onnx", "*.yaml", "*.json", "*.txt"]:
        for f in rap_path.rglob(pattern):
            if f.is_file():
                rel = f.relative_to(rap_path)
                datas.append((str(f), str(pkg_dir / rel.parent)))
    print(f"找到 {len(datas)} 個模型/資源檔")

    # i18n JSON dictionaries
    i18n_dir = here / "i18n"
    if i18n_dir.exists():
        for lang_file in i18n_dir.glob("*.json"):
            datas.append((str(lang_file), "i18n"))

    custom_dir = here / "custom_models"
    if custom_dir.exists():
        for f in custom_dir.iterdir():
            if f.is_file():
                datas.append((str(f), "custom_models"))
        print(f"找到 {len(list(custom_dir.iterdir()))} 個自訂模型檔")

    # 核心/ GUI 模組 ─ glob 自動掃描，不再手動維護
    for f in (here / "core").rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        datas.append((str(f), "core"))
    for f in (here / "gui").rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        datas.append((str(f), "gui"))
    for rel, dest in [("_loader.py", "."), ("i18n/__init__.py", "i18n")]:
        f = here / rel
        if f.exists():
            datas.append((str(f), dest))

    # 烘入更新 feed 位址（用戶端 core/12_updater.py 執行時讀取）
    feed_py = here / "_update_feed.py"
    feed_py.write_text(f'FEED_REPO_URL = "{feed_url}"\n', encoding="utf-8")
    datas.append((str(feed_py), "."))

    # 被 _loader.py 動態載入的模組（PyInstaller 靜態分析無法追蹤）
    # 以及 transitive deps（PyInstaller 無法自動追蹤的內部依賴）
    hidden = [
        # 動態載入（透過 _loader.load_sibling）
        "mss",
        "cv2",
        "pygetwindow",
        "numpy",
        "rapidocr_onnxruntime",
        # transitive deps
        "onnxruntime",
        "PIL",
        "pyclipper",
        "shapely",
        "yaml",
        "tqdm",
        # pynput + dxcam: lazy-imported, static scanner can miss them
        "pynput",
        "dxcam",
        "comtypes",
        # frida: 後台注入模式，lazy-imported，DLL 需 collect-all 收集
        "frida",
        # stdlib submodule imported from _loader-loaded data files; PyInstaller can miss it.
        "logging.handlers",
        # velopack: 更新框架，lazy-imported（core/12_updater.py 函式內 import）
        "velopack",
    ]

    exclude = [
        # 大型 ML/AI 框架（完全不使用）
        "torch",
        "torchvision",
        "torchaudio",
        "pytorch_lightning",
        "lightning_utilities",
        "safetensors",
        "ultralytics",
        "ultralytics_thop",
        "modelscope",
        "cnocr",
        "cnstd",
        "imgaug",
        # 資料科學（不使用）
        "pandas",
        "scipy",
        "sympy",
        "matplotlib",
        "seaborn",
        "contourpy",
        "cycler",
        "fonttools",
        "kiwisolver",
        "scikit_image",
        "networkx",
        "tifffile",
        "imageio",
        # 網路／HTTP（不使用）
        "aiohttp",
        "aiosignal",
        "frozenlist",
        "multidict",
        "yarl",
        "propcache",
        "httpx",
        "anyio",
        "httpcore",
        "h11",
        "requests",
        "urllib3",
        "certifi",
        "idna",
        # 開發/建置工具
        "Cython",
        # GUI 框架（不使用 tkinter）
        "tkinter",
        "_tkinter",
        "tcl",
        # 其他未使用
        "PyAutoGUI",
        "keyboard",
        "psutil",
        "PyDirectInput",
        "mouseinfo",
        "pyscreeze",
        "pytweening",
        "sentry_sdk",
        "pydantic",
        "rich",
        "Pygments",
        "cryptography",
        "chardet",
        "openpyxl",
        "python_dotenv",
        "wandb",
        "omegaconf",
        "antlr4_python3_runtime",
        # dist 瘦身：numpy typing stubs 拉入的開發工具
        "mypy",
        "ast_serialize",
        # dist 瘦身：無人使用的 XML / COM 相關
        "lxml",
        "Pythonwin",
        "win32",
        "pythoncom",
        "win32com",
        "pywin32_bootstrap",
    ]

    args = [
        "--onedir",
        "--windowed",
        "--name=ocr-trigger-clicker",
        "--distpath=" + str(here / "dist"),
        "--workpath=" + str(here / "build"),
        "--specpath=" + str(here),
        "--noconfirm",
    ]
    for h in hidden:
        args.append(f"--hidden-import={h}")
    # 收集 numpy 所有子模組 + 二進位 + 資料檔，確保 C extension 不漏
    args.append("--collect-all=numpy")
    # ponytail: cv2 用動態載入器引入 load_config_py3 等 helper，靜態分析抓不到
    args.append("--collect-all=cv2")
    # dxcam/comtypes: COM interop 在運行期動態解析介面，需收集所有二進位
    args.append("--collect-all=comtypes")
    args.append("--collect-all=dxcam")
    # pynput: 平台特定子模組（_win32）靜態分析可能遺漏
    args.append("--collect-all=pynput")
    # frida: _frida.pyd + frida-core.dll + frida-gum.dll 需全數收集，避免 LoadLibrary 找不到
    args.append("--collect-all=frida")
    for e in exclude:
        args.append(f"--exclude-module={e}")
    for src, dst in datas:
        args.append(f"--add-data={src}{os.pathsep}{dst}")

    icon = here / "icons" / "app.ico"
    if icon.exists():
        args.append(f"--icon={str(icon)}")
    else:
        print("未找到 icons/app.ico，略過圖示設定")

    args.append(str(here / "gui/06_gui_main.py"))

    print("=== PyInstaller 打包參數 ===")
    print("入口: 06_gui_main.py")
    print("輸出: dist\\ocr-trigger-clicker\\")
    print(f"資料檔案: {len(datas)} 項")
    print(f"隱藏 import: {len(hidden)} 項")
    print(f"排除模組: {len(exclude)} 項")
    print()

    PyInstaller.__main__.run(args)
    feed_py.unlink(missing_ok=True)

    exe = here / "dist" / "ocr-trigger-clicker" / "ocr-trigger-clicker.exe"
    if exe.exists():
        print(f"\n打包成功: {exe}")
        # 清理 build/ 暫存（spec 保留供除錯）
        import shutil

        shutil.rmtree(here / "build", ignore_errors=True)
        slim_dist()
        verify_feed(feed_url)
        pack_velopack()
    else:
        print("\n打包失敗")


def slim_dist():
    # ponytail: 移除打包後已確認零使用的檔案（究責：PE import 表/程式碼參考皆無引用）
    root = Path(__file__).parent / "dist" / "ocr-trigger-clicker" / "_internal"
    targets = [
        (root / "cv2", "opencv_videoio_ffmpeg*_64.dll"),
        (root / "PIL", "_avif*"),
        (root / "dxcam" / "processor", "_numpy_kernels.c"),
        (root / "dxcam" / "processor", "_numpy_kernels.pyx"),
    ]
    removed = 0
    for base, pattern in targets:
        for f in base.glob(pattern) if base.exists() else []:
            size = f.stat().st_size
            f.unlink()
            removed += size
            print(f"瘦身: 移除 {f.relative_to(root.parent)} ({size / 1048576:.1f} MB)")
    if removed:
        print(f"瘦身: 共釋出 {removed / 1048576:.1f} MB")


def verify_feed(expected_url: str):
    """防呆：確認烘進包裡的 feed 位址與本次目標一致，防止拿錯包上架。"""
    f = Path(__file__).parent / "dist" / "ocr-trigger-clicker" / "_internal" / "_update_feed.py"
    if not f.exists():
        sys.exit("❌ 防呆失敗：dist 內找不到 _update_feed.py")
    got = f.read_text(encoding="utf-8")
    if expected_url not in got:
        sys.exit(f"❌ 防呆失敗：烘入的 feed 與目標不符\n期望: {expected_url}\n實際: {got}")
    print(f"✓ feed 防呆通過: {expected_url}")


def _read_version(here: Path) -> str:
    m = re.search(
        r'__version__\s*=\s*"([^"]+)"', (here / "_version.py").read_text(encoding="utf-8")
    )
    if not m:
        sys.exit("❌ 無法從 _version.py 讀取版號")
    return m.group(1)


def read_release_notes(here: Path, version: str) -> str:
    """從 docs/dev/CHANGELOG.md 取出 `## [v{version}]` 區塊（去除首尾空行）。

    與 release.ps1 的解析規則一致；找不到區塊回空字串（release.ps1 會先擋掉，
    這裡僅靜默帶空，vpk 就不嵌入 notes）。
    """
    text = (here / "docs" / "dev" / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(
        rf"^## \[v{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not m:
        return ""
    lines = m.group(1).splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def pack_velopack():
    """Velopack 打包：產生 Setup.exe／full.nupkg／delta（若有前版）至 Releases/。"""
    import subprocess
    import tempfile

    here = Path(__file__).parent
    version = _read_version(here)
    cmd = [
        "vpk",
        "pack",
        "--packId",
        "OCRTriggerClicker",
        "--packVersion",
        version,
        "--packDir",
        str(here / "dist" / "ocr-trigger-clicker"),
        "--mainExe",
        "ocr-trigger-clicker.exe",
        "--outputDir",
        str(here / "Releases"),
    ]
    # 內嵌發行說明：用戶端 UpdateInfo.NotesMarkdown 來自 nupkg manifest，
    # 沒帶這個參數，更新彈窗只會顯示「無法取得更新說明」（GitHub release body 不影響）
    notes = read_release_notes(here, version)
    if notes:
        f = Path(tempfile.gettempdir()) / f"ocr_vpk_notes_{version}.md"
        f.write_text(notes, encoding="utf-8")
        cmd += ["--releaseNotes", str(f)]
    else:
        print("⚠️ CHANGELOG 無 v%s 區塊，vpk 不嵌入發行說明" % version)
    print("\n=== Velopack 打包（vpk pack）===")
    print(" ".join(cmd))
    r = subprocess.run(cmd, cwd=str(here))
    if r.returncode != 0:
        sys.exit(r.returncode)


if __name__ == "__main__":
    _build_here = Path(__file__).parent
    # self-check：CHANGELOG 解析壞掉會讓更新彈窗空白，先抓出來
    _notes = read_release_notes(_build_here, _read_version(_build_here))
    assert _notes.strip(), "self-check 失敗：CHANGELOG 找不到當前版本的發行說明區塊"
    assert "請下載" in _notes, "self-check 失敗：發行說明缺少「請下載」提示行"
    print("✓ 發行說明 self-check 通過（%d 字）" % len(_notes))
    print("OCR Trigger Clicker - 打包工具")
    print(f"工作目錄: {Path.cwd()}")
    print(f"腳本目錄: {_build_here}")
    print()
    try:
        main()
    except Exception as e:
        print(f"\n❌ 打包程式異常終止: {e}")
        import traceback

        traceback.print_exc()
