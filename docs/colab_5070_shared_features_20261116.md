# Colab Python Slot｜5070 共用功能回移（2026-11-16）

此實驗分支的 Colab 筆記本固定拉取 `experiment/colab-python-slot-5070-backport`，保留獨立的 Drive 資料夾 `MyDrive/BananaMVClassicPythonSlot`。不修改公開 Classic 主線或 `MyDrive/BananaMV`。

從 5070 本機導入的共用工作流：

- Python 先分配當段通告單，識別章節下一行的 `時間：`，將明確的歌詞事件定位到 SRT 時間，不提前把未來段落送進 9B。
- 9B 用熟悉的 H3 Ref2VA 六段式安排運鏡、動作與當段聲部；歌手區間合併同一聲部的連續字幕。
- 緊急停爐對 ComfyUI 指定 `prompt_id` 取消當前 9B/H3 任務，不讓尚未完成的影片進入成片。
- 每段可「重配丹方」、編輯／貼上完整 H3 提示詞、單段回爐；中斷段落初煉成功後自動續跑後續段落。先前完成的影片保留。
- 毛片預覽優先播放對應版本的 RAW（含 H3 原音軌），沒有 RAW 才顯示裁切版；正式合成仍使用 `part.mp4`。
- 舊 `legacy_ordered` 計畫重配／續跑時先備份，僅重寫未完成段落的時間通告單；已完成的作品不被直接覆蓋。

Colab 相容性：保留 **720P／10 秒**與獨立分段預設，ComfyUI 8188、MV UI 8190、Colab 自有 Drive 缓存和原本的模型下載。Windows 5070 桌面重啟／切換、NVEncC 升頻與 5070 限定 FaceRefine 在 Colab 不開放；這些需要另一套雲端安裝／後端支持，不會假裝可用。

驗證：在 GitHub Actions 跑純程式回歸、Node 前端測試、ffmpeg RAW 串流、筆記本資料路徑與預設值；**不等於已在實際 Colab GPU 跑 H3 全片**。
