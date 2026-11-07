# 在原本成功的 9B／ComfyUI 做 T8 政策對照

本實驗不安裝另一套 ComfyUI、不下載或切換大模型、不改上游全片規劃或 H3 採樣參數。預設關閉；正式 A 保持既有提示，B 才替換逐段攝影政策。沒有 GPU 成功紀錄前，不代表已改善攝影品質。

## A 與 B 的差別

- A：目前完整政策，包括 AUTO_FILMING、DYNAMIC_EDITING、完整攝影強度與腰部以上偏好。
- B：固定 T8 H3／AUTO 加入 system 一次，取代 AUTO_FILMING／DYNAMIC_EDITING 和強度中的重複攝影配方。強度保留為風格／能量背景，保留動態切鏡關閉選項。把無條件歌手近景偏好換成「表演鏡頭嘴形可讀；其他畫面依事件資訊決定」。
- 兩組保留同一故事計畫、改編權限、角色／表演規則、聲部、原曲、局部時間及收尾。上游分配器不接 T8。

這是整組攝影政策對照，不是只加一句話的單變因測試。B 的結果不能歸功於 T8 某一句。T8 原文不負責增加創作權限；保留原導演／表演職責，不能宣稱「裝上就會爆發」。沒有改寫 T8 原文。

## 在現有 Colab 執行

先保留已成功安裝且 ComfyUI 可工作的環境，等現有任務結束。不要同時執行正式 MV 或其他 Comfy 工作。從此實驗分支啟動新的 Python 程序；不需要搬入隔離 repo 的安裝器。

在原本的 BananaMV 原碼目錄使用：

```bash
git fetch origin experiment/native9b-t8-policy-ab
git switch experiment/native9b-t8-policy-ab
python tools/compare_t8.py --project /實際的任務資料夾 --clip 0 --output /全新的測試輸出資料夾 --seed 42
```

程式從原環境 `BANANA_DATA/config.json` 取得既有 ComfyUI／模型設定，並從已存工作讀取參考素材 ID。資料夾要同時有 status.json、director_plan.json，且原始素材庫仍存在。若搬移過素材，明確使用 `--images 原圖1 原圖2 ...` 指定原始順序；不是把合併圖拆成新編號。chain 的非首段還需 `--tail 同一張實際前段末幀`。

首次明確執行此測試時，只下載固定 T8 文字來源並驗證；不執行、import 或發布上游節點原碼。若網路或 hash 失敗即停止，不回退 A 冒充 B。

以上先只跑兩次 9B，不做 H3。要做真實 H3 對照，再指定原本成功任務保存的完整 `--workflow /.../00_workflow_api.json`。該工作流所需圖片／裁切音訊必須仍在既有 Comfy input 位置；找不到會停止，不偷偷換素材或音訊。兩組使用同一工作流，只替換 node 7 prompt；保留工作流內的 render seeds，`--seed` 是 9B seed。

輸出目錄不能已存在，避免誤用保存稿。任何排隊或等待失敗後停止整個對照，不自動提交另一組；先檢查既有 Comfy 佇列。既有 director_plan 直接凍結使用，不觸發全片重新規劃。H3 選項會使用原工作流的輸出節點，不重新實作音訊組裝。

## 保存的證據

- comparison.json：本次程序 commit（非 Git 目錄為 null）、import 時的程式 hash、完整 guide 與 hash、凍結請求／當段／原圖 hash、T8 來源及兩組狀態。
- 每組 trace：完整 system、實際 chat／TextGenerate 圖表、實際 9B seed／參數、轉為 JPEG 後真正送入的圖片與 hash、prompt_id、raw response／history；失敗保留 error.json。
- 每組 prompt.txt：正規化後的原生提示詞，沒有另做語意修稿。
- 指定 H3 時保存實際 workflow、Comfy history 與可找到的 MP4。其他條件保持相同，不對成片做自動好壞評分。

請人工比較：表演進程、表情是否超出參考圖、事件細節和反應、真正的切鏡與運鏡、男女聲部、地理隔離、事件狀態、音訊及新增對白。小樣本只說明該樣本。9B 沒有直接聽原曲，不能宣稱辨識實際演唱情緒。

## 固定來源與授權界線

來源：https://github.com/T8mars/comfyui-minimax-h3-prompt-enhancer-T8

commit `25a8caafac8d4d77f5d0e11b6c01f1491903d5f5`，檔案 storyboard_director.py，H3／AUTO revision 1.0.0。adapter 驗證 Git blob、檔案 SHA256 與抽取文字 SHA256，僅 AST 擷取字串、不 eval／exec。來源 code 留在忽略的 cache/t8，不隨本分支發布。未確認上游可再分發授權，不能把它整份搬進公開原碼。

## 關閉與正式設定

對照工具本身不改 config.json、不改正式任務或保存稿。一般伺服器預設仍為 A。若自行在 config.json 設 t8_storyboard=true，逐段新寫稿才使用 B；移除或改 false 即回 A，載入本分支程式後才有效。需 t8_source_path 指向已驗證來源（不設定時使用原碼目錄 cache/t8）。原伺服器若尚未重啟，不會因磁碟更新自動換政策。舊快取／回爐保留舊提示詞，不能當作新政策驗證。

另提供 [可直接點開的 T8 測試 Colab](https://colab.research.google.com/github/haohao1130-bit/banana-mv-public/blob/experiment/native9b-t8-policy-ab/Banana_MV_T8_Test.ipynb)：依序①②③，T8 預設開啟，③可勾選關閉，使用原本 MV 前端。資料另存 BananaMV_T8_Test，啟用成功會明確顯示固定版本；取得／驗證來源失敗時不啟動。這個入口是單政策測試，不會自動跑兩組。原本正式筆記本及主分支未更動；尚未真實 GPU 驗收。
