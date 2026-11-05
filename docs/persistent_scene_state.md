# Persistent Scene State V1

此系統記錄**導演預計發生的狀態**，不讀取影片內容，也不宣稱影片真的完成服裝、道具或環境變化。

## 啟用與相容性

新專案預設勾選「跨段狀態持續 V1」，需同時啟用9B。可獨立於全曲事件規劃開關使用；獨立分段、末幀接續、自動／武打導演與既有音訊分段都可沿用。舊專案沒有 `scene_state_version=1` 時保持舊流程，不把已生成專案混入新帳本。Face Lock 改為只鎖定臉部身分；髮型、服裝、妝容、傷痕跟隨明確指令與狀態。

啟用時，原有全曲事件規劃（若有）之後，會多一次9B初始狀態建模。每段仍由原本本地改寫模型同時產出 H3 提示詞和狀態變更，不另設語意審查模型。格式、媒體引用或狀態轉換錯誤最多修復一次；仍錯誤時保存失敗資料並停止，可續跑，不以失去狀態的整首控制詞偷偷回退。

## 資料結構

`PersistentSceneState` 是具名結構：

- `character_states[subject_id]`：原始圖片索引 `identity_reference`、`hairstyle`、`garments`、`current_outfit`、`removed_garments`、`appearance_changes`、`injuries`、`held_props`、`location`。
- 每件 `garments[garment_id]`：固定ID、類型、材質、顏色、`current_status`、`current_location`。狀態支援 worn、unfastened、partially_removed、removed、held、placed。`current_outfit` 與 `removed_garments` 由程式衍生，不由模型重填。
- `environment_states[scene_id]`：`active_location`、`persistent_changes`、`damaged_objects`、`prop_positions`。
- `narrative_states`：完成事件、當前未完成事件、待處理事件、保留終局事件，以及上一段事件描述／是否完成／狀態變更。
- `timeline`：目前段落索引、來源起訖時間、全曲長度。時間由應用程式給定，模型不能覆寫。

`scene_state.json` 另含事件目錄：事件ID、描述、是否可重複、是否終局、前置事件、允許的操作，以及初始化／事件目錄雜湊和有序提交清單。角色、衣物、事件、場景的ID來自此專案，沒有固定姓名、性別或劇情模板。沒有相關服裝變化的角色可不設衣物，不強套人類衣服給動物或吉祥物。

## 每段的傳遞

1. 取上一段提交的 `scene_state_out`，覆上本段真實時間；第一段用一次性初始狀態。
2. 明確提供上一段已規劃事件與完成狀態、造成的變更、全曲已完成ID、待處理與保留終局ID，以及當段音樂／SRT資料。
3. 9B 回傳 JSON：`clip_prompt`、依順序的 `planned_events`、本段完成的 `completed_events`、`state_transitions`。每項變更綁定事件ID和操作，並帶正確的 `from` 值。
4. 程式套用合法變更，計算完整 `scene_state_out` 和剩餘事件；模型不能直接用一份全新快照重置狀態。若回傳額外快照，必須和程式衍生值一致。
5. 保存本段規劃快照與提示詞，才開始影片生成。片段通過原有尺寸／幀數有效性檢查並保存後，提交規劃狀態供下一段使用。這個提交代表片段成功保存，**不代表畫面內容已驗證**。

規則檢查固定事件ID、前置依賴、完成狀態、衣物狀態轉換、明確復原授權與時間窗，不審查鏡頭創意。已完成且不可重複的事件不得重播。已移除衣物只能透過目錄明確授權的 dress 事件穿回；清除傷痕／持續變化需 heal／restore 事件。非最終段連「開始」保留終局事件都不允許。普通鏡頭可以自然結束，不必另造懸念。

## 紀錄與續跑

- 根帳本：`scene_state.json`。
- 每段：`00_scene_state.json`、`01_scene_state.json`……，包含 `clip_index`、`scene_state_in`、`planned_events`、`state_transitions`、`scene_state_out`、雜湊、planned／committed 狀態與 `visual_verified:false`。
- 格式失敗：`XX_scene_state_attempt.json`，包含輸入、錯誤和模型回覆節錄。
- 重新規劃／回復時保留 `*_history_*.json`。前端選擇提示詞段落後可展開狀態Debug；另有已提交段數摘要。

生成失敗只留下草稿，不提前提交。續跑會驗證雜湊鏈，重用同一份輸入與準備好的提示詞／狀態配對；不重建初始服裝。若較早片段遺失或需重新規劃，從該段回復並使後續提示詞／狀態失效，將受影響的舊片段改存歷史檔名供追查，避免續跑把舊影片誤當作新狀態的產物。重用GPU歷史結果前，另比對當次提示詞雜湊；新提示詞／狀態草稿保存後清除舊任務ID與待重寫旗標，避免失敗重試反覆規劃或錯接舊結果。

程式介面 `restore_clip_input(work, index)` 可取回指定段落歷史輸入。沒有新增「任意重做一段成功影片」的HTTP按鈕；現有續跑路徑會在缺失片段恢復相應輸入。原有已完成段落仍會跳過。

## 保證範圍

狀態帳本與合法轉換可由程式驗證，衣物／道具狀態不會因讀取新段落自動重置。自然語言 `clip_prompt` 是否逐項遵循帳本，及 H3 實際畫面是否遵循提示詞，仍取決於模型並需看片確認。沒有影片視覺分析時，不能宣稱敵人已真的倒下、桌子已真的翻倒或衣服已真的移除。此系統不強制攝影機位置、焦段、景別、鏡頭數量或末幀接續，也不改動H3採樣參數或武打動作配方。
