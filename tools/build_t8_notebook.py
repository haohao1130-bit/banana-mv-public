"""Build a clickable public T8 test entry without changing normal Colab notebooks."""
import copy
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BRANCH='experiment/native9b-t8-policy-ab'


def build():
    source_path=next(p for p in (ROOT/'Banana_MV_Public.ipynb',
                                ROOT/'public_templates/Banana_MV_Public.ipynb',
                                ROOT/'Banana_MV_T8_Test.ipynb') if p.is_file())
    nb=copy.deepcopy(json.loads(source_path.read_text(encoding='utf-8')))
    def source(index,text):nb['cells'][index]['source']=text.splitlines(True)
    source(0,'''# 🍌 Banana MV｜T8 測試版

沿用原本 H3 專用 9B 與 MV 介面，預設開啟固定版 T8 H3/AUTO 攝影政策。這是未經真實 GPU 成片驗收的實驗版。

選擇原本可用的 GPU，依序按①②③，再點③輸出的「打開大乘蕉宗 MV 製作所」。先用約 15 秒音訊建立新任務測試。

③的 T8_STORYBOARD 預設勾選；取消後重新執行③可改回原政策，建立新任務才會重新寫稿。原本的長鏡／動態切鏡、故事與生成設定仍在前端。

專案另存 MyDrive/BananaMV_T8_Test，與正式作品分開。首次使用不需要 GitHub Token；HF_TOKEN 仍可選。
''')
    source(1,f'''#@title ① 安裝 Banana MV T8 測試版
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH={BRANCH!r}
PROJECT=Path('/content/banana-mv-t8-test')
if PROJECT.exists():
    result=subprocess.run(['git','-C',str(PROJECT),'branch','--show-current'],capture_output=True,text=True)
    if result.returncode or result.stdout.strip()!=BRANCH or not (PROJECT/'banana_mv/t8_storyboard.py').is_file():
        raise RuntimeError('此執行階段的程式不是 T8 測試版，請使用新的 Colab 執行階段。')
    print('沿用本執行階段的 T8 程式；要更新請開新的執行階段。')
else:
    PROJECT.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='banana-t8-',dir=PROJECT.parent) as scratch:
        checkout=Path(scratch)/'checkout'
        result=subprocess.run(['git','-c','credential.helper=','clone','--depth','1','--branch',BRANCH,
                               'https://github.com/haohao1130-bit/banana-mv-public.git',str(checkout)],
                              env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_ASKPASS='/bin/false'),capture_output=True,text=True)
        if result.returncode:raise RuntimeError('T8 測試版下載失敗，請確認網路；不需要 GitHub Token。')
        shutil.move(str(checkout),str(PROJECT))
print('已載入 commit:',subprocess.check_output(['git','-C',str(PROJECT),'rev-parse','HEAD'],text=True).strip())
sys.path.insert(0,str(PROJECT));sys.path.insert(0,str(PROJECT/'tools'))
import colab_runtime as runtime
if Path(runtime.__file__).resolve().parent!=PROJECT/'tools':
    raise RuntimeError('核心已載入其他版本，請開新的執行階段。')
runtime.install(globals())
''')
    source(2,'''#@title ② 下載模型（使用原本的 H3 專用 9B）
USE_DRIVE_CACHE = False #@param {type:"boolean"}
runtime.download(globals(), include_rewriter=True, use_drive_cache=USE_DRIVE_CACHE)
''')
    source(3,'''#@title ③ 啟動 T8 測試版並開啟 MV 介面
T8_STORYBOARD = True #@param {type:"boolean"}
TRACE_REWRITER = True #@param {type:"boolean"}
SAVE_TO_DRIVE = True #@param {type:"boolean"}
runtime.launch(globals(), save_to_drive=SAVE_TO_DRIVE)
''')
    source(4,'''## 開始測試

開啟③輸出的 MV 介面，上傳角色圖與原曲，保留「使用本地 9B 模型優化提示詞」，選擇導演模式後建立新任務。

③顯示「T8 H3/AUTO 已開啟」才代表設定成功；完整輸入與原始輸出另存 rewrite_traces。舊提示詞與回爐不會自動改寫。

勾選保存時，素材、作品與紀錄在 MyDrive/BananaMV_T8_Test。這個入口只跑選定政策，不會自動做兩次生成；同計畫 A/B 仍使用 tools/compare_t8.py。

要更換政策時，等任務完成，再調整③的勾選並重新執行③，然後建立新任務。不要同時操作另一個正式 MV 前端或 ComfyUI 佇列。
''')
    for i,c in enumerate(nb['cells']):c['id']=f'banana-t8-{i:02d}'
    (ROOT/'Banana_MV_T8_Test.ipynb').write_text(json.dumps(nb,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':build()
