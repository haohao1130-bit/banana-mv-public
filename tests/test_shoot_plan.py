"""Two-stage directing: real worker/resume flow, simulated 9B and GPU."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from PIL import Image

from banana_mv import server
from banana_mv.story_plan import ensure_plan
from banana_mv.shoot_plan import ensure_shoot_plan
from test_unified_direction import timeline, request


def allocation():
    return ('=== SETUP ===\nThe port stays industrial. <Picture 1> is the human singer; '
            '<Picture 2> is the non-singing hero.\n'
            '=== CLIP 0 story ===\nHUMAN_OPENING: <Picture 1> changes into <Picture 2> once.\n'
            '=== CLIP 1 action ===\nCURRENT_COUNTER: <Picture 2>, already transformed, is the non-singing hero at the industrial port. '
            'The hero holds a damaged shield, blocks one attack and ends behind a container with the shield still in hand.\n'
            '=== CLIP 2 story ===\nFINAL_BEAT: <Picture 2> holds a victory pose.\n=== END ===')


def native_prompt(i,offset=0):
    # No compulsory shot count, six-section gate or all-cast attendance check.
    return (f'<Picture {2+offset}> performs ONLY_BEAT_{i}. <Audio 1>: fully_copy. '+('Detailed native camera prose. '*190)).strip()


class ShootPlanTests(unittest.TestCase):
    def fixture(self,root,mode='independent'):
        images=[]
        for i in range(2):
            p=root/f'ref{i}.png';Image.new('RGB',(8,8)).save(p);images.append(p)
        guide=root/'guide.md';guide.write_text('OFFICIAL_NATIVE_GUIDE_MARKER')
        cfg={'guides':{'ref':str(guide)},'comfy_input_dir':str(root)}
        req=request(director_schema=5,scene_state_version=0,prompt_compiler_version=0,
                    project_scope='full',mode=mode,rewrite_retries=0,
                    prompt='PRIVATE_FULL_STORY with FUTURE_STORY_MARKER',
                    lyrics='WHOLE_SONG_LYRIC_MARKER',srt_cues=[
                        {'start':.5,'end':1.5,'text':'OPENING_CUE'},
                        {'start':5,'end':6,'text':'CURRENT_CUE'}])
        return images,cfg,req

    def test_9b_fresh_restart_does_not_inherit_rejected_draft(self):
        from banana_mv.scene_state import SceneStateError, rewrite_retry_count
        self.assertEqual(rewrite_retry_count({}),5)
        self.assertEqual(rewrite_retry_count({'rewrite_retries':0}),0)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            req['rewrite_retries']=1
            seg=dict(timeline()[1],director_plan={
                'handoff_version':1,'mode':'action',
                'event':'CURRENT_ONLY: the hero protects the shield at the port.'})
            writer=Mock(return_value=native_prompt(1))
            with patch.object(server.backend,'rewrite_local',writer),patch(
                'banana_mv.shoot_plan.check_commission',
                side_effect=[['[ERROR] wrong singer']]*3+[[]]) as guard:
                result=server.local_prompt(cfg,req,seg,images,None)
            self.assertEqual(result,native_prompt(1))
            self.assertEqual(writer.call_count,4)
            self.assertEqual(guard.call_count,4)
            self.assertIn('REPAIR THIS CLIP ONLY',writer.call_args_list[1].args[2][-1][1])
            self.assertEqual(len(writer.call_args_list[3].args[2]),
                             len(writer.call_args_list[0].args[2]))
            self.assertIn('CURRENT_ONLY',writer.call_args_list[3].args[2][0][1])
            self.assertNotIn('PREVIOUS DRAFT',writer.call_args_list[3].args[2][0][1])
            self.assertEqual(seg['prompt_profile']['fresh_restarts'],1)
            self.assertNotIn('commission_guard_errors',seg)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            req['rewrite_retries']=1
            seg=dict(timeline()[1],director_plan={
                'handoff_version':1,'mode':'action','event':'CURRENT_ONLY'})
            writer=Mock(return_value=native_prompt(1))
            with patch.object(server.backend,'rewrite_local',writer),patch(
                'banana_mv.shoot_plan.check_commission',
                return_value=['[ERROR] wrong singer']):
                with self.assertRaisesRegex(SceneStateError,'重新起稿 1 次仍未通過'):
                    server.local_prompt(cfg,req,seg,images,None)
            self.assertEqual(writer.call_count,6)

    def test_once_allocated_then_native_director_only_sees_current_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            allocator=Mock(return_value=allocation())
            plan=ensure_plan(cfg,req,timeline(),images,root,allocator)
            self.assertEqual(allocator.call_count,1)
            self.assertNotIn('OFFICIAL_NATIVE_GUIDE_MARKER',allocator.call_args.args[1])
            again=ensure_plan(cfg,req,timeline(),images,root,allocator)
            self.assertEqual(again,plan);self.assertEqual(allocator.call_count,1)
            seg=dict(timeline()[1],director_plan=plan['segments'][1],shoot_setup=plan['shared_setup'],
                     direction_ending_contract=plan['ending_contract'],previous_planned_event='HISTORY_LEAK')
            writer=Mock(return_value=native_prompt(1))
            with patch.object(server.backend,'rewrite_local',writer):
                got=server.local_prompt(cfg,req,seg,images,None)
            self.assertEqual(got,native_prompt(1))
            system=writer.call_args.args[1];text=writer.call_args.args[2][0][1]
            self.assertIn('OFFICIAL_NATIVE_GUIDE_MARKER',system)
            self.assertNotIn('prompt_word_budget',system+text)
            self.assertIn('CURRENT_COUNTER',text)
            for forbidden in ('PRIVATE_FULL_STORY','FUTURE_STORY_MARKER','HUMAN_OPENING',
                              'FINAL_BEAT','WHOLE_SONG_LYRIC_MARKER','OPENING_CUE','HISTORY_LEAK'):
                self.assertNotIn(forbidden,text)
            task=json.loads(text.split('Clip timing and audio context:\n',1)[1])
            self.assertNotIn('local_srt', task)
            self.assertNotIn('CURRENT_CUE', text)
            self.assertEqual(task['authored_vocal_timeline'], [])
            self.assertEqual(task['ending']['phase'],'resolving')
            self.assertEqual(task['ending']['local_settle_by'],3.5)
            self.assertEqual(seg['prompt_profile']['writer_calls'],1)

    def test_reverse_chinese_cast_activates_python_locked_srt_shots(self):
        # Real-world 5070 input uses @圖片1＝蕉大師，S1 rather than S1 = @圖片1.
        from banana_mv.core import map_image_mentions
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            images,cfg,req=self.fixture(root,'chain')
            req['director_schema']=6
            req['srt_cues']=[
                {'start':0,'end':1.3,'text':'[S1] 阿彌陀蕉'},
                {'start':1.3,'end':10,'text':'[S2] 一紙封印一座塔'},
            ]
            segment=dict(timeline()[0],fixed_reference_settings=map_image_mentions(
                '@圖片1＝蕉大師，S1，男性角色\n'
                '@圖片2＝白素貞，S2，女性角色\n',2),
                director_plan={'handoff_version':1,'mode':'performance',
                               'event':'白素貞唱 S2，蕉大師在旁安靜敲木魚。'})
            with patch('banana_mv.shoot_plan.write_locked_shoot_prompt',
                       return_value='subject_definitions:\n<Subject 1> S1\n'
                       'detailed_description:\n[Shot 1] <Subject 2> sings.\n'
                       'overall_soundscape:\nMusic.\nnon_diegetic_music:\nMusic.') as locked:
                result=server.local_prompt(cfg,req,segment,images,None)
            self.assertTrue(locked.called,'two authored singers must enter Python-locked camera path')
            self.assertIn('<Subject 2> sings',result)
            self.assertNotEqual(segment.get('prompt_profile',{}).get('source'),
                                'isolated_native_director')
            self.assertEqual(locked.call_args.args[5],
                             {'S1':'<Picture 1>','S2':'<Picture 2>'})

    def test_tagged_duet_sends_roles_without_lyrics_or_previous_events(self):
        from banana_mv.python_slots import split_source
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images, cfg, req = self.fixture(root, 'chain')
            setup, chapters = split_source(
                '【共同設定】\n'
                '真人寫實情侶生活 MV，從公寓出發，到海邊，再回到同一間公寓。\n'
                'S1 = @圖片1，男主角。\nS2 = @圖片2，女主角。\n'
                '依 SRT 分配對嘴。\n【劇情】\n男主角看向手機。'
            )
            from banana_mv.core import map_image_mentions
            setup = map_image_mentions(setup, 2)
            self.assertIn('海邊', setup)  # The whole route belongs to Python.
            self.assertEqual(chapters[0]['actions'], ['男主角看向手機。'])
            self.assertIn('S2 = <Picture 2>', setup)
            req['srt_cues'] = [
                {'start': 0, 'end': 1, 'text': '[S1] 那天只是看了一眼價格'},
                {'start': 1, 'end': 2, 'text': '[S2] 你上次也是這樣說的喔'},
                {'start': 2, 'end': 3, 'text': '[S1+S2] 一邊是夢一邊是幸福'},
            ]
            seg = dict(timeline()[0], fixed_reference_settings=setup, director_plan={
                'handoff_version': 1, 'mode': 'story',
                'event': 'ALREADY ESTABLISHED; do not restage: PREVIOUS_ACTION\n'
                         'Current interval actions in original order:\n- 男主角看向手機。'
            })
            writer = Mock(return_value=(
                'subject_definitions:\nMan from <Picture 2>. Woman from <Picture 3>.\n'
                'retention_analysis:\n<Audio 1>: reference - generated dialogue.\n'
                'detailed_description:\n'
                '[Shot 1] She says <d>那天只是看了一眼價格</d>. Camera moves closer.\n'
                'overall_soundscape:\nInvented voices.\nnon_diegetic_music:\nN/A'
            ))
            with patch.object(server.backend, 'rewrite_local', writer):
                got = server.local_prompt(cfg, req, seg, images, images[0])
            text = writer.call_args.args[2][0][1]
            self.assertNotIn('PREVIOUS_ACTION', text)
            self.assertNotIn('那天只是看了一眼價格', text + got)
            self.assertNotIn('海邊', text)
            self.assertNotIn('<d>', got)
            self.assertNotIn('She says', got)
            self.assertNotIn('Invented voices', got)
            self.assertIn('<Audio 1>: fully_copy.', got)
            self.assertIn('0.000–1.000s: <Picture 2>', got)
            self.assertIn('1.000–2.000s: <Picture 3>', got)
            self.assertIn('2.000–3.000s: <Picture 2> and <Picture 3>', got)
            self.assertIn('Camera moves closer', got)
            self.assertEqual(writer.call_count, 1)


    def test_global_route_is_filtered_but_srt_cast_survives(self):
        from banana_mv.python_slots import split_source
        from banana_mv.core import map_image_mentions
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images, cfg, req = self.fixture(root)
            raw = ('【共同設定】\nS1 = @圖片1，男主唱。\nS2 = @圖片2，女主唱。\n'
                   '真人寫實情侶 MV，先在公寓唱歌，後面去海邊游泳，最後回公寓。\n'
                   '【角色設定】\n人物五官與身份依圖片。\n'
                   '【故事主題】\n中段兩人去海邊玩水，最終在夕陽下告白。\n'
                   '【故事背景】\n公寓內木桌與暖色窗光。\n'
                   '【整體風格】\n真人電影攝影，自然演出。\n'
                   '【演唱與劇情安排】\n尾聲時男女主角重返公寓。\n')
            setup, _ = split_source(raw + '【劇情】\n男主角在公寓看手機。')
            self.assertIn('海邊', setup)
            req['srt_cues'] = [
                {'start': 0, 'end': 1, 'text': '[S1] 男主唱'},
                {'start': 1, 'end': 2, 'text': '[S2] 女主唱'},
                {'start': 2, 'end': 3, 'text': '[S1+S2] 合唱'},
            ]
            seg = dict(timeline()[0],
                fixed_reference_settings=map_image_mentions(setup, 2),
                director_plan={'handoff_version': 1, 'mode': 'story',
                    'event': 'Current interval actions in original order:\n'
                             '- 男主角在公寓看手機。'})
            writer = Mock(return_value='subject_definitions:\nMan from <Picture 1>.\n'
                'detailed_description:\n[Shot 1] The man checks his phone.\n'
                'overall_soundscape:\nSource song.\nnon_diegetic_music:\nSource song.')
            with patch.object(server.backend, 'rewrite_local', writer):
                prompt = server.local_prompt(cfg, req, seg, images, None)
            sent = writer.call_args.args[2][0][1]
            for retained in ('S1 = <Picture 1>', 'S2 = <Picture 2>',
                             '公寓內木桌', '真人電影攝影', '男主角在公寓看手機'):
                self.assertIn(retained, sent)
            for leaked in ('海邊', '夕陽下告白', '重返公寓', '合唱'):
                self.assertNotIn(leaked, sent)
            self.assertIn('0.000–1.000s: <Picture 1>', prompt)
            self.assertIn('1.000–2.000s: <Picture 2>', prompt)
            self.assertIn('2.000–3.000s: <Picture 1> and <Picture 2>', prompt)
            self.assertIn('unchanged (fully_copy)', prompt)

    def test_chain_uses_fixed_original_slots_and_actual_tail_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root,'chain')
            plan=ensure_plan(cfg,req,timeline(),images,root,Mock(return_value=allocation()))
            seg=dict(timeline()[1],director_plan=plan['segments'][1],shoot_setup=plan['shared_setup'])
            writer=Mock(return_value=native_prompt(1,1))
            with patch.object(server.backend,'rewrite_local',writer):
                server.local_prompt(cfg,req,seg,images,images[0])
            text=writer.call_args.args[2][0][1]
            task=json.loads(text.split('Clip timing and audio context:\n',1)[1])
            self.assertNotIn('is the human singer',text)
            self.assertIn('is the non-singing hero at the industrial port',text)
            self.assertIn('<Picture 3>, already transformed',text)
            labels=[value for kind,value in writer.call_args.args[2] if kind=='text'][1:]
            self.assertEqual(labels,['<Picture 1>:','<Picture 2>:','<Picture 3>:'])
            self.assertIn('<Picture 1>',task['first_frame'])

    def test_chain5_continuation_is_local_to_five_frame_mode_and_tail(self):
        # The single-frame and independent writer inputs remain byte-for-byte
        # unchanged; chain5 never duplicates the Python Slot event handoff.
        cases=[('chain5',True),('chain5',False),
               ('chain',True),('independent',False)]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,_=self.fixture(root)
            event=('ALREADY ESTABLISHED; do not restage: FIRST_STRIKE_DONE.\n'
                   'Current interval actions in original order:\n'
                   '- FOLLOW_THROUGH_COUNTER.')
            row={'index':1,'mode':'action','event':event,'handoff_version':1}
            for mode,has_tail in cases:
                with self.subTest(mode=mode,has_tail=has_tail):
                    _,_,req=self.fixture(root,mode)
                    seg=dict(timeline()[1],director_plan=copy.deepcopy(row),
                             fixed_reference_settings='The same two fighters remain in the arena.')
                    writer=Mock(return_value=native_prompt(1,int(has_tail)))
                    with patch.object(server.backend,'rewrite_local',writer):
                        server.local_prompt(cfg,req,seg,images,images[0] if has_tail else None)
                    self.assertEqual(writer.call_count,1)
                    text=writer.call_args.args[2][0][1]
                    task=json.loads(text.split('Clip timing and audio context:\n',1)[1])
                    expected=int(mode=='chain5' and has_tail)
                    self.assertEqual(text.count('CHAIN5 CONTINUATION:'),expected)
                    self.assertNotIn('FIRST_STRIKE_DONE', text)
                    self.assertEqual(text.count('FOLLOW_THROUGH_COUNTER'),1)
                    self.assertEqual(seg['director_plan'],row)
                    self.assertNotIn('CURRENT_ACTOR_STATE',text)
                    if expected:
                        self.assertIn('F-4',task['first_frame'])
                        self.assertIn('not its final frame',task['first_frame'])
                        self.assertIn('Keep later cinematography flexible.',text)
                    elif has_tail:
                        self.assertEqual(task['first_frame'],
                            '<Picture 1> is the actual previous last frame, not another actor.')
                    else:
                        self.assertNotIn('first_frame',task)

    def test_chain5_continuation_stays_single_with_wardrobe_and_retry(self):
        # Retry messages extend the existing request instead of rebuilding or
        # stacking continuity notes; wardrobe remains owned by Python Slot.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root,'chain5')
            req['rewrite_retries']=1
            event=('CURRENT_ACTOR_STATE (at clip start):\n'
                   '- Torso: jacket already removed.\n'
                   'EXPECTED_ACTOR_STATE_AFTER_THIS_CLIP (planned consequence):\n'
                   '- Torso: jacket already removed.\n'
                   'ALREADY ESTABLISHED; do not restage: jacket removal completed.\n'
                   'Current interval actions in original order:\n'
                   '- The fighters exchange a new counter.')
            row={'index':1,'mode':'action','event':event,'handoff_version':1}
            seg=dict(timeline()[1],director_plan=copy.deepcopy(row),
                     fixed_reference_settings='Opening costume is historical; current state takes priority.')
            writer=Mock(side_effect=['<Picture 99> invalid',native_prompt(1,1)])
            with patch.object(server.backend,'rewrite_local',writer):
                result=server.local_prompt(cfg,req,seg,images,images[0])
            self.assertEqual(result,native_prompt(1,1))
            self.assertEqual(writer.call_count,2)
            for call in writer.call_args_list:
                inputs=call.args[2]
                self.assertEqual(sum(value.count('CHAIN5 CONTINUATION:')
                                     for kind,value in inputs if kind=='text'),1)
                text=inputs[0][1]
                self.assertEqual(text.count('CURRENT_ACTOR_STATE'),1)
                self.assertEqual(text.count('EXPECTED_ACTOR_STATE_AFTER_THIS_CLIP'),1)
                self.assertNotIn('jacket removal completed', text)
                self.assertIn('The fighters exchange a new counter.',text)
            self.assertEqual(seg['director_plan'],row)

    def test_native_enhancement_keeps_parallel_script_and_authored_camera_prose(self):
        # Simulated model delivery tests routing/preservation, not 9B quality.
        from banana_mv.shoot_plan import NATIVE_ENHANCER_SYSTEM, DYNAMIC_EDITING
        setup=('<Picture 1> sings only on the concert stage. <Picture 2> is the '
               'silent courier in a separate station. These spaces never merge.')
        script=(setup+'\nIntercut the singer leaning into the microphone and the courier '
                'catching a falling parcel. The courier checks the label; return '
                'to the singer reaching toward the audience. Preserve this order.')
        camera=('subject_definitions:\n<Subject 1> comes from <Picture 1>. '
                '<Subject 2> comes from <Picture 2>.\nsummary:\n[reference generation + audio reuse] '
                'Parallel performance and story.\nretention_analysis:\n<Audio 1>: fully_copy.\n'
                'detailed_description:\n[Shot 1] A low stage-edge close-up of <Subject 1>, '
                'hands soft in the foreground, red backlight; the camera tracks left as she leans in.\n'
                '[Shot 2] At 00:03.500, cut over <Subject 2>\'s shoulder in the station; '
                'a long-lens view compresses the platform lights as the parcel drops into frame.\n'
                '[Shot 3] At 00:07.000, return to a high oblique close-up of <Subject 1> '
                'reaching toward the audience, a diagonal microphone line against blue haze.\n'
                'overall_soundscape:\n<Audio 1>: fully_copy.\nnon_diegetic_music:\nN/A')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            for dynamic in (True,False):
                seg=dict(timeline()[0],seconds=10,shoot_setup=setup,
                         director_plan={'index':0,'mode':'story','event':script,'handoff_version':1})
                before=copy.deepcopy(seg)
                writer=Mock(return_value=camera)
                with patch.object(server.backend,'rewrite_local',writer):
                    got=server.local_prompt(cfg,dict(req,dynamic_cuts=dynamic),seg,images,None)
                self.assertEqual(got,camera)
                self.assertEqual(seg['director_plan'],before['director_plan'])
                self.assertEqual(seg['shoot_setup'],setup)
                self.assertEqual(writer.call_count,1)
                system=writer.call_args.args[1];text=writer.call_args.args[2][0][1]
                self.assertEqual(system,NATIVE_ENHANCER_SYSTEM+'OFFICIAL_NATIVE_GUIDE_MARKER')
                self.assertTrue(text.startswith('Target video duration: 10.000000 seconds.'))
                self.assertIn('Original prompt:\nCurrent clip script:\n'+script,text)
                self.assertIn('Current clip script:\n'+script,text)
                self.assertIn('Allocate shot durations and cut timing',text)
                self.assertEqual(DYNAMIC_EDITING in text,dynamic)
                self.assertNotIn('3–5',text)
                if not dynamic:self.assertIn('Prefer motivated longer takes.',text)
                graph=server.build_workflow(['one.png','two.png'],'song.wav',32,32,245,got,42)
                self.assertEqual(graph['7']['inputs']['prompt'],camera)

    def test_copied_long_event_retries_without_losing_original_story(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root);req['rewrite_retries']=1
            event='The courier arrives, opens the parcel, delivers its contents and leaves. '*8
            bad=('=== SETUP ===\nKeep <Picture 1> and <Picture 2> separate.\n'
                 '=== CLIP 0 story ===\nMode: story\n'+event+
                 '\n=== CLIP 1 action ===\nMode: action\n'+event+
                 '\n=== CLIP 2 story ===\nHold the delivered parcel.\n=== END ===')
            model=Mock(side_effect=[bad,allocation()])
            plan=ensure_plan(cfg,req,timeline(),images,root,model)
            self.assertEqual(model.call_count,2)
            self.assertEqual(plan['segments'][1]['mode'],'action')
            self.assertIn('PRIVATE_FULL_STORY',model.call_args.args[2][0][1])
            self.assertIn('重複',json.loads((root/'director_attempt_00.json').read_text())['error'])

    def test_short_repeated_holds_are_allowed(self):
        from banana_mv.shoot_plan import _check_distinct_events
        _check_distinct_events([{'index':i,'event':'Hold the final pose.'} for i in range(3)])

    def test_adaptation_reaches_both_stages_without_changing_native_delivery(self):
        from banana_mv.shoot_plan import CREATIVE_DIRECTION, FAITHFUL_DIRECTION
        for free in (False,True):
            with self.subTest(free=free),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);images,cfg,req=self.fixture(root)
                req.update(story_plan=free,intensity='extreme',dynamic_cuts=True)
                allocator=Mock(return_value=allocation())
                plan=ensure_plan(cfg,req,timeline(),images,root,allocator)
                expected=CREATIVE_DIRECTION if free else FAITHFUL_DIRECTION
                other=FAITHFUL_DIRECTION if free else CREATIVE_DIRECTION
                system=allocator.call_args.args[1]
                self.assertIn(expected,system);self.assertNotIn(other,system)
                task=json.loads(allocator.call_args.args[2][0][1])
                self.assertEqual(task['intensity'],'extreme')
                self.assertTrue(task['dynamic_cuts'])
                self.assertEqual(task['adaptation'],'FREE' if free else 'FAITHFUL')
                seg=dict(timeline()[1],director_plan=plan['segments'][1],
                         shoot_setup=plan['shared_setup'])
                writer=Mock(return_value=native_prompt(1))
                with patch.object(server.backend,'rewrite_local',writer):
                    result=server.local_prompt(cfg,req,seg,images,None)
                text=writer.call_args.args[2][0][1]
                self.assertIn(expected,text);self.assertNotIn(other,text)
                self.assertNotIn('HUMAN_OPENING',text);self.assertNotIn('FINAL_BEAT',text)
                self.assertEqual(result,native_prompt(1));self.assertEqual(writer.call_count,1)

    def test_pre_policy_cache_resumes_without_reallocating(self):
        from banana_mv.scene_state import digest
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            allocator=Mock(return_value=allocation())
            plan=ensure_plan(cfg,req,timeline(),images,root,allocator)
            task=json.loads(allocator.call_args.args[2][0][1])
            task['format']='isolated_shoot_briefs_v1'
            plan['input_sha256']=digest({k:v for k,v in task.items()
                                        if k not in ('intensity','dynamic_cuts')})
            (root/'director_plan.json').write_text(json.dumps(plan))
            self.assertEqual(ensure_plan(cfg,req,timeline(),images,root,allocator),plan)
            self.assertEqual(allocator.call_count,1)

    def test_global_setup_with_future_story_is_not_transmitted(self):
        leaked='Story spine: GLOBAL_SECRET_START then FUTURE_CONCERT and FINAL_CHAIR_END.'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            delivered=allocation().replace('=== SETUP ===\n','=== SETUP ===\n'+leaked+'\n')
            plan=ensure_plan(cfg,req,timeline(),images,root,Mock(return_value=delivered))
            self.assertIn(leaked,plan['shared_setup']) # Kept only as upstream audit evidence.
            seg=dict(timeline()[1],director_plan=plan['segments'][1],shoot_setup=plan['shared_setup'],
                     direction_ending_contract=plan['ending_contract'])
            writer=Mock(return_value=native_prompt(1))
            with patch.object(server.backend,'rewrite_local',writer):
                result=server.local_prompt(cfg,req,seg,images,None)
            outgoing=writer.call_args.args[1]+''.join(v for k,v in writer.call_args.args[2] if k=='text')
            for marker in ('GLOBAL_SECRET_START','FUTURE_CONCERT','FINAL_CHAIR_END','HUMAN_OPENING','FINAL_BEAT'):
                self.assertNotIn(marker,outgoing)
            for required in ('damaged shield','industrial port','non-singing hero','ends behind a container'):
                self.assertIn(required,outgoing)
            self.assertEqual(result,native_prompt(1))

    def test_legacy_commission_is_not_repaired_with_global_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            seg=dict(timeline()[0],director_plan={'index':0,'mode':'story','event':'A short old brief.'},
                     shoot_setup='GLOBAL_FUTURE_ENDING')
            writer=Mock(return_value=native_prompt(0))
            with patch.object(server.backend,'rewrite_local',writer):
                with self.assertRaisesRegex(ValueError,'新任務'):
                    server.local_prompt(cfg,req,seg,images,None)
            writer.assert_not_called()

    def test_photographic_intensity_reaches_both_stages_in_each_adaptation_mode(self):
        from banana_mv.shoot_plan import AUTO_FILMING, CLIP_INTENSITY, DYNAMIC_EDITING, REFERENCE_PERFORMANCE
        for free in (False,True):
            for level in ('normal','high','extreme'):
                for dynamic in (False,True):
                    with self.subTest(free=free,level=level,dynamic=dynamic),tempfile.TemporaryDirectory() as tmp:
                        root=Path(tmp);images,cfg,req=self.fixture(root)
                        req.update(story_plan=free,intensity=level,dynamic_cuts=dynamic)
                        allocator=Mock(return_value=allocation())
                        plan=ensure_plan(cfg,req,timeline(),images,root,allocator)
                        system=allocator.call_args.args[1]
                        self.assertIn(CLIP_INTENSITY[level],system)
                        self.assertIn(REFERENCE_PERFORMANCE,system)
                        for other in set(CLIP_INTENSITY)-{level}:
                            self.assertNotIn(CLIP_INTENSITY[other],system)
                        seg=dict(timeline()[1],director_plan=plan['segments'][1],shoot_setup=plan['shared_setup'])
                        writer=Mock(return_value=native_prompt(1))
                        with patch.object(server.backend,'rewrite_local',writer):
                            result=server.local_prompt(cfg,req,seg,images,None)
                        text=writer.call_args.args[2][0][1]
                        self.assertIn(CLIP_INTENSITY[level],text)
                        self.assertIn(AUTO_FILMING,text)
                        self.assertIn(REFERENCE_PERFORMANCE,text)
                        self.assertEqual(DYNAMIC_EDITING in text,dynamic)
                        if not dynamic:self.assertIn('Prefer motivated longer takes.',text)
                        if level!='normal':
                            self.assertNotIn('Use restrained',system+text)
                            self.assertNotIn('balanced with sustained images',text)
                        self.assertEqual(result,native_prompt(1))
                        self.assertNotIn('FINAL_BEAT',text)

    def test_bad_delivery_retries_compactly_without_story_replanning_per_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root);req['rewrite_retries']=1
            model=Mock(side_effect=['Long failed analysis. '*1000,allocation()])
            ensure_plan(cfg,req,timeline(),images,root,model)
            self.assertEqual(model.call_count,2)
            self.assertNotIn('Long failed analysis',model.call_args.args[2][-1][1])
            self.assertTrue((root/'director_attempt_00.json').exists())
            p=root/'director_plan.json';d=json.loads(p.read_text());d['shared_setup']='tampered';p.write_text(json.dumps(d))
            with self.assertRaisesRegex(ValueError,'校驗失敗'):
                ensure_plan(cfg,req,timeline(),images,root,model)
            self.assertEqual(model.call_count,2)

    def test_cross_genre_scripts_keep_scope_with_all_intensities(self):
        from banana_mv.shoot_plan import AUTO_FILMING, CLIP_INTENSITY, DYNAMIC_EDITING
        cases={
            'band':'The singer turns toward the guitarist; they finish the phrase together.',
            'story':'The traveler opens a letter, pauses, and leaves it on the table.',
            'comedy':'The server catches a falling cup, notices the empty tray, and holds still.',
            'action':'The dancer pivots, lands, and passes a ribbon to the waiting partner.',
            'fantasy':'An empty courtyard fills with drifting fog; no character enters.'}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            for mode,script in cases.items():
                for intensity in ('normal','high','extreme'):
                    for dynamic in (False,True):
                        with self.subTest(mode=mode,intensity=intensity,dynamic=dynamic):
                            row={'index':0,'mode':mode,'event':script,'handoff_version':1}
                            seg=dict(timeline()[0],seconds=15,director_plan=copy.deepcopy(row),
                                     shoot_setup='Keep supplied identities and separate locations.')
                            writer=Mock(return_value=native_prompt(0))
                            with patch.object(server.backend,'rewrite_local',writer):
                                got=server.local_prompt(cfg,dict(req,intensity=intensity,dynamic_cuts=dynamic),seg,images,None)
                            self.assertEqual(got,native_prompt(0));self.assertEqual(writer.call_count,1)
                            self.assertEqual(seg['director_plan'],row)
                            text=writer.call_args.args[2][0][1]
                            self.assertIn('Current clip script:\n'+script+'\n\n',text)
                            self.assertIn(AUTO_FILMING,text)
                            self.assertIn(CLIP_INTENSITY[intensity],text)
                            self.assertEqual(DYNAMIC_EDITING in text,dynamic)
                            self.assertNotIn('3–5',text)
                            for other in cases.values():
                                if other!=script:self.assertNotIn(other,text)

    def test_incomplete_or_unconnected_allocations_never_reach_clip_writer(self):
        for bad in (allocation().replace('=== END ===',''),
                    allocation().replace('=== CLIP 1 action ===','=== CLIP 9 action ==='),
                    allocation().replace('<Picture 2>','<Picture 9>')):
            with self.subTest(bad=bad[:80]),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);images,cfg,req=self.fixture(root)
                with self.assertRaises(ValueError):
                    ensure_plan(cfg,req,timeline(),images,root,Mock(return_value=bad))
                self.assertFalse((root/'director_plan.json').exists())

    def test_worker_resume_reuses_plan_and_saved_prompt_then_directs_only_unwritten_clip(self):
        for mode in ('independent','chain'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
                root=Path(tmp);images,cfg,req=self.fixture(root,mode)
                work=root/'abcdef123456';work.mkdir()
                job={'id':work.name,'request':req,'segments':timeline(),'status':'running',
                     'size':[32,32],'images_comfy':['ref0.png','ref1.png'],'seed':42,
                     'duration':9,'output_size':[32,32]}
                outputs=[native_prompt(i,int(mode=='chain' and i>0)) for i in range(3)]
                model=Mock(side_effect=[allocation()]+outputs)
                lock=threading.Lock();lock.acquire();downloads=[0];graphs=[]
                def download(config,item,dest):
                    downloads[0]+=1
                    if downloads[0]==2:raise RuntimeError('interrupted')
                    dest.write_bytes(b'raw')
                def queue(config,graph):graphs.append(copy.deepcopy(graph));return str(len(graphs))
                for owner,name,value in [(server,'RUNS',root),(server,'GPU_LOCK',lock),
                    (server.backend,'DATA',root),(server.backend,'rewrite_local',model),
                    (server,'preflight',Mock()),(server,'valid_part',lambda p,*a:p.is_file()),
                    (server,'audio_window',lambda src,dest,*a:dest.write_bytes(b'audio')),
                    (server.backend,'queue_prompt',queue),(server.backend,'history_entry',Mock(return_value=None)),
                    (server,'wait_generation',Mock(return_value={'outputs':{'x':{'videos':[{'filename':'out.mp4'}]}}})),
                    (server.backend,'comfy_download',download),
                    (server,'trim_video',lambda src,dest,*a:dest.write_bytes(b'part')),
                    (server,'last_frame',lambda src,dest:Image.new('RGB',(8,8)).save(dest)),
                    (server,'assemble',lambda parts,song,dest,*a:dest.write_bytes(b'final'))]:
                    stack.enter_context(patch.object(owner,name,value))
                server.worker(job,cfg,images,root/'song.wav',root/'song.wav')
                self.assertEqual(job['status'],'error');self.assertEqual(model.call_count,3)
                self.assertFalse((work/'02_prompt_v1.txt').exists())
                first=(work/'00_part_v1.mp4').read_bytes();saved=(work/'01_prompt_v1.txt').read_text()
                job['resuming']=True;lock.acquire()
                server.worker(job,cfg,images,root/'song.wav',root/'song.wav')
                self.assertEqual(job['status'],'done',job.get('error'))
                self.assertEqual(model.call_count,4)  # One allocation + three native directors.
                self.assertEqual((work/'00_part_v1.mp4').read_bytes(),first)
                self.assertEqual((work/'01_prompt_v1.txt').read_text(),saved)
                self.assertEqual([g['7']['inputs']['prompt'] for g in graphs],
                                 [outputs[0],outputs[1],outputs[1],outputs[2]])
                self.assertTrue(all(g['7']['inputs']['audio_mode']=='lock_source' for g in graphs))
                for call in model.call_args_list[1:]:
                    self.assertNotIn('PRIVATE_FULL_STORY',call.args[2][0][1])


if __name__=='__main__':unittest.main()
