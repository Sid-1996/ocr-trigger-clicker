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
        print(f'      cd "{__file__}"')
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

    custom_dir = here / "custom_models"
    if custom_dir.exists():
        for f in custom_dir.iterdir():
            if f.is_file():
                datas.append((str(f), "custom_models"))
        print(f"找到 {len(list(custom_dir.iterdir()))} 個自訂模型檔")

    # 核心模組 ─ 保留 core/ gui/ 目錄結構
    py_datas = [
        ("core/01_screenshot.py", "core"),
        ("core/02_ocr_engine.py", "core"),
        ("core/03_ahk_socket.py", "core"),
        ("core/04_rule_engine.py", "core"),
        ("core/05_main_loop.py", "core"),
        ("core/10_performance_monitor.py", "core"),
        ("gui/06_gui_main.py", "gui"),
        ("gui/07_gui_roi.py", "gui"),
        ("gui/09_ocr_debug.py", "gui"),
        ("gui/13_gui_click_picker.py", "gui"),
        ("build.py", "."),
        ("_loader.py", "."),
    ]
    for rel, dest in py_datas:
        f = here / rel
        if f.exists():
            datas.append((str(f), dest))

    hidden = [
        "rapidocr_onnxruntime",
        "onnxruntime",
        "cv2",
        "pygetwindow",
        "mss",
        "numpy",
        "PIL",
        "pyclipper",
        "shapely",
        "yaml",
        "tqdm",
    ]

    exclude = [
        "torch",
        "torchvision",
        "torchaudio",
        "pandas",
        "scipy",
        "matplotlib",
        "sympy",
        "sentry_sdk",
        "fsspec",
        "pydantic",
        "rich",
        "urllib3",
        "cryptography",
        "pygments",
        "chardet",
        "openpyxl",
        "jinja2",
        "anyio",
        "httpcore",
        "httpx",
    ]

    args = [
        "--onefile",
        "--windowed",
        "--name=ocr-trigger-clicker",
        "--distpath=" + str(here / "dist"),
        "--workpath=" + str(here / "build"),
        "--specpath=" + str(here),
        "--noconfirm",
    ]
    for h in hidden:
        args.append(f"--hidden-import={h}")
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
    print("輸出: dist\\ocr-trigger-clicker.exe")
    print(f"資料檔案: {len(datas)} 項")
    print(f"隱藏 import: {len(hidden)} 項")
    print(f"排除模組: {len(exclude)} 項")
    print()

    PyInstaller.__main__.run(args)

    exe = here / "dist" / "ocr-trigger-clicker.exe"
    if exe.exists():
        print(f"\n打包成功: {exe}")
    else:
        print("\n打包失敗")


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
