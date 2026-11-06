# Banana MV：原始拍法與獨立分段

給故事大綱、歌曲與參考圖，沿著主軸拍音樂 MV。保留人物分工、因果、轉折和指定結果；用演唱、故事、反應、細節與環境交錯呈現，不要求每個十秒都演完一場完整短劇。

## 導演與切鏡

目前分段寫手恢復最初 `b797c7e` 的 prompt-only 導演風格：使用當段模式、原本強度描述，以及「事件 → 行動 → 注意力 → 攝影 → 剪輯」。約 3–5 秒切鏡採用當時原文：

> Use motivated editorial cuts and distinct camera compositions around 3–5 seconds where possible; short transition shots may appear anywhere. Cuts are flexible, not fixed to segment boundaries.

這是攝影節奏指引，不是最低鏡數。不再計算 required_shots、不因單鏡而重試、不按字詞或固定寬中近模板補鏡。關閉動態切鏡時偏向長鏡；最後畫面停留時不引入新動作。主唱可見時採半身或更近，並遵守指定演唱角色。

全曲導演保留一次規劃，FREE 可濃縮次要情節並設計相容的演唱／故事穿插；FAITHFUL 保留原事件順序。兩者都守住角色、獨立場地、因果與指定結果。音樂資料提供節奏與強弱參考，不假裝辨識未提供的歌詞或副歌。沒有固定演唱占比，也不照每句歌詞發明新事件。

## 段落隔離

新任務預設 `scene_state_version=0`：全曲導演決定每段 event 和 cast，分段寫手只收到當段拍攝內容、當下角色外觀、場地、必要限制與適用的收尾要求。它不讀上一段的劇情、變身經過、已完成事件流水帳或整份大綱。回到同一場地／主唱可換拍法，不重演先前事件。

同一段先後出現的角色都列入 cast，但不要求同框。transitions 和 visibility 只描述當段交接；end_appearance 只描述當段內的外觀變化。原始 Picture N 不因角色退場或 cast 排序重新編號。上一段末幀只在使用者選擇接續模式時作為開場影像，不能變成另一個角色的身份圖。

舊專案仍依保存的 scene_state_version 使用原狀態機；這次不改舊計畫或已完成毛片，不重建第二套帳本。

## 格式、音訊與失敗處理

正常仍是 **1 次全曲規劃＋N 次畫面寫手**，不新增語意審查呼叫。程式組裝 H3 Ref2VA 六段：subject_definitions、summary、retention_analysis、detailed_description、overall_soundscape、non_diegetic_music；接手固定身份、參考圖與原音訊欄位。

寫手只寫帶鏡號的畫面描述；若專用模型仍回傳六段，只取其畫面區塊。可清理鏡頭前的簡短前言。檢查鏡號、時間、媒體引用與當段角色，但不檢查最低鏡數，也不宣稱能驗證故事語意、肢體或對嘴。

真實格式／引用錯誤使用原有有限重試預算；失敗只回報當段，保留完成片段供續跑。不再由程式把事件切成字詞、補成保底分鏡，避免改寫動作或把不同場地的角色標進每一鏡。重試不能偷偷改成全曲劇本。

原曲、24fps、影格切段、H3 採樣、注意力、LoRA、Seed 和丹藥檢查／回爐流程均沿用既有設定。生成時保留音訊對嘴驅動，毛片預覽無聲，完整合成混入原曲。

## 整首與片段

- full：ending_plan 保留 start_time、resolved_by、resolution，提前完成結果並抵達 closing_shot。短尾段完成已開始的收尾，不臨時開新場景。
- excerpt：ending_plan=null、closing_shot 為空；可完成局部事件，不硬製造整首勝利或謝幕。

結尾計畫與角色結束外觀使用不同變數，避免 end_appearance 覆寫 ending_plan。快取若已存有這類錯誤資料，顯示明確錯誤並要求新建任務，不偷偷改寫已保存計畫或重跑影片。

## 驗證範圍

測試覆蓋原始切鏡文字、單鏡不觸發湊數重試、當段隔離、固定原圖編號、角色交接、完整／片段結尾、壞快取拒絕、原曲路由及失敗續跑。測試使用模擬模型與 GPU；不代表已用真實 9B／H3 重現早期畫面品質。更新程式並重啟服務後，新建任務比較；已保存 prompt 不會自動重寫。
