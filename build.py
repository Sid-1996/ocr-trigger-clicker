import os
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
        print("請先安裝 PyInstaller: pip install pyinstaller")
        sys.exit(1)

    here = Path(__file__).parent

    print("搜尋 RapidOCR 模型檔案...")
    try:
        import rapidocr_onnxruntime
    except ModuleNotFoundError:
        print("\n❌ 找不到 rapidocr_onnxruntime 模組")
        print(f"   當前 Python: {sys.executable}")
        print(f"   工作目錄: {Path.cwd()}")
        print()
        print("   請確認已在正確的 Python 環境中執行：")
        print("   1. 啟動虛擬環境（如有）：venv\\Scripts\\activate")
        print("   2. 安裝依賴：pip install rapidocr-onnxruntime")
        print("   3. 或直接在專案目錄執行：")
        print(f'      cd "{here}"')
        print(f'      "{sys.executable}" build.py')
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

    ahk_src = here / "clicker.ahk"
    if ahk_src.exists():
        datas.append((str(ahk_src), "."))

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

    # 核心模組 ─ 保留 core/ gui/ 目錄結構
    # _loader.load_sibling() 動態載入的 .py 必須列在此處
    # 缺漏 → EXE 啟動 FileNotFoundError（PyInstaller 靜態分析無法追蹤）
    py_datas = [
        ("core/00_global_hotkey.py", "core"),
        ("core/00_logging_config.py", "core"),
        ("core/01_screenshot.py", "core"),
        ("core/02_ocr_engine.py", "core"),
        ("core/03_ahk_socket.py", "core"),
        ("core/04_rule_engine.py", "core"),
        ("core/rule_models.py", "core"),
        ("core/rule_migration.py", "core"),
        ("core/rule_serialization.py", "core"),
        ("core/task_management.py", "core"),
        ("core/run_config.py", "core"),
        ("core/file_utils.py", "core"),
        ("core/05_main_loop.py", "core"),
        ("core/10_performance_monitor.py", "core"),
        ("core/11_template_matching.py", "core"),
        ("core/12_updater.py", "core"),
        ("core/trigger_log.py", "core"),
        ("gui/06_gui_main.py", "gui"),
        ("gui/07_gui_roi.py", "gui"),
        ("gui/09_ocr_debug.py", "gui"),
        ("gui/13_gui_click_picker.py", "gui"),
        ("gui/14_capture_region.py", "gui"),
        ("gui/group_settings_controller.py", "gui"),
        ("gui/screenshot_controller.py", "gui"),
        ("gui/rule_config_controller.py", "gui"),
        ("gui/test_run_controller.py", "gui"),
        ("build.py", "."),
        ("_loader.py", "."),
        ("i18n/__init__.py", "i18n"),
    ]
    for rel, dest in py_datas:
        f = here / rel
        if f.exists():
            datas.append((str(f), dest))

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
        "pynput",
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

    exe = here / "dist" / "ocr-trigger-clicker" / "ocr-trigger-clicker.exe"
    if exe.exists():
        print(f"\n打包成功: {exe}")
        # 清理 build/ 暫存（spec 保留供除錯）
        import shutil

        shutil.rmtree(here / "build", ignore_errors=True)
        build_updater()
    else:
        print("\n打包失敗")


def build_updater():
    import PyInstaller.__main__

    here = Path(__file__).parent
    args = [
        "--onefile",
        "--windowed",
        "--name=updater",
        "--distpath=" + str(here / "dist" / "ocr-trigger-clicker"),
        "--workpath=" + str(here / "build_updater"),
        "--specpath=" + str(here),
        "--noconfirm",
        str(here / "updater_main.py"),
    ]
    print("\n=== 打包獨立 updater.exe ===")
    PyInstaller.__main__.run(args)
    updater_exe = here / "dist" / "ocr-trigger-clicker" / "updater.exe"
    if updater_exe.exists():
        print(f"updater 打包成功: {updater_exe}")
        import shutil

        shutil.rmtree(here / "build_updater", ignore_errors=True)
    else:
        print("updater 打包失敗")


if __name__ == "__main__":
    _build_here = Path(__file__).parent
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
