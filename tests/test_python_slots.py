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
