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
            self.assertEqual(ensure_python_slot_plan(request(),clips(),[],root)['version'],6)
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
                self.assertNotIn('OPEN_01',received) if index>0 else None
                self.assertNotIn('ENDING_03',received) if index<26 else None
                self.assertNotIn('CRISIS_02',received) if index==0 else None
            self.assertEqual(plan['segments'][-1]['index'],27)

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
