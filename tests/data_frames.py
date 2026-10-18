"""測試用實境截圖（tests/data/，1920x1080 全視窗擷取，StarSavior 跑馬畫面）。

OCR 模擬測試共用的幀序列。預設只跑 CORE_FRAMES（維持測試套件標準速度）；
要看全部實境幀時設環境變數 OTC_FULL_FRAMES=1。

新增截圖：檔名用 ASCII（OpenCV imread 讀不了非 ASCII 路徑），再加入 ALL_FRAMES。
"""

import os

CORE_FRAMES = [
    "test.png",
    "test2.png",
    "test3.png",
    "starsavior_training_live.png",
]

ALL_FRAMES = [
    "test.png",
    "test2.png",
    "test3.png",
    "test4.png",
    "test5.png",
    "test6.png",
    "test7.png",
    "test8.png",
    "test9.png",
    "test10.png",
    "test11.png",
    "starsavior_training_live.png",
]

FRAMES = ALL_FRAMES if os.getenv("OTC_FULL_FRAMES") == "1" else CORE_FRAMES
