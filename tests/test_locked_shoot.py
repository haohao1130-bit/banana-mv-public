"""Python-owned singer cuts and 9B visual-only slot tests."""
import unittest
from banana_mv.locked_shoot import plan_slots, singer_rows, _global_vocal_rows, _extract, _errors, _native, _native_output_template, _repair_vocals, _commission_text, write_locked_shoot_prompt


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
        self.assertTrue(any('If showing lip-sync' in x for s in slots for x in s['rows']))
        self.assertEqual(slots[-1]['end'],10.0)

    def test_short_srt_switch_stays_inside_one_cinematic_shot(self):
        slots=plan_slots(10,[cue(0,0.22,'S1'),cue(.22,9.82,'S2'),cue(9.82,10,'S1')],{},True)
        full=' '.join(x for s in slots for x in s['rows'])
        self.assertIn('0.000–0.220s',full)
        self.assertIn('0.220–5.000s',full)
        self.assertIn('5.000–9.820s',full)
        self.assertIn('9.820–10.000s',full)

    def test_consecutive_srt_labels_merge_into_single_role_windows(self):
        cues=[cue(0,.920,'S2'),cue(.920,3.360,'S2'),cue(3.360,3.660,'S2'),
              cue(3.660,5.400,'S2'),cue(5.400,7.920,'S2'),cue(7.920,10,'S1')]
        slots=plan_slots(10,cues,{},True)
        merged=_global_vocal_rows(slots)
        self.assertEqual(len(merged),2)
        self.assertIn('0.000–7.920s: If showing lip-sync, use <Subject 2> (SRT S2)',merged[0])
        self.assertIn('7.920–10.000s: If showing lip-sync, use <Subject 1> (SRT S1)',merged[1])
        self.assertNotIn('0.920–3.360s',' '.join(merged))
        self.assertEqual(len(singer_rows(0,10,cues)),2)

    def test_overlapping_separate_srt_lines_are_not_a_duet(self):
        # In the Bai Suzhen song the 03:47.940–03:48.015 overlap is
        # two independently labeled SRT cues, not an authored [S1+S2].
        cues=[cue(0,8.015,'S1'),cue(7.940,10,'S2')]
        rows=singer_rows(0,10,cues)
        self.assertTrue(any('No authored duet' in row for row in rows),rows)
        self.assertFalse(any('lip-sync together' in row for row in rows),rows)
        slots=plan_slots(10,cues,{},False)
        both=next(slot for slot in slots if set(slot['allowed_singers'])=={'S1','S2'})
        self.assertFalse(both['duet_authorized'])
        repaired,audit=_repair_vocals(
            {both['number']:'Both sing while the camera arcs around the shrine.'},
            [both],'S1 = <Picture 1>\nS2 = <Picture 2>')
        self.assertEqual(len(audit),1)
        self.assertNotIn('Both sing',repaired[both['number']])
        self.assertIn('camera arcs',repaired[both['number']])

    def test_explicit_s1_plus_s2_duet_still_works(self):
        cues=[cue(0,10,'S1','S2')]
        self.assertTrue(any('lip-sync together' in row for row in singer_rows(0,10,cues)))
        slot=plan_slots(10,cues,{},False)[0]
        self.assertTrue(slot['duet_authorized'])
        original='Both sing while the camera arcs around the shrine.'
        revised,audit=_repair_vocals({slot['number']:original},[slot],
                                     'S1 = <Picture 1>\nS2 = <Picture 2>')
        self.assertEqual(revised[slot['number']],original)
        self.assertEqual(audit,[])

    def test_real_gap_and_duet_break_merging(self):
        cues=[cue(0,2,'S2'),cue(2,4,'S2'),cue(4.5,6,'S2'),
              cue(6,8,'S1','S2'),cue(8,10,'S1')]
        rows=singer_rows(0,10,cues)
        self.assertEqual(len(rows),5)
        self.assertIn('0.000–4.000s: If showing lip-sync, use <Subject 2>',rows[0])
        self.assertIn('4.000–4.500s: No SRT cast hint',rows[1])
        self.assertIn('4.500–6.000s: If showing lip-sync, use <Subject 2>',rows[2])
        self.assertIn('6.000–8.000s: If showing the duet, <Subject 1> and <Subject 2>',rows[3])
        self.assertIn('8.000–10.000s: If showing lip-sync, use <Subject 1> (SRT S1)',rows[4])

    def test_final_h3_prompt_lists_singers_once_separate_from_shots(self):
        cues=[cue(0,3,'S2'),cue(3,5,'S2'),cue(5,10,'S1')]
        slots=plan_slots(10,cues,{},False)
        blocks={i['number']:f'<Subject 2> glances at the screen. Camera dolly shot {i["number"]}.'
                for i in slots}
        result=_native(blocks,slots,{'S1':'<Picture 1>','S2':'<Picture 2>'},
                       {},False,'兩人在室內工作。',2)
        detail=result.split('detailed_description:',1)[1].split('overall_soundscape:',1)[0]
        self.assertIn('SRT CAST HINTS',detail)
        self.assertEqual(detail.count('If showing lip-sync'),2)
        self.assertIn('[Shot 1]',detail)
        self.assertIn('[Shot 2]',detail)
        self.assertNotIn('0.000–3.000s:',detail)

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

    def test_reverse_binds_keep_bai_suzhen_rap_and_silence_monk(self):
        # White snake sings S2 from 00:51.300; the monk's S1 turn is over.
        fixed = '<Picture 1>＝蕉大師，S1，男性角色\n<Picture 2>＝白素貞，S2，女性角色\n'
        slots=plan_slots(10,[cue(0,1.3,'S1'),cue(1.3,10,'S2')],{},False)
        self.assertAlmostEqual(slots[1]['start'],1.3)
        bad='<Subject 1> raps with the camera circling; he speaks as the rain falls.'
        revised,audit=_repair_vocals({2:bad},slots[1:],fixed)
        self.assertEqual(len(audit),2,audit)
        self.assertNotIn(' raps ',revised[2])
        self.assertNotIn(' speaks ',revised[2])
        self.assertIn('camera circling',revised[2])
        self.assertIn('rain falls',revised[2])
        by_pronoun='He is rapping beside <Subject 2> who looks forward.'
        revised,audit=_repair_vocals({2:by_pronoun},slots[1:],fixed)
        self.assertEqual(len(audit),1,audit)
        self.assertIn('He is moving to the beat',revised[2])
        okay='<Subject 2> raps to the original track while <Subject 1> plays the wooden fish.'
        revised,audit=_repair_vocals({2:okay},slots[1:],fixed)
        self.assertEqual(revised[2],okay)
        self.assertEqual(audit,[])

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
        self.assertFalse(records)
        self.assertEqual(repaired[1], '<Subject 1> sings to camera.')

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
        blocks={1:'<Subject 2> sings into camera beside <Picture 2>.'}
        fixed,changes=_repair_vocals(blocks,slots,'')
        self.assertEqual(len(changes),1)
        self.assertNotIn('<Subject 2> sings',fixed[1])
        errors=_errors(fixed,{})
        self.assertIn('[ERROR][Cast]',str(errors))
        self.assertNotIn('[ERROR][Vocal]',str(errors))
        self.assertNotIn('[ERROR][Wardrobe]',str(errors))   # 寫死的服裝規則已移除
        with self.assertRaises(ValueError):
            _extract('[Shot 2] Extra camera.',plan_slots(10,[],{},False))

    def test_two_failed_local_shot_repairs_restart_full_draft_with_limit(self):
        from banana_mv.scene_state import SceneStateError
        cfg={'rewriter':{'temperature':.4,'thinking':False}}
        req={'dynamic_cuts':False,'rewrite_retries':1,'srt_cues':[
            {'start':0,'end':5,'text':'[S1] verse'},
            {'start':5,'end':10,'text':'[S2] verse'}]}
        bad=('[Shot 1] <Subject 1> sings beside <Picture 2> while camera approaches.\n'
             '[Shot 2] <Subject 2> gestures as the camera tracks left.')
        bad_fix='[Shot 1] <Subject 1> sings beside <Picture 2> in a camera close-up.'
        good=('[Shot 1] <Subject 1> sings in a short-sleeve top and shorts, camera approaches.\n'
              '[Shot 2] <Subject 2> gestures as the camera tracks left.')
        seg={'index':0,'start':0,'seconds':10,'audio_evidence':{}}
        calls=[]
        def writer(config,system,parts,seed):
            calls.append(parts)
            return [bad,bad_fix,bad_fix,good][len(calls)-1]
        result=write_locked_shoot_prompt(cfg,req,seg,'- S1 sings; S2 reacts.',
                  'S1 = <Picture 1>\nS2 = <Picture 2>',
                  {'S1':'<Picture 1>','S2':'<Picture 2>'},
                  {'S1':'short-sleeve top and shorts'},['a','b'],[],writer)
        self.assertIn('short-sleeve top and shorts',result)
        self.assertEqual(len(calls),4)
        self.assertIn('REPAIR ONE SHOT ONLY',calls[1][0][1])
        self.assertNotIn('REPAIR ONE SHOT ONLY',calls[3][-1][1])
        self.assertIn('LOCKED SHOT SLOTS',calls[3][-1][1])
        self.assertEqual(seg['prompt_profile']['fresh_restarts'],1)
        self.assertNotIn('commission_guard_errors',seg)
        seg={'index':0,'start':0,'seconds':10,'audio_evidence':{}}
        calls.clear()
        def fails(config,system,parts,seed):
            calls.append(parts)
            if 'REPAIR ONE SHOT ONLY' in parts[-1][1]:
                return bad_fix
            return bad
        with self.assertRaisesRegex(SceneStateError,'自動重新起稿 1 次'):
            write_locked_shoot_prompt(cfg,req,seg,'- S1 sings; S2 reacts.',
                    'S1 = <Picture 1>\nS2 = <Picture 2>',
                    {'S1':'<Picture 1>','S2':'<Picture 2>'},
                    {'S1':'short-sleeve top and shorts'},['a','b'],[],fails)
        self.assertEqual(len(calls),6)

    def test_only_bad_shot_is_rewritten_and_temperature_is_reduced(self):
        record=[]
        replies=[
            '[Shot 1] <Subject 1> sings while sitting beside <Picture 2>.\n[Shot 2] <Subject 2> gestures as the camera tracks left.',
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
        self.assertIn('REPAIR ONE SHOT ONLY: [Shot 1]',record[1][1])
        self.assertNotIn('REPAIR ONE SHOT ONLY: [Shot 2]',record[1][1])
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
        self.assertLess(text.index('CINEMATOGRAPHY AND OUTPUT'),text.index('OUTPUT SHAPE'))
        self.assertIn('face and hairstyle from <Picture 3> ONLY',text)
        self.assertIn('CURRENT OUTFIT: pure-white tie-string bikini',text)
        self.assertIn('[Shot 2] 2.300–8.760s',text)
        self.assertIn('If showing lip-sync',text)
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
            '[Shot 1] <Subject 1> sings while sitting beside <Picture 2>.\n'
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
        full=_extract(native,slots)
        self.assertEqual(full[1],body[1])
        with self.assertRaises(ValueError):
            _extract('A bare unlabeled paragraph.',slots,only=1)


    def test_reference_clothes_do_not_reset_on_ordinary_beach_or_apartment_clip(self):
        from banana_mv.commission_guard import scene_wardrobe_schedule
        fixed='S1 = <Picture 2>\nS2 = <Picture 3>'
        pictures={'S1':'<Picture 2>','S2':'<Picture 3>'}
        one='USER-SPECIFIED SONG TIME — active time inside THIS clip is 0.000–10.000s.\n'
        self.assertEqual(scene_wardrobe_schedule(
            one+'PYTHON-OWNED CURRENT EVENT — scene 海邊',fixed,pictures,10),[])
        self.assertEqual(scene_wardrobe_schedule(
            one+'PYTHON-OWNED CURRENT EVENT — scene 公寓',fixed,pictures,10),[])

    def test_no_lip_sync_assigned_to_terminal_instrumental_tail(self):
        slots=plan_slots(1.208,[],{},False)
        self.assertIn('No SRT cast hint',slots[0]['rows'][0])
