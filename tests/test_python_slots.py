"""Python Slot experiment contract; fast CPU-only regressions (no GPU/9B)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from banana_mv import server
from banana_mv.python_slots import ensure_python_slot_plan, span_counts, split_source


def source():
    return (
        '角色綁定\n'
        '@圖片1：宗主，唯一男性主唱，黑皮衣。\n'
        '@圖片2：白衣工程師，唯一女性主唱。\n'
        '世界觀：量子科技煉丹基地。\n'
        '第一幕｜出發\n'
        'OPEN_01 啟動控制台。\n'
        'OPEN_02 女主角轉向伺服器。\n'
        'OPEN_03 巨型丹爐亮起金光。\n'
        'OPEN_04 主角發現異常訊號。\n'
        '第二幕｜災難\n'
        'CRISIS_01 拳擊模擬人偶甦醒。\n'
        'CRISIS_02 人偶打出上勾拳。\n'
        'CRISIS_03 男主角躲避上勾拳。\n'
        'CRISIS_04 工程師啟動緊急修復。\n'
        'CRISIS_05 程式反而變成機械迷宮。\n'
        '第三幕｜復原\n'
        'RESTORE_01 兩人拆除錯誤模組。\n'
        'RESTORE_02 系統重新啟動。\n'
        'RESTORE_03 監控螢幕恢復正常。\n'
        '終幕｜結果\n'
        'ENDING_01 工程師指出根本原因。\n'
        'ENDING_02 男主角無奈承認錯誤。\n'
        'ENDING_03 最後關鍵結果發生。\n'
        '全曲執行原則\n'
        '保留兩名角色的參考外觀，不自行增加主角。\n'
    )


def clips(tail=2.8):
    rows = [{'index':i, 'start':i*10, 'seconds':10.0,
             'song_seconds':270+tail,'segment_count':28} for i in range(27)]
    rows.append({'index':27,'start':270,'seconds':tail,
                 'song_seconds':270+tail,'segment_count':28})
    return rows


def request():
    return {'prompt':source(),'director':'auto','story_plan':True,
            'project_scope':'full','ending_policy_version':2,
            'director_schema':6,'rewrite_retries':0,
            'intensity':'high','dynamic_cuts':True,'mode':'chain'}


class PythonSlotsTests(unittest.TestCase):
    def test_long_song_28_clip_plan_is_deterministic_and_has_no_planning_llm(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            plan=ensure_python_slot_plan(request(),clips(),[root/'one.png',root/'two.png'],root)
            self.assertEqual(plan['version'],6)
            self.assertEqual(len(plan['segments']),28)
            self.assertEqual([s['index'] for s in plan['segments']],list(range(28)))
            self.assertTrue(all(s['handoff_version']==1 for s in plan['segments']))
            text='\n'.join(s['event'] for s in plan['segments'][:20])
            self.assertNotIn('ENDING_03',text)
            self.assertNotIn('GLOBAL STORY OUTCOME',plan['shared_setup'])
            self.assertIn('<Picture 1>',plan['shared_setup'])
            self.assertIn('<Picture 2>',plan['shared_setup'])
            self.assertIn('previous full interval',plan['segments'][-1]['event'])
            self.assertEqual(ensure_python_slot_plan(request(),clips(),[root/'one.png',root/'two.png'],root)['version'],6)
            self.assertTrue((root/'director_plan.json').is_file())

    def test_python_slot_plan_rejects_timing_mutation_without_clobber(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            ensure_python_slot_plan(request(),clips(),[root/'one.png',root/'two.png'],root)
            original=(root/'director_plan.json').read_bytes()
            changed=clips();changed[-1]['seconds']=2.4
            with self.assertRaisesRegex(ValueError,'不一致'):
                ensure_python_slot_plan(request(),changed,[root/'one.png',root/'two.png'],root)
            self.assertEqual((root/'director_plan.json').read_bytes(),original)

    def test_excerpts_do_not_invent_finale_hold(self):
        with tempfile.TemporaryDirectory() as d:
            req=dict(request(),project_scope='excerpt')
            plan=ensure_python_slot_plan(req,clips(),[Path(d)/'one.png',Path(d)/'two.png'],d)
            self.assertEqual(len(plan['segments']),28)
            self.assertNotIn('SOURCE SONG SHORT TAIL',plan['segments'][-1]['event'])
            self.assertFalse(plan['ending_contract']['finish_work'])

    def test_stage_counts_keep_chapters_in_order(self):
        fixed, chapters=split_source(source())
        self.assertIn('角色綁定',fixed)
        self.assertEqual(len(chapters),4)
        counts=span_counts(chapters,27)
        self.assertEqual(sum(counts),27)
        self.assertTrue(all(n>=1 for n in counts))

    def test_each_h3_writer_receives_only_local_slot_and_fixed_references(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            originals=[]
            for i in range(2):
                path=root/('ref'+str(i)+'.png')
                Image.new('RGB',(16,16),'white').save(path)
                originals.append(path)
            guide=root/'guide.md'
            guide.write_text('OFFICIAL_H3_GUIDE_INTACT',encoding='utf-8')
            cfg={'guides':{'ref':str(guide)}}
            req=request()
            plan=ensure_python_slot_plan(req,clips(),originals,root)
            for index in (0,12,26):
                seg=dict(clips()[index],
                    director_plan=plan['segments'][index],
                    fixed_reference_settings=plan['shared_setup'],
                    direction_ending_contract=plan['ending_contract'])
                model=Mock(return_value='<Picture 1> acts in ONLY_THIS_LOCAL_CLIP. <Audio 1>: fully_copy.')
                with patch.object(server.backend,'rewrite_local',model):
                    result=server.local_prompt(cfg,req,seg,originals,None)
                self.assertIn('ONLY_THIS_LOCAL_CLIP',result)
                self.assertEqual(model.call_count,1)
                system=model.call_args.args[1]
                received=model.call_args.args[2][0][1]
                self.assertIn('OFFICIAL_H3_GUIDE_INTACT',system)
                self.assertIn('Current clip script:',received)
                if index>0:
                    self.assertNotIn('OPEN_01',received)
                if index<26:
                    self.assertNotIn('ENDING_03',received)
                if index==0:
                    self.assertNotIn('CRISIS_02',received)
            self.assertEqual(plan['segments'][-1]['index'],27)


    def test_chinese_next_line_times_and_srt_keep_future_duet_in_its_own_clip(self):
        from banana_mv.timed_slots import parse_timed_source
        text=(
            '【共同設定】\n同一間公寓，S1 男聲，S2 女聲。\n'
            '【劇情內容】\n'
            '第1段｜裝置開始運作\n時間：00:00–00:38\n'
            '場景：公寓。電腦啟動。S1 開始整理電源線。\n'
            '第2段｜差一點才成功\n時間：00:38–01:16.680\n'
            '場景：公寓客廳。\n'
            'S1 唱「只是差一點 真的差一點」。\n'
            'S2 看向螢幕，唱「你說的差一點 是昨天還是前年」。\n'
            'S2 想起旅行，唱「我都快忘記海水到底有多甜」。\n'
            '第一次唱到「我蓋了一座小小的丹爐」時，電腦終於跳出測試畫面。\n'
            'S1 指向畫面，唱「想把腦海的夢全部留住」「從一張照片到一場演出」。\n'
            'S2 看向吉他與泳圈。\n'
            'S2 唱「一邊是夢 一邊是幸福」。\n'
            '兩人合唱「原來我們都住在這座小丹爐」。\n'
            '第3段｜更新驅動\n時間：01:16.680–01:30\n'
            '場景：公寓工作區。\nS1 回到主機旁，開啟 CUDA。\n'
        )
        parsed=parse_timed_source(text)
        self.assertIsNotNone(parsed)
        self.assertEqual([(round(c['start'],3),round(c['end'],3)) for c in parsed[1]],
                         [(0,38),(38,76.68),(76.68,90)])
        cues=[(37.92,40.22,'S1','只是差一點 真的差一點'),
              (42.26,46.02,'S2','你說的差一點 是昨天還是前年'),
              (46.02,49.82,'S2','我都快忘記海水到底有多甜'),
              (49.82,52.93,'S1','我蓋了一座小小的丹爐'),
              (52.93,55.06,'S1','想把腦海的夢全部留住'),
              (55.06,57.34,'S1','從一張照片到一場演出'),
              (67.88,72.44,'S2','一邊是夢 一邊是幸福'),
              (72.44,76.68,'S1+S2','原來我們都住在這座小丹爐')]
        req=dict(request(),prompt=text,srt_cues=[
            {'start':start,'end':end,'text':f'[{role}] {lyrics}'}
            for start,end,role,lyrics in cues])
        segs=[{'index':i,'start':i*10.,'seconds':10.,
               'song_seconds':90.,'segment_count':9} for i in range(9)]
        with tempfile.TemporaryDirectory() as d:
            plan=ensure_python_slot_plan(req,segs,[Path(d)/'male.png',Path(d)/'female.png'],d)
        self.assertEqual(plan['source_timing'],'explicit_markdown')
        events=[x['event'] for x in plan['segments']]
        self.assertNotIn('一邊是夢','\n'.join(events[:6]))
        self.assertNotIn('原來我們都住','\n'.join(events[:7]))
        self.assertIn('一邊是夢',events[6])
        self.assertIn('原來我們都住',events[7])
        self.assertNotIn('CUDA',events[5])
        self.assertIn('跳出測試畫面',events[4])  # 49.820s lies inside 40–50s.
        self.assertIn('@9.820s',events[4])
        self.assertNotIn('跳出測試畫面',events[3])

    def test_saved_legacy_plan_rebuilds_only_commissions_and_archives_old_status(self):
        from banana_mv.python_slots import refresh_stale_timed_plan
        text=('【劇情內容】\n第1段｜工作\n時間：00:00–00:20\n'
              'S1 查看主機。S1 拿起紙張。\n'
              '第2段｜結果\n時間：00:20–00:40\n'
              'S2 對嘴唱「一邊是夢 一邊是幸福」。兩人看著螢幕。\n')
        cue={'start':31,'end':35,'text':'[S2] 一邊是夢 一邊是幸福'}
        req=dict(request(),prompt=text,srt_cues=[cue])
        segs=[{'index':i,'start':i*10.,'seconds':10.,
               'song_seconds':40.,'segment_count':4,'status':'done' if i<2 else 'waiting',
               'prompt':'OLD FILMED' if i<2 else 'OLD UNFILMED'} for i in range(4)]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'abcdef123456';work.mkdir()
            from banana_mv import python_slots
            with patch.object(python_slots,'parse_timed_source',return_value=None):
                old=ensure_python_slot_plan(req,segs,[root/'male.png'],work)
            self.assertEqual(old['source_timing'],'legacy_ordered')
            job={'id':'abcdef123456','request':req,'segments':segs,'status':'cancelled'}
            with patch.object(server,'RUNS',root):
                server.write_state(job)
                self.assertTrue(refresh_stale_timed_plan(job,[root/'male.png'],work))
            self.assertTrue((work/job['timing_repair']['backup']).is_file())
            self.assertTrue((work/job['timing_repair']['status_backup']).is_file())
            self.assertEqual(job['segments'][0]['prompt'],'OLD FILMED')
            self.assertEqual(job['segments'][1]['status'],'done')
            self.assertNotIn('refresh_prompt',job['segments'][1])
            self.assertTrue(job['segments'][2]['refresh_prompt'])
            self.assertTrue(job['segments'][3]['refresh_prompt'])
            self.assertIn('explicit_markdown',(work/'director_plan.json').read_text())
            self.assertFalse(refresh_stale_timed_plan(job,[root/'male.png'],work))

    def test_timed_markdown_five_chapters_fill_nine_5s_slots(self):
        from banana_mv.timed_slots import parse_timed_source
        prompt = (
            '# 作品｜午夜劇場\n'
            '## 1｜角色設定\n'
            '@小語：成年女歌手，固定高馬尾。\n'
            '## 2｜MV 主題\n'
            '復古夜總會與紅色布幕。\n'
            '歌手持續表演，最後以謝幕姿態結尾。\n'
            '## 3｜故事內容\n'
            '### 第一段｜00:00–00:10｜開場\n'
            'OPEN_1 歌手登上舞台。\n'
            'OPEN_2 歌手開始演唱。\n'
            'OPEN_3 觀眾開始鼓掌。\n'
            '### 第二段｜00:10–00:20｜升溫\n'
            'WARM_1 伴舞開始加入。\n'
            'WARM_2 樂隊開始合奏。\n'
            '### 第三段｜00:20–00:30｜轉折\n'
            'TURN_1 舞台忽然停電。\n'
            'TURN_2 主角摸索開關。\n'
            '### 第四段｜00:30–00:40｜高潮\n'
            'PEAK_1 聚光燈重新亮起。\n'
            'PEAK_2 全場歡呼。\n'
            '### 第五段｜00:40–00:44.5｜謝幕\n'
            'END_1 主角唱出最後一句。\n'
            'END_2 紅色布幕落下。\n'
            '## 4｜演唱與攝影\n'
            '她是唯一主唱，鏡頭跟隨演出。\n'
            '## 5｜劇情連續性\n'
            '第一段只完成開場表演。\n'
            '第四、第五段維持紅色主燈光。\n'
            '每段延續舞台狀態。\n'
            '## 6｜導演自由發揮\n'
            '最後 4.5 秒專注謝幕。\n'
        )
        parsed=parse_timed_source(prompt)
        self.assertIsNotNone(parsed)
        fixed,chapters=parsed
        self.assertEqual(len(chapters),5)
        self.assertIn('成年女歌手',fixed)
        self.assertIn('唯一主唱',fixed)
        self.assertNotIn('第一段只完成',fixed)
        self.assertNotIn('第四、第五段',fixed)
        self.assertNotIn('最後 4.5 秒',fixed)
        self.assertNotIn('最後以謝幕',fixed)
        self.assertTrue(any('最後以謝幕' in x for x in chapters[4]['constraints']))
        self.assertFalse(any('最後以謝幕' in x for x in chapters[0]['constraints']))
        self.assertTrue(any('第一段只完成' in s for s in chapters[0]['constraints']))
        self.assertTrue(any('第四、第五段' in s for s in chapters[3]['constraints']))
        self.assertTrue(any('最後 4.5 秒' in s for s in chapters[4]['constraints']))
        segs=[{'index':i,'start':5*i,'seconds':min(5.0,44.5-5*i),
               'song_seconds':44.5,'segment_count':9} for i in range(9)]
        with tempfile.TemporaryDirectory() as d:
            req=dict(request(),prompt=prompt)
            plan=ensure_python_slot_plan(req,segs,[Path(d)/'one.png'],d)
        self.assertEqual(plan['source_timing'],'explicit_markdown')
        self.assertEqual(len(plan['segments']),9)
        self.assertEqual([plan['segments'][i]['event'].split('Source chapter: ')[1].splitlines()[0].split('｜')[0]
                          for i in range(9)],
                         ['第一段','第一段','第二段','第二段','第三段','第三段','第四段','第四段','第五段'])
        slots=[entry['event'] for entry in plan['segments']]
        self.assertIn('OPEN_1',slots[0])
        self.assertNotIn('OPEN_3',slots[0])
        self.assertIn('OPEN_3',slots[1])
        self.assertIn('WARM_1',slots[2])
        self.assertNotIn('WARM_1',slots[1])
        self.assertIn('END_1',slots[8])
        self.assertNotIn('END_1','\n'.join(slots[:8]))
        self.assertNotIn('## 1｜角色設定','\n'.join(slots))
        self.assertNotIn('## 5｜劇情連續性','\n'.join(slots))
        self.assertNotIn('ALREADY ESTABLISHED; do not restage or repeat: ##','\n'.join(slots))

    def test_explicit_timed_boundary_crossing_and_short_final_slot(self):
        prompt=(
            '### 第一段｜00:00–00:07｜開場\n'
            'FIRST_1 開場。\n'
            'FIRST_2 移動。\n'
            '### 第二段｜00:07–00:15｜轉折\n'
            'SECOND_1 進入新場景。\n'
            'SECOND_2 發現線索。\n'
            '### 第三段｜00:15–00:17｜短尾結局\n'
            'END_ONLY_17 完成最後事件。\n'
        )
        segs=[{'index':i,'start':i*5,'seconds':min(5.0,17-i*5),
               'song_seconds':17.0,'segment_count':4} for i in range(4)]
        with tempfile.TemporaryDirectory() as d:
            plan=ensure_python_slot_plan(dict(request(),prompt=prompt),
                                         segs,[Path(d)/'ref.png'],d)
        s=[p['event'] for p in plan['segments']]
        self.assertIn('FIRST_1',s[0])
        self.assertIn('FIRST_2',s[1])
        self.assertIn('SECOND_1',s[1])
        self.assertIn('2.000–5.000s',s[1])
        self.assertNotIn('END_ONLY_17','\n'.join(s[:3]))
        self.assertIn('END_ONLY_17',s[3])
        self.assertNotIn('SOURCE SONG SHORT TAIL',s[3])

    def test_plain_one_click_story_keeps_cast_and_direction_out_of_timeline(self):
        prompt = (
            'H3 ONE-CLICK MV｜蕉猿戲水樂園\n\n'
            '故事：終於帶我來玩水了\n'
            '角色：@圖片1 = 小語，唯一女主角。\n\n'
            '完整故事劇情\n\n'
            '早晨，小語跑向入口。猴子拿反地圖替她指路。\n\n'
            '午後，小語滑下水道，落進水池。\n\n'
            '傍晚，猴子售票員揮手，小語轉向鏡頭微笑。\n\n'
            '導演執行要求\n'
            '- 對嘴演唱自然融入適合的場景。\n'
            '- 不要自行改寫故事結局。\n\n'
            '視覺基調\n'
            '16:9 電影式真人實景攝影。'
        )
        segs = [{'index': i, 'start': 10 * i, 'seconds': 10} for i in range(2)]
        with tempfile.TemporaryDirectory() as d:
            plan = ensure_python_slot_plan(dict(request(), prompt=prompt),
                                           segs, [Path(d)/'ref.png'], d)
        setup = plan['shared_setup']
        events = [row['event'] for row in plan['segments']]
        self.assertIn('角色：<Picture 1> = 小語', setup)
        self.assertIn('對嘴演唱自然融入', setup)
        self.assertIn('16:9 電影式真人實景攝影', setup)
        self.assertIn('早晨，小語跑向入口', events[0])
        self.assertIn('小語轉向鏡頭微笑', events[-1])
        self.assertNotIn('小語轉向鏡頭微笑', events[0])
        for rule in ('H3 ONE-CLICK MV', '對嘴演唱自然融入', '16:9 電影式'):
            self.assertNotIn(rule, '\n'.join(events))

    def test_sectioned_brief_with_and_without_markdown_keeps_setup_out_of_actions(self):
        markdown = (
            '# 午夜歌舞 MV\n'
            '## 1｜角色設定\n'
            '開場穿著：黑色馬甲與高跟鞋。\n'
            '服裝逐步變化，最後才赤腳演出。\n'
            '## 2｜MV 主題\n'
            '紅幕歌舞舞台。\n'
            '## 3｜故事內容\n'
            '### 第一段｜紅幕開場\n'
            'OPEN_1 主角登上舞台演唱。\n'
            'OPEN_2 主角轉身面向麥克風。\n'
            '### 第二段｜變化\n'
            'CHANGE_1 主角摘下帽子。\n'
            'CHANGE_2 主角繼續演唱。\n'
            '### 第三段｜謝幕\n'
            'END_1 主角走到紅幕中央。\n'
            'END_2 紅幕落下。\n'
            '## 4｜演唱與劇情安排\n'
            '歌手全程維持身份一致。\n'
            '## 5｜特殊要求\n'
            '完成的事件不得重演。\n'
            '## 6｜導演自由發揮\n'
            '全片按故事順序推進。\n'
        )
        plain = markdown.replace('### ', '').replace('## ', '').replace('# ', '')
        plans = []
        for brief in (markdown, plain):
            fixed, chapters = split_source(brief)
            self.assertEqual(len(chapters), 3)
            self.assertEqual([c['title'] for c in chapters],
                             ['第一段｜紅幕開場', '第二段｜變化', '第三段｜謝幕'])
            self.assertIn('開場穿著', fixed)
            self.assertIn('紅幕歌舞舞台', fixed)
            self.assertIn('特殊要求', fixed)
            self.assertIn('完成的事件不得重演', fixed)
            self.assertNotIn('##', fixed)
            all_actions = '\n'.join(a for c in chapters for a in c['actions'])
            self.assertNotIn('服裝逐步變化，最後才赤腳演出', all_actions)
            self.assertNotIn('開場穿著', all_actions)
            self.assertNotIn('特殊要求', all_actions)
            self.assertIn('CHANGE_1', all_actions)
            segs = [{'index': i, 'start': 5.0*i, 'seconds': 5.0,
                     'song_seconds': 60.0, 'segment_count': 12} for i in range(12)]
            with tempfile.TemporaryDirectory() as d:
                plan = ensure_python_slot_plan(dict(request(), prompt=brief), segs,
                                               [Path(d)/'ref.png'], d)
            self.assertEqual(plan['source_timing'], 'legacy_ordered')
            self.assertNotEqual(plan['shared_setup'], '')
            events = [x['event'] for x in plan['segments']]
            self.assertNotIn('服裝逐步變化，最後才赤腳演出', '\n'.join(events))
            self.assertNotIn('END_1', '\n'.join(events[:8]))
            self.assertIn('END_2', '\n'.join(events[-4:]))
            self.assertNotIn('##', '\n'.join(events))
            plans.append((fixed, chapters))
        self.assertEqual(plans[0], plans[1])


    def test_completed_wardrobe_events_propagate_across_5s_slots(self):
        # Regression: the 4th/5th/6th/7th local shots must not re-dress
        # previously removed garments merely because global setup includes them.
        brief = (
            '## 1｜角色設定\n'
            '@圖片1：演員，唯一演出者。\n'
            '開場穿著：\n'
            '藍色外套\n'
            '灰色長褲\n'
            '黑色長靴\n'
            '## 2｜MV 主題\n'
            '排練室的表演。\n'
            '## 3｜故事內容\n'
            '### 第一段｜紅幕開場\n'
            '演員穿著完整藍色外套與長褲及黑色長靴登場。\n'
            '她正面對嘴演唱並旋轉。\n'
            '攝影機拉至中全景。\n'
            '本段保留完整開場服裝。\n'
            '### 第二段｜第一件落幕\n'
            '演員繼續演唱。\n'
            '她解開藍色外套，完成本段服裝變化。\n'
            '接著以上身裸露、保留長褲及黑色長靴的狀態跳舞。\n'
            '攝影機穿插特寫與全身鏡頭。\n'
            '本段只完成藍色外套卸除。\n'
            '### 第三段｜第二件落幕\n'
            '歌聲持續並切換旋轉舞步。\n'
            '演員向鏡頭露出笑容。\n'
            '她完成灰色長褲的卸除。\n'
            '接著以全裸、僅穿黑色長靴的狀態跳舞。\n'
            '本段只完成灰色長褲卸除。\n'
            '### 第四段｜最後一件\n'
            '演員延續歌舞。\n'
            '她依序卸除左右黑色長靴。\n'
            '完成後她赤腳繼續舞蹈。\n'
            '攝影機追蹤她的旋轉。\n'
            '本段完成最後的服裝變化。\n'
            '## 4｜特殊要求\n'
            '所有已卸除衣物都不得重新穿回。\n'
        )
        segs = [{'index':i, 'start':i*5.0, 'seconds':5.0,
                 'song_seconds':40.0, 'segment_count':8} for i in range(8)]
        with tempfile.TemporaryDirectory() as d:
            plan = ensure_python_slot_plan(dict(request(), prompt=brief), segs,
                                           [Path(d)/'ref.png'], d)
        events = [row['event'] for row in plan['segments']]
        self.assertEqual(len(events), 8)
        self.assertEqual([events[i].split('Source chapter: ')[1].splitlines()[0].split('｜')[0]
                          for i in range(8)],
                         ['第一段','第一段','第二段','第二段',
                          '第三段','第三段','第四段','第四段'])
        self.assertIn('Torso: Bare;', events[3])  # Already removed before fourth clip.
        self.assertIn('Torso: Bare;', events[4])  # No reinstatement at next chapter.
        self.assertIn('Bottom: 灰色長褲 worn.', events[4])
        self.assertIn('Bottom: Bare;', events[6])
        self.assertIn('Feet: 黑色長靴 worn.', events[6])
        self.assertIn('Feet: Barefoot;', events[7])
        self.assertNotIn('Current interval actions in original order:\n- 本段只完成',
                         '\n'.join(events))
        self.assertNotIn('ALREADY ESTABLISHED; do not restage or repeat: 本段只完成',
                         '\n'.join(events))
        self.assertNotIn('黑色長靴的卸除', '\n'.join(events[:6]))
        # Input scene and film mode must remain meaningful despite state header.
        self.assertEqual(plan['segments'][7]['mode'], 'story')


    def test_python_retains_global_story_route_for_local_slot_allocation(self):
        text = ('【共同設定】\nS1 = @圖片1，男主唱。\nS2 = @圖片2，女主唱。\n'
                '整首 MV 從公寓出發，到海邊，再回到公寓。\n'
                '【劇情】\n第一段｜公寓\n男主角看手機。\n'
                '第二段｜海邊\n女主角在海邊玩水。\n')
        fixed, chapters = split_source(text)
        self.assertIn('海邊', fixed)
        self.assertEqual(len(chapters), 2)
        slots = [{'index': i, 'start': i * 5.0, 'seconds': 5.0,
                  'song_seconds': 10.0, 'segment_count': 2} for i in range(2)]
        with tempfile.TemporaryDirectory() as d:
            plan = ensure_python_slot_plan(dict(request(), prompt=text), slots,
                [Path(d)/'a.png', Path(d)/'b.png'], d)
        self.assertIn('海邊', plan['shared_setup'])
        self.assertNotIn('海邊', plan['segments'][0]['event'])
        self.assertIn('海邊', plan['segments'][1]['event'])

    def test_unrelated_story_has_no_invented_wardrobe_state(self):
        brief = (
            '第一幕｜控制室\n'
            '宗主操作控制台，丹爐亮起。\n'
            '第二幕｜修復\n'
            '工程師找出錯誤並恢復系統。\n'
        )
        segs = [{'index':i,'start':i*5.0,'seconds':5.0,
                 'song_seconds':10.0,'segment_count':2} for i in range(2)]
        with tempfile.TemporaryDirectory() as d:
            plan = ensure_python_slot_plan(dict(request(),prompt=brief),segs,
                                           [Path(d)/'ref.png'],d)
        self.assertNotIn('CURRENT_ACTOR_STATE',
                         '\n'.join(row['event'] for row in plan['segments']))
        self.assertIn('工程師找出錯誤',plan['segments'][1]['event'])

    def test_python_appearance_anchor_is_first_local_bullet_and_carries_forward(self):
        from banana_mv.python_slots import _inject_actor_state, _local_filmed_actions
        fixed = '開場穿著：\n藍色外套\n灰色長褲\n黑色長靴\n'
        events = [
            'Current interval actions in original order:\n'
            '- 演員脫下藍色外套。\n'
            'Stage these actions with physical cause.\n',
            'Current interval actions in original order:\n'
            '- 演員開始唱歌並繞過舞台。\n'
            'Stage these actions with physical cause.\n',
            'Current interval actions in original order:\n'
            '- 演員向鏡頭揮手。\n'
            'Stage these actions with physical cause.\n',
        ]
        result = _inject_actor_state(events, fixed, [])
        anchor = 'Current interval actions in original order:\n- 【Python當前狀態'
        self.assertTrue(all(anchor in x for x in result))
        self.assertIn('上身已無藍色外套', result[1])
        self.assertIn('上身已無藍色外套', result[2])
        self.assertIn('下身穿著灰色長褲', result[2])
        self.assertIn('雙腳穿著黑色長靴', result[2])
        self.assertIn('Torso: Bare;', result[2])
        self.assertEqual(list(_local_filmed_actions(result[1])),
                         ['演員開始唱歌並繞過舞台。'])
        self.assertNotIn('演員脫下藍色外套。', result[1])

    def test_fixed_reference_priority_is_per_property_and_absent_state_falls_back(self):
        from banana_mv.shoot_plan import _fixed_reference_with_python_priority
        fixed = ('人物五官與開場服裝依照參考圖片。\n'
                 '開場穿著：\n'
                 '藍色外套\n'
                 '灰色長褲\n'
                 '黑色長靴\n'
                 '舞台設計：\n'
                 '銀色麥克風與白色聚光燈。')
        event = ('CURRENT_ACTOR_STATE (at clip start; authoritative):\n'
                 '- Torso: Bare; 藍色外套 already removed, stays off.\n'
                 'EXPECTED_ACTOR_STATE_AFTER_THIS_CLIP (planned consequence):\n'
                 '- Torso: Bare; 藍色外套 already removed, stays off.\n')
        cleaned = _fixed_reference_with_python_priority(fixed, event)
        self.assertNotIn('\n藍色外套\n', cleaned)
        self.assertIn('\n灰色長褲\n', cleaned)
        self.assertIn('\n黑色長靴\n', cleaned)
        self.assertIn('人物五官依照參考圖片', cleaned)
        self.assertIn('銀色麥克風與白色聚光燈', cleaned)
        self.assertEqual(_fixed_reference_with_python_priority(fixed, '沒有狀態紀錄'),
                         fixed)

    def test_plain_numbered_direction_notes_stay_out_of_final_film_slots(self):
        # Regression: 6｜導演執行重點 after a plain-text fifth act is setup,
        # not a sixth filmable phase or a fake last clip event.
        from banana_mv.python_slots import commission
        for heading in ('6｜導演執行重點', '6｜執行重點', '導演執行重點'):
            with self.subTest(heading=heading):
                brief = (
                    '1｜角色設定\n'
                    '@圖片1：小語。\n'
                    '5｜完整 MV 分鏡與武打設計\n'
                    '第一幕｜十人入侵\n'
                    '惡人走進神社。\n'
                    '第二幕｜交手\n'
                    '蕉大師攤手化解攻擊。\n'
                    '第三幕｜反擊\n'
                    '敵人陸續倒地。\n'
                    '第四幕｜首領登場\n'
                    '蕉大師擊退首領。\n'
                    '第五幕｜十惡人連滾帶爬逃離神社\n'
                    '十人終於翻身起來。\n'
                    '十人互相攙扶逃出鳥居。\n'
                    + heading + '\n'
                    '戰鬥進度\n'
                    '依照 1 → 3 → 5 → 6 → 8 → 9 → 10 人順序累積。\n'
                    '攝影設計\n'
                    '以側面中景展示攻防。\n'
                )
                fixed, chapters = split_source(brief)
                self.assertEqual(len(chapters), 5)
                self.assertIn('戰鬥進度', fixed)
                self.assertIn('攝影設計', fixed)
                self.assertTrue(any('逃出鳥居' in x for x in chapters[-1]['actions']))
                filmable = '\n'.join(a for c in chapters for a in c['actions'])
                self.assertNotIn('戰鬥進度', filmable)
                self.assertNotIn('攝影設計', filmable)
                self.assertNotIn('依照 1 →', filmable)
                final, _ = commission(chapters[-1], 1, 2, '')
                self.assertIn('逃出鳥居', final)
                self.assertNotIn('戰鬥進度', final)
                segs = [{'index':i,'start':i*5.0,'seconds':5.0,
                         'song_seconds':95.0,'segment_count':19}
                        for i in range(19)]
                with tempfile.TemporaryDirectory() as d:
                    req=dict(request(), prompt=brief)
                    plan=ensure_python_slot_plan(req, segs, [Path(d)/'ref.png'], d)
                all_events='\n'.join(x['event'] for x in plan['segments'])
                self.assertNotIn('戰鬥進度', all_events)
                self.assertNotIn('攝影設計', all_events)
                self.assertIn('逃出鳥居', all_events)
                self.assertIn('戰鬥進度', plan['shared_setup'])

    def test_markdown_direction_notes_leave_story_without_new_actions(self):
        brief=(
            '## 3｜故事內容\n'
            '### 第一段｜開場\n'
            '小語開始演唱。\n'
            '### 第二段｜謝幕\n'
            '小語鞠躬謝幕。\n'
            '## 6｜導演執行重點\n'
            '攝影設計\n'
            '高角度拍攝整體舞台。\n'
        )
        fixed, chapters=split_source(brief)
        self.assertEqual(len(chapters),2)
        self.assertIn('攝影設計',fixed)
        self.assertNotIn('攝影設計','\n'.join(str(c['actions']) for c in chapters))

    def test_quote_only_line_does_not_become_previous_event(self):
        from banana_mv.python_slots import commission
        brief=(
            '第一幕｜副歌\n'
            '小語爆發性嘶吼：\n'
            '「我要打十個！\n'
            '」\n'
            '紅白燈光與鼓點同時爆發。\n'
            '第二幕｜神社\n'
            '蕉大師擋下來拳。\n'
        )
        _,chapters=split_source(brief)
        self.assertEqual(chapters[0]['actions'],
                         ['小語爆發性嘶吼：','「我要打十個！」','紅白燈光與鼓點同時爆發。'])
        previous=''
        events=[]
        for i in range(3):
            event,previous=commission(chapters[0],i,3,previous)
            events.append(event)
        self.assertIn('ALREADY ESTABLISHED; do not restage or repeat: 「我要打十個！」',
                      events[2])
        self.assertNotIn('ALREADY ESTABLISHED; do not restage or repeat: 」',
                         '\n'.join(events))
        self.assertEqual(previous,'紅白燈光與鼓點同時爆發。')
        _,inline=split_source('第一幕｜副歌\n「我要打十個！」\n')
        self.assertEqual(inline[0]['actions'],['「我要打十個！」'])


    def test_plain_act_clock_uses_srt_not_legacy_action_order(self):
        # Regression: the real Bai Suzhen brief uses ACT timecodes without
        # Markdown and <Picture 1>＝蕉大師，S1 (not S1 = <Picture 1>).
        from banana_mv.commission_guard import role_pictures
        from banana_mv.shoot_plan import _filming_reference_settings
        brief = (
            'BANANAMV｜白蛇千年復仇戰\n'
            '一、角色與圖片身份\n'
            '@圖片1＝蕉大師，S1，男性角色\n'
            '@圖片2＝白素貞，S2，女性角色\n'
            '二、世界觀、場景與整體故事\n'
            '古寺與雷峰塔。\n'
            '四、完整時間軸與電影分鏡\n'
            'ACT 01｜00:00–00:51.300\n'
            '00:00–00:10.000｜S2 出場\n'
            '白素貞接近雷峰塔。\n'
            '00:41.888–00:51.300｜S1 高速 Machine-Gun Rap\n'
            '「慢著慢著先別鬧！法海跟我不同號！別拿雷電亂開炮！」\n'
            '蕉大師敲木魚，金色音波推開洪水。\n'
            'ACT 02｜00:51.300–01:09.988\n'
            '00:51.300–01:00.688｜S2 高速 Rap\n'
            '「一紙封印一座塔！一場風雨一場殺！千年舊恨誰來答！」\n'
            '白素貞站在水霧中央，揮動雙手。\n'
            '01:00.688–01:09.988｜S2 高速 Rap 持續\n'
            '「斷橋斷夢斷前緣！千年千劫千重念！」\n'
            '白素貞將水霧凝成巨大的雷峰塔幻影。\n'
            '五、全片連續性與演出規則\n'
            '1. 不可提早進入最終演唱會舞台。\n'
            '六、最終導演意圖\n'
            '雙人最後化敵為友，不能提前拍攝結局。\n'
        )
        cues = [
            {'start':41.888,'end':51.3,'text':'[S1] 別拿雷電亂開炮！'},
            {'start':51.3,'end':60.688,'text':'[S2] 一紙封印一座塔！'},
            {'start':60.688,'end':69.988,'text':'[S2] 斷橋斷夢斷前緣！'},
        ]
        settings = request()
        settings.update(prompt=brief, srt_cues=cues, direct_script=False)
        slots = [{'index':i,'start':i*10.0,'seconds':10.0,
                  'song_seconds':70.0,'segment_count':7} for i in range(7)]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            plan = ensure_python_slot_plan(settings, slots,
                                           [root/'monk.png',root/'snake.png'],root)
        self.assertEqual(plan['source_timing'],'explicit_markdown')
        filtered_setup = _filming_reference_settings(plan['shared_setup'])
        self.assertEqual(role_pictures(filtered_setup),
                         {'S1':'<Picture 1>','S2':'<Picture 2>'})
        self.assertNotIn('雙人最後化敵為友',filtered_setup)
        before = plan['segments'][4]['event']
        crossing = plan['segments'][5]['event']
        after = plan['segments'][6]['event']
        self.assertIn('S1 高速 Machine-Gun Rap',before)
        self.assertIn('ACT 02',crossing)
        self.assertIn('S2 高速 Rap',crossing)
        self.assertIn('S2 高速 Rap 持續',after)
        # No unscoped future lyric, extra dialogue or post-story finale in any
        # 10-second filming commission. The song already holds the SRT words.
        for event in (before,crossing,after):
            self.assertNotIn('一紙封印一座塔',event)
            self.assertNotIn('慢著慢著先別鬧',event)
            self.assertNotIn('雙人最後化敵為友',event)
            self.assertNotIn('全片連續性與演出規則',event)
        self.assertNotIn('S1 高速 Machine-Gun Rap',after)

    def test_master_director_prompt_next_line_act_and_global_scene_isolation(self):
        """The supplied Bai Suzhen long-form structure, not a simplified format."""
        from banana_mv.timed_slots import parse_timed_source
        from banana_mv.commission_guard import role_pictures
        from banana_mv.shoot_plan import _filming_reference_settings
        text = (
            '🍌 BANANAMV｜MASTER DIRECTOR PROMPT\n'
            '01｜PROJECT IDENTITY\n'
            'Visual Style: Ultra-realistic cinematic fantasy film\n'
            'The ending becomes a huge concert; this is Python global context.\n'
            '02｜SUBJECT DEFINITIONS\n'
            'Subject 1｜蕉大師\n'
            'Use @圖片1 as the exclusive visual identity reference.\n'
            'A bald monk wearing grey and orange robes.\n'
            'Subject 2｜白素貞\n'
            'Use @圖片2 as the exclusive visual identity reference.\n'
            'A woman with a continuous white snake tail.\n'
            'Subject 3｜大乘蕉宗神社\n'
            'The shrine is a physical environment, not another singer.\n'
            '03｜ABSOLUTE CHARACTER ENTRANCE LOCK\n'
            'Subject 1 must not appear before 00:17.813.\n'
            '04｜AUDIO AND SRT LOCK\n'
            '[S1] = Subject 1 蕉大師\n'
            '[S2] = Subject 2 白素貞\n'
            '05｜MASTER STORY CONCEPT\n'
            'FINAL STORY SPOILER: they become concert partners after 03:21.\n'
            '06｜FULL CINEMATIC STORYBOARD\n'
            'ACT 1｜THE THOUSAND-YEAR REVENGE\n'
            '\n00:00.000–00:41.888\n'
            'Sequence 01｜The White Snake Arrives\n'
            '00:00–00:16.600\n'
            'Only 白素貞 appears and climbs rain-soaked steps.\n'
            '00:16.600–00:22.800\n'
            'Wooden fish reveal and entrance of 蕉大師 at 00:17.813.\n'
            '00:19.764: 蕉大師 begins his first assigned line.\n'
            'ACT 2｜I AM NOT FAHAI\n'
            '\n00:41.888–01:35.645\n'
            'S1 monk performs a precise rebuttal at 00:41.888.\n'
            'S2 white snake replies at 00:51.300.\n'
            'ACT 3｜THE NEXT THOUSAND YEARS\n'
            '\n01:35.645–02:23.080\n'
            'The serious question causes a silent reflection.\n'
            'ACT 4｜THE WHITE SNAKE REBORN\n'
            '\n02:23.080–03:21.667\n'
            '白素貞 takes the concert stage in her new mood.\n'
            'ACT 5｜ANCIENT AND MODERN ON ONE STAGE\n'
            '\n03:21.667–04:20.733\n'
            'A coherent epic musical collaboration begins.\n'
            'ACT 6｜THE OLD SCORE IS NOT SETTLED\n'
            '\n04:20.733–04:42.540\n'
            'The dry final joke ends with 蕉大師 speaking.\n'
            '07｜CINEMATOGRAPHY AND EDITING RULES\n'
            'No random filler shots.\n'
            '08｜VISUAL CONSISTENCY AND NEGATIVE CONSTRAINTS\n'
            'No random monsters.\n'
            "09｜DIRECTOR'S PRIORITY ORDER\n"
            'Do not show the monk too early.\n'
            '10｜FINAL DIRECTOR CHECKLIST\n'
            'FINAL CHECKLIST ONLY: verify the full movie outcome.\n'
        )
        from banana_mv.core import map_image_mentions
        fixed, chapters = parse_timed_source(map_image_mentions(text,2))
        self.assertEqual(len(chapters),6,[c['title'] for c in chapters])
        self.assertEqual([(round(c['start'],3),round(c['end'],3)) for c in chapters],
                         [(0.,41.888),(41.888,95.645),(95.645,143.08),
                          (143.08,201.667),(201.667,260.733),(260.733,282.54)])
        self.assertEqual(role_pictures(fixed),
                         {'S1':'<Picture 1>','S2':'<Picture 2>'})
        filtered=_filming_reference_settings(fixed)
        self.assertIn('Environment: 大乘蕉宗神社',filtered)
        self.assertNotIn('MASTER STORY CONCEPT',filtered)
        self.assertNotIn('FINAL STORY SPOILER',filtered)
        self.assertNotIn('FINAL CHECKLIST ONLY',filtered)
        self.assertNotIn('Subject 3｜',filtered)
        self.assertIn('Visual Style:',filtered)
        req=dict(request(),prompt=text,direct_script=False,srt_cues=[
            {'start':1.205,'end':3.3,'text':'[S2] 開場'},
            {'start':17.813,'end':18.979,'text':'[S1] 阿彌陀蕉'},
            {'start':19.764,'end':22.8,'text':'[S1] 施主認錯和尚'},
            {'start':41.888,'end':51.3,'text':'[S1] Rap'},
            {'start':51.3,'end':69.988,'text':'[S2] 復仇'},
        ])
        parts=[{'index':i,'start':i*10.0,'seconds':10.0,
                'song_seconds':282.54,'segment_count':29} for i in range(28)]
        parts.append({'index':28,'start':280.,'seconds':2.54,
                      'song_seconds':282.54,'segment_count':29})
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            plan=ensure_python_slot_plan(req,parts,[root/'monk.png',root/'snake.png'],root)
        self.assertEqual(plan['source_timing'],'explicit_markdown')
        self.assertEqual(len(plan['segments']),29)
        self.assertNotIn('FINAL STORY SPOILER',plan['segments'][0]['event'])
        self.assertNotIn('FINAL CHECKLIST ONLY',plan['segments'][-1]['event'])
        self.assertNotIn('concert partners',plan['segments'][0]['event'])
        self.assertNotIn('The dry final joke',plan['segments'][0]['event'])
        self.assertIn('Only 白素貞',plan['segments'][0]['event'])
        self.assertIn('The dry final joke',plan['segments'][27]['event'])

    def test_notebook_is_named_branch_pinned_and_drive_is_separate(self):
        root=Path(__file__).resolve().parents[1]
        nb=json.loads((root/'BANANAMV_CLASSIC_PYTHON_SLOT_EXPERIMENT.ipynb').read_text(encoding='utf-8'))
        code=''.join(''.join(c['source']) for c in nb['cells'] if c['cell_type']=='code')
        self.assertIn("BRANCH = 'experiment/python-slot-director'",code)
        self.assertIn("'--branch', BRANCH",code)
        self.assertIn("drive_folder='BananaMVClassicPythonSlot'",code)
        runtime=(root/'tools/colab_runtime.py').read_text(encoding='utf-8')
        self.assertIn("drive_folder='BananaMV'",runtime)
        self.assertIn("BananaMVClassicPythonSlot",runtime)


if __name__=='__main__':
    unittest.main()
