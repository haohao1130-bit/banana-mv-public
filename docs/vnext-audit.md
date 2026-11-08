# VNext 獨立工程驗收（2026-11-09，離線驗收）

結論：修正可重現的設定及驗證漏洞；**GPU 品質尚未驗收，不能判定完整產品驗收通過**。
沒有合併或覆寫 main，沒有讀寫使用者的歷史作品。修正在 audit/vnext-regression 分支提出。

## 固定驗收輸入

| 倉庫 | 稽核起點 commit |
|---|---|
| `banana-film-studio` | `229f22ff95d0bfa6c55d86b41cec580ee08bd0c3` |
| `banana-film-public` | `65bfbfb6b014bba1b738d03bdfcfd4c363d12700` |
| `banana-mv-colab` | `42114f419816c3a9b0c872e57d2dc3032a8e885e` |
| `banana-mv-public` | `ebf338881af6c6af1c98ca6cfa536d06f2096c16` |

私有版使用 GitHub 連線下載上述 commit 的所有追蹤檔案；本機 snapshot 的逐檔 Git blob SHA 與遠端 tree 核對。
公開版使用完整 Git clone。私有版最近 100 筆以內的可取得 commit metadata 與關鍵 commit 差異透過 GitHub API 讀取。
並非宣稱逐行審查歷史上每一個 commit，審查集中於列明契約的現行路徑及相關變更。

