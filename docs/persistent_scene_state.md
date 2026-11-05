# Persistent Scene State V1

此系統記錄**導演預計發生的狀態**，不讀取影片內容，也不宣稱影片真的完成服裝、道具或環境變化。

## 啟用與相容性

新專案預設勾選「跨段狀態持續 V1」，需同時啟用9B。可獨立於全曲事件規劃開關使用；獨立分段、末幀接續、自動／武打導演與既有音訊分段都可沿用。舊專案沒有 `scene_state_version=1` 時保持舊流程，不把已生成專案混入新帳本。Face Lock 改為只鎖定臉部身分；髮型、服裝、妝容、傷痕跟隨明確指令與狀態。

啟用時，原有全曲事件規劃（若有）之後，會多一次9B初始狀態建模。每段仍由原本本地改寫模型同時產出 H3 提示詞和狀態變更，不另設語意審查模型。格式、媒體引用或狀態轉換錯誤最多修復一次；仍錯誤時保存失敗資料並停止，可續跑，不以失去狀態的整首控制詞偷偷回退。

## 初始化格式與診斷修正

初始化只接受一個根 JSON 物件，根層必須有 `initial_state` 和 `events`。`events` 不是衣物清單，也不是 `event_catalog` 對照表；必須是長度 1–128 的物件陣列，不能放進 `initial_state`。普通演唱 MV 可以只列使用者指定演唱的可重複事件，無須增加故事、武打或服裝變化。事件數不等於片段數。

以下是通過實際驗證器的最小範例；角色與場景可依需求填入，完整欄位見下方資料結構：

```json
{
  "initial_state": {"character_states": {}, "environment_states": {}},
  "events": [{
    "event_id": "E1",
    "description": "Perform the song requested by the user",
    "repeatable": true,
    "reserved_final": false,
    "depends_on": [],
    "allowed_operations": ["update"]
  }]
}
```

事件 Schema 與程式的 `INITIAL_EVENT_SCHEMA`、`event_catalog()` 一致：

| 欄位 | 驗證要求 | 省略時 |
| --- | --- | --- |
| `event_id` | 1–2000 字元非空白字串，全部事件中唯一 | 必填 |
| `description` | 1–2000 字元非空白字串 | 必填 |
| `repeatable` | JSON boolean | `false` |
| `reserved_final` | JSON boolean | `false` |
| `depends_on` | 無重複字串陣列，最多256項，每個ID必須存在且不能有循環 | `[]` |
| `allowed_operations` | 無重複字串陣列，最多256項；只能用 update/remove/dress/acquire/drop/use/damage/restore/heal/move | `[]` |

9B 提示詞要求輸出全部六個事件欄位；驗證器仍沿用舊版對可選欄位的預設值。沒有放寬空事件、未知依賴、循環或不存在的圖片引用。

每次新的初始化／格式修復都會在專案目錄保存：

- `scene_state_init_debug.json`：最近一次初始化的所有嘗試與最終狀態。
- `scene_state_init_<run_id>_00.json` 和 `_01.json`：每次原始回應的獨立歷史紀錄；重試或續跑不覆蓋以前的run。
- 紀錄包含 `raw_response`（完整原文）、`parsed_response`、根層 `events`、`events_present`、`nested_events`、`schema_validation_errors`、`stage` 和 `status`。
- 驗證錯誤帶具體 `path/code/message`，例如 `$.events[0].description` 缺失、`$.events` 為空或誤放在 `$.initial_state.events`。JSON 語法錯誤包含行／欄位置。具體錯誤亦寫入服務日誌，不把完整素材／提示詞印到日誌。

解析支援標準 JSON、BOM、常見單一 Markdown JSON 包裝和 `<think>` 包裝；不執行文字、不接受多份有歧義的JSON區塊或 NaN/Infinity。第一次格式失敗後，將**原始失敗回應和具體錯誤**連同原始使用者需求傳給9B，僅進行一次格式修復。修復不得改寫故事；對已解析出來的既有事件，會逐項比對已合法的ID、描述、旗標與操作，防止用另一段事件替換格式錯誤資料。原文完全無法解析時，故事保留依靠修復提示詞，並非額外語意模型驗證。

