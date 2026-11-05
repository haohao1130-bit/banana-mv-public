import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from banana_mv.core import fallback_prompt
from banana_mv.director import director_prompt, mode_candidates, resolve_modes
from banana_mv.prompt_quality import (enforce_reference_policy,
                                      reference_policy, MV_POLICY, director_led, DIRECTOR_AUTHORITY)
from banana_mv.story_plan import allowed_modes, validate_plan


class PromptQualityTests(unittest.TestCase):
    def req(self, **changes):
        return dict({'optimizer_version':1,'director_version':2,'director':'action','intensity':'high',
                     'prompt':'參考圖人物在演唱會演唱，另在格鬥場武打。格鬥場不演唱。'},**changes)

    def test_base_prompt_no_longer_forces_singing_into_action_first_scene(self):
        prompt=fallback_prompt('First frame already in combat; stage and arena stay separate.',scene_aware=True)
        self.assertNotIn('The performer sings in a medium close-up',prompt)
        self.assertIn('Do not add an opening singing shot',prompt)
        self.assertIn('The performer sings in a medium close-up',fallback_prompt('legacy'))

    def test_scoped_negation_and_modes_work_for_manual_and_auto(self):
        for selected in ('action','auto'):
            req=self.req(director=selected)
            self.assertIn('performance',mode_candidates(req)[0])
            self.assertIn('performance',allowed_modes(req))
            stage={'director_plan':{'event':'The performer sings on stage.','mode':'performance'}}
            fight={'director_plan':{'event':'The performer blocks a punch.','mode':'action'}}
            self.assertEqual(resolve_modes(req,stage),['performance'])
            self.assertEqual(resolve_modes(req,fight)[0],'action')
            from banana_mv.server import graph_options
            self.assertEqual(graph_options(req,10,stage)['director_mode'],'performance')
            self.assertEqual(graph_options(req,10,fight)['director_mode'],'action')
            self.assertNotIn('action: Show a complete causal exchange',director_prompt(req,10,stage)[0])
        req=self.req(director='auto',prompt='不要武打，只要演唱。')
        self.assertNotIn('action',allowed_modes(req))
        self.assertIn('MOVEMENT:',director_prompt(self.req(),10)[0])
        self.assertEqual(allowed_modes(self.req(prompt='Only boxing in the arena, no singing.')),{'action'})

    def test_planner_accepts_valid_modes_and_rejects_only_invalid_codes(self):
        row={'events':[{'event':'The referenced performer approaches the front of the concert stage.','mode':'performance'}]}
        self.assertEqual(validate_plan(row,[{'index':0}],self.req())['segments'][0]['mode'],'performance')
        with self.assertRaises(ValueError):
            validate_plan({'events':[dict(row['events'][0],mode='invalid-mode')]},[{'index':0}],
                          self.req(director='auto',prompt='不要武打，只要演唱'))

    def test_reference_mapping_groups_and_repeated_application(self):
        policy=reference_policy(4,True)
        self.assertIn('Main original reference: <Picture 2>',policy)
        self.assertIn('<Picture 1> is the previous final frame',policy)
        self.assertIn('Preserve all distinct people',policy)
        self.assertIn('unless explicitly requested',policy)
        text=enforce_reference_policy('prompt',policy)
        self.assertEqual(enforce_reference_policy(text,policy),text)
        self.assertEqual(text.count('[BANANA_REFERENCE_ROLES_V1]'),1)
        self.assertNotIn('小語',policy)
        self.assertNotIn('蕉彌',policy)
        self.assertIn('SUPPORTING WARDROBE',policy)
        self.assertIn('boxing trunks and boxing shoes',policy)
        self.assertIn('Preserve explicit user/reference costumes',policy)
        self.assertIn('do not dress animal or mascot bodies',policy)

    def test_creative_variation_does_not_trigger_a_second_model_or_abort(self):
        from PIL import Image
        from banana_mv import server
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);photo=root/'ref.png';Image.new('RGB',(32,32)).save(photo)
            guide=root/'guide.md';guide.write_text('H3 prompt guide')
            req=self.req(rewrite=True)
            # Deliberately different creative ending: valid text still goes through.
            draft='subject_definitions: performer from <Picture 1>.\nsummary: The clip ends in the arena.'
            segment={'index':0,'segment_count':4,'seconds':15,'model_frames':362}
            with patch.object(server.backend,'rewrite_local',return_value=draft) as rewrite:
                result=server.local_prompt({'guides':{'ref':str(guide)}},req,segment,[photo],None)
            self.assertIn('The clip ends in the arena',result)
            self.assertEqual(rewrite.call_count,1)
            self.assertNotIn('prompt_review',segment)
            self.assertEqual(segment['prompt_validation']['kind'],'technical_only')
            for invalid in (' ',):
                with patch.object(server.backend,'rewrite_local',return_value=invalid) as rewrite:
                    with self.assertRaises(ValueError):
                        server.local_prompt({'guides':{'ref':str(guide)}},req,dict(segment),[photo],None)
                    self.assertEqual(rewrite.call_count,1)

    def test_missing_model_reference_repairs_once_or_uses_validated_source(self):
        from PIL import Image
        from banana_mv import server
        from banana_mv.core import normalize_mv_prompt, MediaReferenceError
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);photo=root/'ref.png';Image.new('RGB',(32,32)).save(photo)
            guide=root/'guide.md';guide.write_text('H3 guide')
            cfg={'guides':{'ref':str(guide)}}
            req=self.req(rewrite=True,prompt='@圖片1 sings; @圖片2 boxes.')
            for tail,missing in ((None,3),(photo,4)):
                count=2+int(bool(tail))
                for repaired in (True,False):
                    seg={'seconds':10,'model_frames':242}
                    draft=f'<Picture {missing}> boxes.'
                    second='<Picture 2> boxes with <Audio 1>.' if repaired else draft
                    with patch.object(server.backend,'rewrite_local',side_effect=[draft,second]) as rewrite:
                        final=server.local_prompt(cfg,req,seg,[photo,photo],tail)
                    normalize_mv_prompt(final,count)
                    self.assertEqual(rewrite.call_count,2)
                    self.assertEqual(seg['prompt_reference_repair']['status'],'repaired' if repaired else 'fallback')
                    self.assertNotIn(f'<Picture {missing}>',final)
                    if not repaired:
                        self.assertIn(f'<Picture {1+int(bool(tail))}> sings',final)
                        self.assertIn(f'<Picture {2+int(bool(tail))}> boxes',final)
            with patch.object(server.backend,'rewrite_local') as rewrite:
                with self.assertRaises(MediaReferenceError):
                    server.local_prompt(cfg,self.req(prompt='<Picture 3> sings'),{'seconds':10,'model_frames':242},[photo,photo],None)
                rewrite.assert_not_called()

    def test_valid_plan_data_is_not_rejected_for_creative_content(self):
        # Technical enum/string checks remain; genre/duplicates/word count are not creative vetoes.
        rows={'events':[{'event':'唱','mode':'comedy'},{'event':'唱','mode':'comedy'}]}
        plan=validate_plan(rows,[{'index':0},{'index':1}],self.req(director='action'))
        self.assertEqual(len(plan['segments']),2)
        self.assertEqual(plan['segments'][1]['mode'],'comedy')

    def test_director_authority_is_opt_in_and_changes_actual_plan_and_clip_route(self):
        from banana_mv.story_plan import ensure_plan, plan_context
        from banana_mv import server
        from PIL import Image
        req=self.req(rewrite=True,story_plan=True,director_authority=True)
        self.assertTrue(director_led(req))
        self.assertFalse(director_led(dict(req,story_plan=False)))
        self.assertFalse(director_led(dict(req,rewrite=False)))
        self.assertFalse(director_led(self.req())) # persisted older projects do not silently switch authority.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);photo=root/'ref.png';Image.new('RGB',(32,32)).save(photo)
            segs=[{'index':0,'start':0,'seconds':15,'segment_count':2,'model_frames':362},
                  {'index':1,'start':15,'seconds':15,'segment_count':2,'model_frames':362}]
            draft='{"events":[{"event":"A deadpan reaction adds contrast to the music.","mode":"comedy"},{"event":"The performer drives the next boxing exchange.","mode":"action"}]}'
            planner=Mock(return_value=draft)
            plan=ensure_plan({},req,segs,[photo],root,planner)
            self.assertIn(DIRECTOR_AUTHORITY,planner.call_args.args[1])
            self.assertEqual(plan['segments'][0]['mode'],'comedy')
            segs[0]['director_plan']=plan['segments'][0]
            self.assertIn('not a mandatory shot sequence',plan_context(segs[0],True))
            self.assertEqual(server.graph_options(req,15,segs[0])['director_mode'],'comedy')
            guide=root/'guide.md';guide.write_text('H3 guide')
            rewriter=Mock(return_value='summary: A deadpan reaction in <Picture 1> to <Audio 1>.')
            with patch.object(server.backend,'rewrite_local',rewriter):
                server.local_prompt({'guides':{'ref':str(guide)}},req,segs[0],[photo],None)
            self.assertEqual(rewriter.call_count,1)
            self.assertIn(DIRECTOR_AUTHORITY,rewriter.call_args.args[1])

    def test_local_prompt_only_rewrites_once_and_keeps_reference_numbering(self):
        from PIL import Image
        from banana_mv import server
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);photo=root/'reference.png';Image.new('RGB',(32,32)).save(photo)
            guide=root/'guide.md';guide.write_text('H3 reference guide')
            cfg={'guides':{'ref':str(guide)}}
            for selected in ('action','auto'):
                seg={'seconds':10,'model_frames':260,
                     'director_plan':{'mode':'performance','event':'The reference performer sings on the stage.'}}
                req=self.req(director=selected,rewrite=True)
                original=req['prompt']
                rewrite=Mock(return_value='subject_definitions: <Subject 1> from <Picture 2>. <Audio 1>: fully_copy.\nsummary: Stage singing.')
                with patch.object(server.backend,'rewrite_local',rewrite):
                    final=server.local_prompt(cfg,req,seg,[photo,photo],photo)
                self.assertEqual(rewrite.call_count,1)
                self.assertEqual(seg['prompt_validation'],{'status':'passed','kind':'technical_only'})
                self.assertEqual(seg['director_mode'],'performance')
                self.assertIn('Main original reference: <Picture 2>',final)
                self.assertTrue(final.endswith('[/BANANA_FACE_IDENTITY_V1]'))
                self.assertEqual(req['prompt'],original)
                self.assertIn('REFERENCE ROLE CONTRACT',rewrite.call_args_list[0].args[2][0][1])
                self.assertIn('SUPPORTING WARDROBE',rewrite.call_args_list[0].args[2][0][1])
                self.assertIn('SUPPORTING WARDROBE',final)

    def test_music_video_is_the_optimizer_priority_instead_of_a_continuous_film(self):
        from banana_mv.story_plan import plan_input
        req=self.req()
        self.assertIn(MV_POLICY,reference_policy(1))
        self.assertIn(MV_POLICY,plan_input(req,[{'index':0,'start':0,'seconds':10}]))
        text=director_prompt(req,10)[0]
        self.assertIn('source music and supplied music evidence -> clip function',text)
        self.assertIn('do not demand a complete setup',MV_POLICY.lower())
        self.assertIn('without fixed quotas',MV_POLICY)
        self.assertIn('no fixed cut interval',text)
        self.assertNotIn('roughly 3–5',text)

    def test_no_rewrite_path_has_rules_but_no_false_semantic_review(self):
        from banana_mv import server
        req=self.req(rewrite=False,face_identity=False)
        seg={'seconds':10,'model_frames':260}
        with patch.object(server.backend,'rewrite_local',side_effect=AssertionError('must not invoke 9B')):
            prompt=server.local_prompt({},req,seg,[Path('unused.png')],None)
        self.assertEqual(seg['prompt_validation']['kind'],'technical_only')
        self.assertIn('[BANANA_REFERENCE_ROLES_V1]',prompt)
        self.assertNotIn('The performer sings in a medium close-up',prompt)