官方依據：[MiniMax H3 Ref2VA guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/199b7d0e1fd95e7b3eafa8c15eca692534142427/skills/h3-prompt-writing/references/ref-en.txt)、
[shot/speaker base guide](https://github.com/MiniMax-AI/MiniMax-H3/blob/199b7d0e1fd95e7b3eafa8c15eca692534142427/skills/h3-prompt-writing/references/base-en.txt)。
六段順序、首鏡無時間碼、後續鏡頭時間嚴格遞增且位於片長內、Subject/Picture 分工與全域 speaker ID 均以此為依據。
fully_copy 是音訊保留意圖，不能拿提示詞通過當作模型已忠實複製歌曲的證據；成片透過原歌曲音軌合成另行保留歌曲。

## 已證實問題、重現與修正

| ID / 等級 | 原因與重現 | 最小修正 / 檔案 | 回歸證據 |
|---|---|---|---|
| F1 高 | film.start 未收到 mode 時，後端寫入 chain；前端預選 chain5，直接 API 與前端契約不符 | film.py：新建作品後端缺省改 chain5；既存 request 不遷移 | test_omitted_mode_defaults_chain5_at_real_start |
| F2 中 | write_prompt 只有 request 存在 auto_director 欄位才送出明確 adaptation 權限；舊 request 遺漏該欄位時沒有該交接欄位 | film.py：所有 writer 委託都明示僅攝影；原 system 已有限制，未證實實際影片因此改編 | test_writer_authority_present_for_legacy_request_without_auto_flag；原 dynamic 測試失敗後通過 |
| V1 高 | 新 writer 的相容邏輯允許非六段文字；MV 原生輸出也不要求 retention 中 fully_copy。可回傳純文字或 reference/partially_copy 而當成交稿成功 | server.py / film.py：新作品持久化 h3_validation_version=1；shoot_plan.py / film.py：新寫稿要求六段；MV 要求 fully_copy | test_new_writer_rejects_non_native_and_missing_audio_copy；test_new_film_writer_requires_native_six_sections |
| V2 高 | MV repair_prompt 只 normalize 媒體標籤，完全未呼叫分鏡時間驗證；00:59 切鏡可被送進數秒片段 | takes.py：局部改寫後呼叫同一 native validator；新作品同樣要求六段與音軌保留 | test_local_correction_uses_same_format_and_audio_contract |
| T1 低 | 私有短片一項舊測試仍要求最低 85% 片長，與已移除門檻的正式碼、其餘測試及歷史 commit 相矛盾 | test_film_flexible_duration.py：更新為無最低片長，保留 180 秒硬上限測試 | 修正前 KeyError；修正後完整 suite 通過 |
| R1 中 | 公開短片 PUBLIC_MANIFEST 的 film.py 等 checksum 已與發佈內容不符 | PUBLIC_MANIFEST.json：依實際 bytes 重建 checksum 並納入新增測試/驗收檔案；不刪檢查、不放寬條件 | 原 test_public_film 失敗；複驗通過 |

測試檔：tests/test_vnext_regression.py。所有新增程式漏洞均先在原始碼上重現失敗，再修改；原始測試結果摘要與新增失敗案例見 docs/vnext_evidence/。
VNext worker 整合案例直接呼叫正式 worker/local_prompt/write_shoot_prompt；9B 與 ComfyUI I/O 才使用 Mock。
格式失敗時 queue 次數為 0、狀態 error、無 final.mp4；格式重試成功時完整生成三段，ComfyUI 仍為 lock_source。
版本欄位只在建立作品時寫入，避免將新規則套在已保存的舊提示詞與已完成影片上。
舊版 native 輸出保留格式/時間檢查，純文字相容輸出仍可使用舊流程；沒有把新的嚴格格式要求推入既存作品。

## 正式呼叫路徑與驗收方法

| 階段 | 短片 | MV | 離線驗證 |
|---|---|---|---|
| UI → HTTP | web/film.js 提交 mode/segment_seconds；film_server.Handler → film.start | web/index.html → server.Handler → server.start | check_film_ui.cjs / check_ui.cjs；test_film / test_server HTTP Mock GPU |
| 後端設定 | start 寫入 chain5、dynamic_min_seconds=10、segment_seconds=15、新驗證版本 | start 固定 schema5、新驗證版本、mv_motion_version=2 | 新 start regression；既有 request/graph_options tests |
| 上游故事 | plan_film → validate_plan → 保存 director_plan | worker → story_plan.ensure_plan → ensure_shoot_plan | test_film_dynamic、test_shoot_plan 的 cache/retry/隔離測試 |
| 分段委託 | shared_setup → fixed_reference_settings → current_clip_commission | per-clip director_plan + fixed_reference_settings → local_prompt | test_film_reference_settings、test_shoot_plan；不把完整未來故事當委託 |
| 9B / H3 | write_prompt → normalize_prompt → 新作六段檢查 → validate_film_format | schema5 local_prompt → write_shoot_prompt → normalize_mv_prompt → validate_native_mv_format | 新 writer/重試 tests；test_h3_prompt；test_film_dynamic 原生格式 tests |
| ComfyUI | build_workflow → chain5 add_motion_guide → preflight → queue | build_workflow → preflight → queue；audio_mode lock_source | test_core、test_comfy、test_film_motion_context、VNext worker case |
| 輸出 / 裁切 | require_audio → trim_native，後續段裁除 5 影格與相同音訊時間 | trim_video 檢查交付影格數，清除生成音軌 | 實際 ffmpeg/ffprobe 測試，非 GPU |
| 合成 | assemble_native 保留原生影音，僅裁除尺寸對齊 padding | assemble 使用原歌曲；可選外部 effects stem 保留既有產品路徑 | test_core / test_audio_timing / test_sound_effects（有該功能的倉庫） |
| 補拍 | takes.repair_prompt → film.write_prompt；chain5 依採用前段抽取上下文 | takes.repair_prompt → 相同 MV validator；無修改意見時沿用舊稿 | test_takes / test_film_motion_context；新增局部修稿非法格式案例 |
| 續跑 | server.resume → worker dispatch film.worker；沿用既存已驗證 part/保存 prompt | resume → worker；舊 prompt normalize，不新增嚴格六段門檻 | test_shoot_plan worker_resume、test_takes、test_film_motion_context missing parent |
| 失敗 | exception 寫入 error、finally 釋放 lock | 正式 worker 相同；retake 失敗保存候選錯誤、不覆蓋採用版 | 既有失敗/版本測試與新增 worker reject/retry |

h3_prompt.compile_prompt 屬於舊 compiler 流程。新 schema5 路徑由 write_shoot_prompt 交付原生六段並驗證，**不應為了讓舊 compiler 被呼叫而切換產品架構**。
prompt_quality 的 validate_subject_bindings 用於舊 schema3，不是 schema5 的角色語意驗證器；沒有把函式存在誤記成新路徑已有角色語意驗證。

## 歷史漏洞回歸清單

下表 PASS 僅表示指定的離線程式契約；畫面與 9B 真實遵從性一律 NOT TESTED。

| 短片契約 | 結果 / 證據 |
|---|---|
| 上游補事件、下游僅攝影 | PASS：writer 明示 immutable；test_film_dynamic / VNext authority。9B 是否遵守未實測 |
| 共用角色表 / 尾幀 Picture 位移 | PASS：test_film_reference_settings；chain 才加 1，chain5 不占 Picture slot |
| 角色行動與攻防對象身份 | PASS：委託、命名與圖槽傳遞測試；實際角色行動有無互換 NOT TESTED |
| 跨段不重新開始 | PASS：clip_opening continuation、當段委託隔離 / worker resume；實際動作 NOT TESTED |
| 中段不無故結尾 | PASS：intermediate boundary / 全局結局不下放；實際演出 NOT TESTED |
| chain5 全鏈 | PASS：新缺省、9 槽接線、五幀順序、prefix 裁切、相鄰補拍、續跑失效恢復 |
| 自動 10–15 秒 / H3 格點 | PASS：新 request 最低 10 秒，legal durations 為 5+17n 影格；24fps 下實際可用 10.125–14.375 秒；手動 cap / legacy 路徑不遷移 |
| 16:9 頭部裁切 | PASS：正常人物 headroom 指示、允許有意識特寫；尺寸僅裁除格點 padding。實際構圖 NOT TESTED |
| 段內自由多 Shot | PASS：官方 Shot 時間/連號檢查；未增加固定鏡數、景別配額、切鏡秒數 |
| 電影強度不異常加速 | PASS：film_motion_version=2 避免 extreme 額外 boost；legacy 設定保留。實際速度/殘影 NOT TESTED |

| MV 契約 | 結果 / 證據 |
|---|---|
| 新路徑使用 H3 驗證 | PASS：新作品版本欄位 + local_prompt 真實分派 + worker reject/retry |
| fully_copy 原曲與時間 | PASS：新 prompt retention + lock_source 接線 + 原曲合成；模型對嘴 NOT TESTED |
| 歌詞/SRT 僅參考 | PASS：test_lyrics_reference / clip-local SRT / no quote 策略；9B 是否自行新增話語 NOT TESTED |
| 指定主唱 / 歌中人非自動主唱 | PASS：vocal role 指示與相關測試；公開/私有可選標記功能差異如下 |
| Singer / Actor 分離 | PASS：角色、分場、non-singing hero 委託隔離；實際嘴部動作 NOT TESTED |
| 圖片不可交換 | PASS：固定設定傳遞、tail offset / test_core / test_shoot_plan；9B 正確理解命名 NOT TESTED |
| 下游不可提前高潮/結局 | PASS：whole-story marker 不到 clip writer；local ending contract；真實 9B NOT TESTED |
| 音樂驅動自由剪輯 | PASS：多景別、平行剪輯允許；官方本地時間碼；無硬性鏡頭數 |
| 電影爆發非 LoRA 盲加強 | PASS：mv_motion_version=2 限制 extreme 額外 boost；legacy 行為保留 |
| 補拍/續跑/末幀/舊專案 | PASS：既有 test_takes、worker_resume；新增 correction validator；未修改舊 saved prompt |

## 四庫差異核對（保留而不盲目覆寫）

- 短片正式 Python 與前端大致一致，去除檔尾換行差異後，原始差異只有 film.py、film.js、film.html。
  私有版含更完整的 flexible target/hard ceiling 交接與錯誤訊息；公開版也已使用 180 秒硬上限與無最低片長。
  這些措辭/metadata 差異保留並記錄，未藉驗收改寫導演策略。
- MV 原始正式差異在 lyrics_reference.py、shoot_plan.py、takes.py、server.py、web/index.html。
  私有版另有 music_structure、plan_translation、sound_effects 等模組；公開版未含這些可選能力。
  私有版可解析歌詞/SRT 的 @圖片N 主唱標記並在末幀接續時偏移對應引用，公開版沒有該可選解析功能與相關 UI 說明。
  不將「公開版不支援某項私有可選能力」冒稱為已通過相同能力；也沒有擅自把整套私有能力公開。
  主唱分工仍能在兩版故事委託中明示。若需要公開版支援 @圖片N 歌詞標記，應另列清楚範圍。
- 此次新作格式檢查與 MV 補拍檢查同步四庫，短片 API 缺省修正同步兩短片庫。
  短片庫保留的 MV server 路徑也寫入版本欄位，雖然 film_server 拒絕 /api/mv/start。

## 測試的界線與尚待實測

- Chromium 實測已嘗試，用現有 Playwright + /usr/bin/chromium；因 Unix socket 建立遭環境拒絕（Operation not permitted）無法啟動：BLOCKED。
  Node VM 前端契約檢查已實際執行，不能將 VM 通過等同真實瀏覽器通過。
- GPU / 真實 9B / 真實 ComfyUI 節點版本執行：NOT TESTED；沒有花費 GPU 點數。
- 待 GPU：三位具名角色動作/對白歸屬、16:9 頭部構圖、跨段不中斷/不重播、chain5 接縫及聲線、段內多鏡與運鏡、動作速度/殘影、MV 主唱對嘴與非主唱閉嘴、局部補拍及續跑接縫。
- Mock 只能證明程式資料與節點接線，不保證任何自然語言故事/身份語意，也未新增多餘的語意審查模型或攝影配額。
- banana-mv-public 的 notebook 重建只有一個空白行差異：無行為差異，已還原，避免無關改動。
- PR 是可審查修補，整體品質驗收仍受上述 NOT TESTED/BLOCKED 項目限制，不宣稱成片已改善。

## 本倉庫實際結果

完整執行結果見 [results.json](vnext_evidence/results.json)。

重現命令（不使用 GPU）：在稽核起點建立另一個 worktree，僅取本 PR 的
`tests/test_vnext_regression.py`，執行 `python -m unittest discover -s tests -p test_vnext_regression.py`。
修正前記錄位於 reproduction.txt；在 PR 分支執行完整 suite，與 baseline.txt / final-suite.txt 對照。
新增測試不引入攝影限制；只是驗證既定新作格式、音軌保留、缺省與錯誤阻斷。

本庫最終：Python **283 項 PASS**；前端契約、compileall、diff whitespace 檢查 PASS。