第二次仍失敗就回報真實錯誤及診斷檔名，不建立成功帳本、不開始Clip流程；生成服務連線錯誤只記錄並報錯，不偽裝成格式重試。初始化本身不刪除、搬移或清空既有影片。舊版未記錄的初始化原文無法事後還原，不能由籠統的「需有1–128個事件」訊息斷言是空陣列、缺失、型別錯誤或放錯層。

更新後須載入新版 Python 程式。既有 Colab bootstrap 會沿用執行階段的舊程式，建議新建執行階段後重跑①②③；保存在Drive的專案可續跑。這次無須修改H3參數、Face Lock、音訊標籤或分段設定。

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

### 已完成事件與本段可選事件分開

傳給9B的 `event_catalog` 只列當前可選事件：排除已完成的一次性事件，非最終段另排除保留終局。可重複演唱事件仍可選。完整完成紀錄仍在 `scene_state_in` 和 `completed_history_only_do_not_replay`，未到時機的終局另放 `reserved_future_only_do_not_execute`；歷史用來理解目前情況，不能當作本段待辦清單。真正驗證與磁碟帳本仍使用完整事件目錄，不刪掉歷史ID，也不把一次性事件擅改成可重複。

若本段是繼續演唱、反應或呈現目前局面，沒有新的目錄里程碑，可以回傳空的 `planned_events`、`completed_events` 和 `state_transitions`，搭配正常動態的 `clip_prompt`。不要求每段消耗新事件，也不為填清單而重演下車、奪物、首次攻擊或服裝變更。這不代表定格鏡頭，也不代表自動重置目前狀態。

若9B仍把已完成ID填回本段，錯誤會具體指出 `$.planned_events[index]`、事件ID與描述。一次受控重試會收到**完整失敗回應**、具體錯誤和目前狀態；它必須同時修正事件清單與提示詞中的重播動作，不能只刪ID仍保留重播文字。修復成功保存 `XX_scene_state_rewrite_debug.json`，失敗的 `XX_scene_state_attempt.json` 則保留兩次原始回應、解析結果與錯誤。沒有加上額外語意審查推論；提示詞與實際畫面仍須看片確認。

此更新沿用V1帳本，可在載入新程式後開啟原專案續跑。已完成片段的輸入／輸出狀態雜湊不變，第一段不因第二段改寫錯誤而重做。

## 紀錄與續跑

- 根帳本：`scene_state.json`。
- 每段：`00_scene_state.json`、`01_scene_state.json`……，包含 `clip_index`、`scene_state_in`、`planned_events`、`state_transitions`、`scene_state_out`、雜湊、planned／committed 狀態與 `visual_verified:false`。
- 格式失敗：`XX_scene_state_attempt.json`，包含輸入、錯誤和模型回覆節錄。
- 重新規劃／回復時保留 `*_history_*.json`。前端選擇提示詞段落後可展開狀態Debug；另有已提交段數摘要。

生成失敗只留下草稿，不提前提交。續跑會驗證雜湊鏈，重用同一份輸入與準備好的提示詞／狀態配對；不重建初始服裝。若較早片段遺失或需重新規劃，從該段回復並使後續提示詞／狀態失效，將受影響的舊片段改存歷史檔名供追查，避免續跑把舊影片誤當作新狀態的產物。重用GPU歷史結果前，另比對當次提示詞雜湊；新提示詞／狀態草稿保存後清除舊任務ID與待重寫旗標，避免失敗重試反覆規劃或錯接舊結果。

程式介面 `restore_clip_input(work, index)` 可取回指定段落歷史輸入。沒有新增「任意重做一段成功影片」的HTTP按鈕；現有續跑路徑會在缺失片段恢復相應輸入。原有已完成段落仍會跳過。

## 保證範圍

狀態帳本與合法轉換可由程式驗證，衣物／道具狀態不會因讀取新段落自動重置。自然語言 `clip_prompt` 是否逐項遵循帳本，及 H3 實際畫面是否遵循提示詞，仍取決於模型並需看片確認。沒有影片視覺分析時，不能宣稱敵人已真的倒下、桌子已真的翻倒或衣服已真的移除。此系統不強制攝影機位置、焦段、景別、鏡頭數量或末幀接續，也不改動H3採樣參數或武打動作配方。
