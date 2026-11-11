"""Rebuild the isolated Classic Python Slot notebook from the Classic template."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
nb=json.loads((ROOT / "BANANAMV_CLASSIC_PUBLIC.ipynb").read_text(encoding="utf-8"))
nb['cells'][0]['source']=[
 "# 🍌 BANANAMV CLASSIC｜PYTHON SLOT 實驗版\n",
 "\n",
 "**隔離實驗：Python 決定歌曲時間槽與事件範圍；9B 每次只寫一段原生 H3 攝影稿。**\n",
 "\n",
 "⚠️ 與 Classic 正式版不同。程式固定抓 `experiment/python-slot-director`，專案資料另存 `MyDrive/BananaMVClassicPythonSlot`，不讀寫正式版 `MyDrive/BananaMV`。\n",
 "\n",
 "使用自己的 Colab GPU。選 G4 GPU，依序執行 ①②③；請先用短歌或 30–60 秒裁切測試，確認後才跑整首。\n"
]
nb['cells'][1]['source']=[
 "#@title ① 安裝 CLASSIC Python Slot 實驗分支、ComfyUI 與外掛\n",
 "import os, sys, subprocess, shutil\n",
 "from pathlib import Path\n",
 "PROJECT = Path('/content/banana-mv-classic-python-slot')\n",
 "BRANCH = 'experiment/python-slot-director'\n",
 "REPOSITORY = 'https://github.com/haohao1130-bit/banana-mv-public.git'\n",
 "if not PROJECT.exists():\n",
 "    subprocess.run(['git', '-c', 'credential.helper=', 'clone', '--depth', '1', '--single-branch', '--branch', BRANCH, REPOSITORY, str(PROJECT)], check=True)\n",
 "else:\n",
 "    if not (PROJECT / 'tools/colab_runtime.py').is_file():\n",
 "        raise RuntimeError('實驗程式目錄不完整，請重建執行階段。')\n",
 "    current = subprocess.check_output(['git', '-C', str(PROJECT), 'branch', '--show-current'], text=True).strip()\n",
 "    if current != BRANCH:\n",
 "        raise RuntimeError(f'錯誤分支：{current}，應是 {BRANCH}。請使用全新執行階段。')\n",
 "print('✅ 已鎖定實驗分支：', BRANCH)\n",
 "sys.path.insert(0, str(PROJECT / 'tools'))\n",
 "import colab_runtime as runtime\n",
 "runtime.install(globals())\n"
]
nb['cells'][2]['source']=[
 "#@title ② 下載模型（實驗版）\n",
 "INCLUDE_REWRITER = True #@param {type:\"boolean\"}\n",
 "USE_DRIVE_CACHE = False #@param {type:\"boolean\"}\n",
 "# 不下載 9B 時，請在前端取消「使用本地 9B 模型優化提示詞」。\n",
 "runtime.download(globals(), include_rewriter=INCLUDE_REWRITER, use_drive_cache=USE_DRIVE_CACHE)\n"
]
nb['cells'][3]['source']=[
 "#@title ③ 啟動 CLASSIC Python Slot 實驗版\n",
 "SAVE_TO_DRIVE = True #@param {type:\"boolean\"}\n",
 "runtime.launch(globals(), save_to_drive=SAVE_TO_DRIVE, drive_folder='BananaMVClassicPythonSlot')\n"
]
nb['cells'][4]['source']=[
 "## 隔離實驗說明\n",
 "\n",
 "- 專用雲端路徑：`MyDrive/BananaMVClassicPythonSlot`。正式 Classic 仍使用 `MyDrive/BananaMV`。\n",
 "- 新建任務使用 Python Slot；既有 Classic MAIN 不受影響。\n",
 "- 先測試「先搓丹方」可否產生完整 28 槽，再選擇開爐，避免浪費 GPU。\n",
 "- 除了正式 Classic 原本的 ①②③ 與診斷格，其他行為沿用 Classic。\n"
]
for i,cell in enumerate(nb['cells']):
    cell['id']=f'banana-python-slot-{i:02d}'
(ROOT/'BANANAMV_CLASSIC_PYTHON_SLOT_EXPERIMENT.ipynb').write_text(json.dumps(nb,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
