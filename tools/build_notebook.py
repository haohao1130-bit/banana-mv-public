"""Rebuild the public Colab notebook from reviewable source."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REPOSITORY='haohao1130-bit/banana-mv-public'

def md(text):
    return {'cell_type':'markdown','metadata':{},'source':text.splitlines(True)}

def code(text):
    return {'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':text.splitlines(True)}

cells=[
md(f'''# 🍌 Banana MV｜大乘蕉宗公開煉丹房

一張參考圖、一首歌，交給本地 AI 導演製作 MV。角色依你上傳的圖片指定，不綁定任何固定人物。

**使用自己的 Colab GPU 與額度。** 執行階段 → 變更執行階段類型 → 選擇 **G4 GPU**，依序執行①②③。

第一次請用 **5 秒音訊** 測試。模型下載需要數十 GB 磁碟空間；目前配置需要 CUDA capability ≥ 8.0、驅動 ≥ 580。Colab 分配的 GPU 與驅動可能不同，以①檢查結果為準。

公開版不需要 GitHub Token。可在左側🔑加入自己的唯讀 `HF_TOKEN` 以改善模型下載；未設定時嘗試匿名下載。只在 Colab 密鑰填入，勿貼到程式或輸出。

[使用說明](https://github.com/{REPOSITORY}#readme) · [問題回報](https://github.com/{REPOSITORY}/issues)

**遠景修臉（選用）**：①預設勾選 `INSTALL_FACE_REFINE`，執行後再跑②③。開啟網頁後，在生成設定勾選實驗性修臉。首次使用可能下載人臉辨識模型，修臉會額外花時間。完成後可並排播放與下載母片及修臉版，兩支 MP4 也會另存到成品資料夾。
'''),
code('#@title ① 安裝 Banana MV、ComfyUI 與外掛（含選用修臉）\n#@markdown **預設安裝遠景修臉**。取消勾選可略過安裝。\nINSTALL_FACE_REFINE = True #@param {type:"boolean"}\n'+(ROOT/'tools/public_clone.py').read_text()+f'''
PROJECT=Path('/content/banana-mv-public')
clone_project(PROJECT,'https://github.com/{REPOSITORY}.git')
sys.path.insert(0,str(PROJECT/'tools'))
import colab_runtime as runtime
face_installer = PROJECT / 'tools/install_face_refine.py'
if INSTALL_FACE_REFINE and not face_installer.is_file():
    raise RuntimeError('這個執行階段沿用了舊版程式。請中斷連線並刪除執行階段，連線後重跑①。')

runtime.install(globals())
if INSTALL_FACE_REFINE:
    subprocess.run([sys.executable, str(face_installer),
                    '--comfy-source', str(COMFY), '--comfy-base', str(COMFY)], check=True)
    print('修臉安裝完成。接著執行②③，再到生成設定開啟實驗性修臉。')
'''),
code('''#@title ② 下載模型
INCLUDE_REWRITER = True #@param {type:"boolean"}
USE_DRIVE_CACHE = False #@param {type:"boolean"}
# 不下載 9B 時，請在前端取消「使用本地 9B 模型優化提示詞」。
runtime.download(globals(), include_rewriter=INCLUDE_REWRITER, use_drive_cache=USE_DRIVE_CACHE)
'''),
code('''#@title ③ 啟動 Banana MV 並開啟介面
SAVE_TO_DRIVE = True #@param {type:"boolean"}
runtime.launch(globals(), save_to_drive=SAVE_TO_DRIVE)
'''),
md('''## 開爐與續跑

1. 上傳主唱參考圖與原歌曲。需要其他角色或場景，開啟多圖參考。
2. 提示詞用 `@圖片1`、`@圖片2` 指定角色與場景用途；未提供參考圖的配角可直接用文字描述。
3. 選擇導演模式，按「開爐煉製 MV」。生成紀錄可看段落進度與實際送入 H3 的提示詞。
4. 完成後下載完整 MV。先確認 5 秒測試結果，再增加歌曲長度（最多五分鐘）。

③勾選保存到 Drive 後，專案存在你自己的 `MyDrive/BananaMV`。再次啟動時掛載同一個 Drive，開啟原專案並按「續跑未完成段落」；不需重傳素材。未保存的資料可能隨執行階段回收而消失。

生成期間勿另外排入 ComfyUI 任務，也不要讓兩個執行階段同時續跑同一專案。關閉下方 ComfyUI 不會解除 Colab GPU 配置；結束 GPU 使用請在 Colab 中斷並刪除執行階段。
'''),
code('''#@title 🔍 診斷（分享前請移除私人路徑、素材及任何密鑰）
subprocess.run(['nvidia-smi'])
for name in ('comfyui','banana_mv'):
    log=Path('/content')/(name+'.log')
    print(name,log.read_text(errors='replace')[-4000:] if log.exists() else '尚無紀錄')
'''),
code('''#@title 🧯 手動關閉 ComfyUI（全部執行只顯示按鈕）
runtime.show_shutdown_control(globals())
''')]
for index,cell in enumerate(cells):
    cell['id']=f'banana-public-{index:02d}'
nb={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3'},'language_info':{'name':'python'},'colab':{'provenance':[],'gpuType':'G4'},'accelerator':'GPU'},'cells':cells}
(ROOT/'Banana_MV_Public.ipynb').write_text(json.dumps(nb,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
# Name-distinct Colab entrypoint. Keep the historical filename so saved Colab
# links, GitHub bookmarks and existing builder checks still work.
named_nb=json.loads(json.dumps(nb,ensure_ascii=False))
named_nb['cells'][0]['source'][0]='# 🍌 BANANAMV CLASSIC｜標準公開版\n'
(ROOT/'BANANAMV_CLASSIC_PUBLIC.ipynb').write_text(json.dumps(named_nb,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
