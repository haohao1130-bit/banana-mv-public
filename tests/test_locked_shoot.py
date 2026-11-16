"""Python-owned singer cuts and 9B visual-only slot tests."""
import unittest
from banana_mv.locked_shoot import plan_slots, _extract, _errors, _native, _native_output_template, _repair_vocals, _commission_text, write_locked_shoot_prompt


def cue(a,b,*roles):
    return {'clip_start':a,'clip_end':b,'subjects':list(roles)}


class LockedShootTests(unittest.TestCase):
    def test_python_cuts_on_singer_changes_and_source_beats(self):
        slots=plan_slots(10.0,[cue(0,5.240,'S1'),cue(5.240,7.087,'S2'),cue(7.087,10,'S1')],
                         {'music_structure':{'downbeats_s':[2.3,8.76]}},True)
        times=[s['start'] for s in slots]
        self.assertIn(5.24,times)
        self.assertIn(7.087,times)
        self.assertEqual(times[0],0.0)
        self.assertTrue(any('ONLY lip-syncs' in x for s in slots for x in s['rows']))
        self.assertEqual(slots[-1]['end'],10.0)

    def test_short_srt_switch_stays_inside_one_cinematic_shot(self):
        slots=plan_slots(10,[cue(0,0.22,'S1'),cue(.22,9.82,'S2'),cue(9.82,10,'S1')],{},True)
        full=' '.join(x for s in slots for x in s['rows'])
        self.assertIn('0.000–0.220s',full)
        self.assertIn('0.220–5.000s',full)
        self.assertIn('5.000–9.820s',full)
        self.assertIn('9.820–10.000s',full)

    def test_source_only_authorizes_roles_and_python_writes_clothes(self):
        slots=plan_slots(10,[cue(0,5,'S1'),cue(5,10,'S2')],{},False)
        draft='[Shot 1] <Subject 1> gestures while the camera circles the guitar.\n[Shot 2] <Subject 2> walks to the water as the camera tracks alongside.'
        bodies=_extract(draft,slots)
        self.assertEqual(_errors(bodies,{'S1':'short-sleeve top and shorts','S2':'pure-white tie-string bikini'}),{})
        text=_native(bodies,slots,{'S1':'<Picture 2>','S2':'<Picture 3>'},
                     {'S1':'short-sleeve top and shorts','S2':'pure-white tie-string bikini'},
                     True,'S2 沿著浪線往前走。',3)
        self.assertIn('<Subject 1> is the adult lead S1 from <Picture 2>',text)
        self.assertIn('<Subject 2> is the adult lead S2 from <Picture 3>',text)
        self.assertIn('pure-white tie-string bikini',text)
        self.assertIn('[Shot 2] At 00:05.000',text)
        self.assertIn('overall_soundscape:',text)
        self.assertNotIn('hoodie',text)
        self.assertNotIn('cardigan',text)

    def test_correct_singing_is_not_forbidden(self):
        slots=plan_slots(10,[cue(0,10,'S1')],{},False)
        body='<Subject 1> sings into camera while the camera glides forward.'
        corrected,changes=_repair_vocals({1:body},slots,'S1 = <Picture 1>, male singer')
        self.assertEqual(corrected[1],body)
        self.assertEqual(changes,[])
        self.assertEqual(_errors(corrected,{}),{})

    def test_wrong_singer_replaced_in_python_but_camera_is_preserved(self):
        slots=plan_slots(10,[cue(0,10,'S1')],{},False)
        body='<Subject 2> sings while the camera pans from right to left.'
        corrected,changes=_repair_vocals({1:body},slots,
                        'S1 = <Picture 1>, male singer\nS2 = <Picture 2>, female singer')
        self.assertEqual(len(changes),1)
        self.assertIn('<Subject 2> moves to the beat while the camera pans from right to left.',corrected[1])
        self.assertNotIn('<Subject 2> sings',corrected[1])
        self.assertEqual(_errors(corrected,{}),{})

    def test_silent_reaction_watcher_and_negation_do_not_false_trigger(self):
        slots=plan_slots(10,[cue(0,10,'S1')],{},False)
        fixed='S1 = <Picture 1>, male singer\nS2 = <Picture 2>, female singer'
        bodies=[
            'She is watching <Subject 1> singing while the camera moves.',
            '<Subject 2> watches <Subject 1> sing, then smiles.',
            'She watches him singing as the camera cuts wider.',
            '<Subject 2> is not singing; she gestures with her hand.',
            'He is singing while she watches the light shift.',
        ]
        for body in bodies:
            with self.subTest(body=body):
                corrected,changes=_repair_vocals({1:body},slots,fixed)
                self.assertEqual(corrected[1],body)
                self.assertEqual(changes,[])

    def test_pronouns_duets_and_instrumental_tail_get_targeted_correction(self):
        fixed='S1 = <Picture 1>, male singer\nS2 = <Picture 2>, female singer'
        slots=plan_slots(10,[cue(0,10,'S1')],{},False)
        bodies=['She is lip-syncing as the camera pushes in.',
                'Both sing and the camera follows their hands.',
                'He sings as the camera tracks backward.']
        for body in bodies[:2]:
            repaired,records=_repair_vocals({1:body},slots,fixed)
            self.assertEqual(len(records),1)
            self.assertIn('camera',repaired[1])
            self.assertNotIn('sing',repaired[1])
            self.assertNotIn('lip-syncing',repaired[1])
        repaired,records=_repair_vocals({1:bodies[2]},slots,fixed)
        self.assertEqual(repaired[1],bodies[2])
        self.assertFalse(records)
        empty=plan_slots(1.208,[],{},False)
        repaired,records=_repair_vocals({1:'<Subject 1> sings to camera.'},empty,fixed)
        self.assertEqual(len(records),1)
        self.assertIn('moves to the beat',repaired[1])

    def test_mixed_singers_within_one_shot_keep_python_timing(self):
        slots=plan_slots(10,[cue(0,.2,'S1'),cue(.2,9.8,'S2'),
                             cue(9.8,10,'S1')],{},True)
        self.assertIn('S1',slots[0]['allowed_singers'])
        self.assertIn('S2',slots[0]['allowed_singers'])
        revised,changes=_repair_vocals({1:'<Subject 1> sings and <Subject 2> sings.'},
                                        slots[:1],'')
        self.assertEqual(changes,[])
        self.assertIn('<Subject 2> sings',revised[1])

    def test_wrong_vocal_and_clothes_are_separate_concerns(self):
        slots=plan_slots(10,[cue(0,10,'S1')],{},False)
        blocks={1:'<Subject 2> sings into camera while wearing a hoodie.'}
        fixed,changes=_repair_vocals(blocks,slots,'')
        self.assertEqual(len(changes),1)
        self.assertNotIn('<Subject 2> sings',fixed[1])
        errors=_errors(fixed,{'S1':'short-sleeve top and shorts'})
        self.assertIn('[ERROR][Wardrobe]',str(errors))
        self.assertNotIn('[ERROR][Vocal]',str(errors))
        with self.assertRaises(ValueError):
            _extract('[Shot 2] Extra camera.',plan_slots(10,[],{},False))

    def test_only_bad_shot_is_rewritten_and_temperature_is_reduced(self):
        record=[]
        replies=[
            '[Shot 1] <Subject 1> sings while sitting in a hoodie.\n[Shot 2] <Subject 2> gestures as the camera tracks left.',
            '[Shot 1] <Subject 1> sings while sitting in a short-sleeve top and shorts.',
        ]
        def writer(config,system,parts,job):
            record.append((config['rewriter']['temperature'],parts[0][1]))
            return replies.pop(0)
        config={'rewriter':{'temperature':0.7,'thinking':False}}
        request={'dynamic_cuts':False,'srt_cues':[
            {'start':0,'end':5,'text':'[S1] line'},
            {'start':5,'end':10,'text':'[S2] line'}]}
        segment={'index':0,'start':0,'seconds':10,'audio_evidence':{}}
        result=write_locked_shoot_prompt(config,request,segment,'- S1 示意，S2 點頭。',
                   'S1 = <Picture 1>\nS2 = <Picture 2>',
                   {'S1':'<Picture 1>','S2':'<Picture 2>'},
                   {'S1':'short-sleeve top and shorts'},
                   ['a','b'],[],writer)
        self.assertIn('[Shot 1]',result)
        self.assertIn('[Shot 2] At 00:05.000',result)
        self.assertEqual([x[0] for x in record],[.4,.15])
        self.assertIn('REPAIR ONLY [Shot 1]',record[1][1])
        self.assertNotIn('REPAIR ONLY [Shot 2]',record[1][1])
        self.assertEqual(segment['prompt_profile']['writer_calls'],2)

    def test_9b_commission_order_is_hard_locks_event_cinematography(self):
        slots=plan_slots(10,[cue(0,2.3,'S1'),cue(2.3,8.76,'S2'),
                             cue(8.76,10,'S1')],{},False)
        text=_commission_text(
            {'intensity':'extreme'},{'index':4,'seconds':10},
            '- S1 帶著外出包走到海岸；S2 接住毛巾。',
            {'S1':'<Picture 2>','S2':'<Picture 3>'},
            {'S1':'short-sleeve top and shorts',
             'S2':'pure-white tie-string bikini'},slots,True)
        self.assertLess(text.index('CURRENT WARDROBE'),text.index('LOCKED SHOT SLOTS'))
        self.assertLess(text.index('LOCKED SHOT SLOTS'),text.index('THIS CLIP EVENT'))
        self.assertLess(text.index('THIS CLIP EVENT'),text.index('CINEMATOGRAPHY AND OUTPUT'))
        self.assertLess(text.index('CINEMATOGRAPHY AND OUTPUT'),text.index('Return only'))
        self.assertIn('face and hairstyle from <Picture 3> ONLY',text)
        self.assertIn('CURRENT OUTFIT: pure-white tie-string bikini',text)
        self.assertIn('[Shot 2] 2.300–8.760s',text)
        self.assertIn('ONLY lip-syncs',text)
        self.assertIn('OPENING CONTINUITY: <Picture 1>',text)
        self.assertEqual(text.count('THIS CLIP EVENT'),1)
        self.assertNotIn('authored_vocal_timeline',text)
        self.assertNotIn('shared_setup',text)

    def test_no_wardrobe_override_does_not_force_reference_costume(self):
        slots=plan_slots(10,[cue(0,10,'S1')],{},False)
        text=_commission_text(
            {},{'index':0,'seconds':10},'- S1 拿起吉他。',
            {'S1':'<Picture 1>','S2':'<Picture 2>'},{},slots,False)
        self.assertIn('already-established outfit',text)
        self.assertNotIn('overrides clothing visible in the reference photo',text)
        self.assertNotIn('OPENING CONTINUITY: <Picture 1> supplies',text)
        self.assertIn('start directly with the assigned current event',text)

    def test_9b_initial_request_receives_reordered_commission(self):
        captured=[]
        def fake_rewrite(config,system,parts,seed):
            captured.append(parts[0][1])
            return ('[Shot 1] <Subject 1> sings as the camera tilts up.\n'
                    '[Shot 2] <Subject 2> gestures as the camera follows.')
        cfg={'rewriter':{'temperature':.4,'thinking':False}}
        req={'dynamic_cuts':False,'srt_cues':[
            {'start':0,'end':5,'text':'[S1] first line'},
            {'start':5,'end':10,'text':'[S2] second line'}]}
        seg={'index':0,'start':0,'seconds':10,'audio_evidence':{}}
        output=write_locked_shoot_prompt(
            cfg,req,seg,'- S1 彈奏吉他，S2 跟著節拍點頭。',
            'S1 = <Picture 1>\nS2 = <Picture 2>',
            {'S1':'<Picture 1>','S2':'<Picture 2>'},{},
            ['a','b'],[],fake_rewrite)
        self.assertEqual(len(captured),1)
        self.assertLess(captured[0].index('LOCKED SHOT SLOTS'),
                        captured[0].index('THIS CLIP EVENT'))
        self.assertIn('subject_definitions:',captured[0])
        self.assertIn('detailed_description:',captured[0])
        self.assertIn('overall_soundscape:',captured[0])
        self.assertTrue(captured[0].rstrip().endswith('The supplied original song.'))
        self.assertIn('sings as the camera tilts up',output)

    def test_repair_9b_gets_own_one_shot_format_contract_not_full_writer(self):
        calls=[]
        outputs=[
            '[Shot 1] <Subject 1> sings while sitting in a hoodie.\n'
            '[Shot 2] <Subject 2> gestures as the camera tracks left.',
            '[Shot 1]\n<Subject 1> sings while sitting in a short-sleeve top and shorts.'
        ]
        def model(cfg,system,parts,job_id):
            calls.append({'system':system,'parts':parts})
            return outputs.pop(0)
        cfg={'rewriter':{'temperature':.4,'thinking':False}}
        req={'dynamic_cuts':False,'srt_cues':[
            {'start':0,'end':5,'text':'[S1] verse'},
            {'start':5,'end':10,'text':'[S2] verse'}]}
        seg={'index':0,'start':0,'seconds':10,'audio_evidence':{}}
        fake_images=[('text','<Picture 1>:'),('image','fake-image-1'),
                     ('text','<Picture 2>:'),('image','fake-image-2')]
        film=write_locked_shoot_prompt(
            cfg,req,seg,'- S1 移動身體，S2 跟著點頭。',
            'S1 = <Picture 1>\nS2 = <Picture 2>',
            {'S1':'<Picture 1>','S2':'<Picture 2>'},
            {'S1':'short-sleeve top and shorts'},
            ['a','b'],fake_images,model)
        self.assertEqual(len(calls),2)
        # First-shot format requirement follows all picture inputs.
        self.assertEqual(calls[0]['parts'][:-1],fake_images)
        self.assertEqual(calls[0]['parts'][-1][0],'text')
        self.assertIn('LOCKED SHOT SLOTS',calls[0]['parts'][-1][1])
        self.assertIn('CURRENT WARDROBE',calls[0]['parts'][-1][1])
        self.assertIn('SIX native Ref2VA sections',calls[0]['system'])
        # Single-shot repair neither sends image placeholders at the end
        # nor asks the model to generate the full shot list again.
        self.assertEqual(len(calls[1]['parts']),1)
        self.assertNotIn('<Picture 1>:',calls[1]['parts'][0][1])
        self.assertIn('EDITING ONE SHOT',calls[1]['system'])
        self.assertIn('native six-section Ref2VA format',calls[1]['system'])
        self.assertIn('detailed_description:',calls[1]['parts'][0][1])
        self.assertTrue(calls[1]['parts'][0][1].endswith('The supplied original song.'))
        self.assertIn('[Shot 1]',film)
        self.assertIn('[Shot 2] At 00:05.000',film)
        self.assertEqual(seg['prompt_profile']['writer_calls'],2)

    def test_native_h3_six_field_model_reply_is_parsed_without_using_its_unlocked_fields(self):
        slots=plan_slots(10,[cue(0,5,'S1'),cue(5,10,'S2')],{},False)
        template=_native_output_template(slots,
            {'S1':'<Picture 1>','S2':'<Picture 2>'},{})
        self.assertEqual([x for x in (
            'subject_definitions:','summary:','retention_analysis:',
            'detailed_description:','overall_soundscape:',
            'non_diegetic_music:') if x in template].__len__(),6)
        native_reply=(
            'subject_definitions:\nIncorrect invented clothes.\n'
            'summary:\nWhatever.\nretention_analysis:\nIncorrect clothes.\n'
            'detailed_description:\n'
            '[Shot 1] <Subject 1> sings while the camera rises.\n'
            '[Shot 2] At 00:05.000, <Subject 2> sings as the camera tracks.\n'
            'overall_soundscape:\nInvented effects.\n'
            'non_diegetic_music:\nInvented music.')
        bodies=_extract(native_reply,slots)
        self.assertEqual(sorted(bodies),[1,2])
        final=_native(bodies,slots,
            {'S1':'<Picture 1>','S2':'<Picture 2>'},{},False,
            '- This clip has its existing event.',2)
        self.assertNotIn('Incorrect invented clothes',final)
        self.assertNotIn('Invented music.',final)
        self.assertIn('<Subject 1> sings',final)

    def test_single_shot_native_detailed_description_without_shot_label(self):
        slots=plan_slots(10,[cue(0,10,'S1')],{},False)
        native=('subject_definitions:\nCast.\nsummary:\nPresent clip.\n'
                'retention_analysis:\nCast from image.\n'
                'detailed_description:\n<Subject 1> sings while the camera arcs '
                'around him in a medium shot and catches his expression.\n'
                'overall_soundscape:\nSource music unchanged.\n'
                'non_diegetic_music:\nSource track.')
        body=_extract(native,slots,only=1)
        self.assertEqual(sorted(body),[1])
        self.assertIn('camera arcs',body[1])
        with self.assertRaises(ValueError):
            _extract('A bare unlabeled paragraph.',slots,only=1)

    def test_no_lip_sync_assigned_to_terminal_instrumental_tail(self):
        slots=plan_slots(1.208,[],{},False)
        self.assertIn('No assigned visible lip-sync',slots[0]['rows'][0])
