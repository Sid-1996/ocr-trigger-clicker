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
        print(f'      cd "{os.path.dirname(__file__)}"')
        print(f'      "{sys.executable}" build.py')
        sys.exit(1)

    rap_path = Path(rapidocr_onnxruntime.__file__).parent

    datas = []
    for pattern in ["*.onnx", "*.yaml", "*.json", "*.txt"]:
        for f in rap_path.rglob(pattern):
            if f.is_file():
                rel = f.relative_to(rap_path)
                datas.append((str(f), str(rel.parent)))
    print(f"找到 {len(datas)} 個模型/資源檔")

    ahk_src = here / "clicker.ahk"
    if ahk_src.exists():
        datas.append((str(ahk_src), "."))

    py_datas = [
        "core/01_screenshot.py",
        "core/02_ocr_engine.py",
        "core/03_ahk_socket.py",
        "core/04_rule_engine.py",
        "core/05_main_loop.py",
        "core/10_performance_monitor.py",
        "gui/06_gui_main.py",
        "gui/07_gui_roi.py",
        "gui/08_gui_log.py",
        "gui/09_ocr_debug.py",
        "gui/13_gui_click_picker.py",
        "build.py",
    ]
    for fn in py_datas:
        f = here / fn
        if f.exists():
            datas.append((str(f), "."))

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

    args = [
        "--onefile",
        "--windowed",
        "--name=ocr-trigger-clicker",
        "--distpath=" + str(here / "dist"),
        "--workpath=" + str(here / "build"),
        "--specpath=" + str(here),
    ]
    for h in hidden:
        args.append(f"--hidden-import={h}")
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
    input("\n按 Enter 鍵結束...")
