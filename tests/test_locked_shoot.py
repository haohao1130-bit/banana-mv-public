"""Python-owned singer cuts and 9B visual-only slot tests."""
import unittest
from banana_mv.locked_shoot import plan_slots, _extract, _errors, _native, write_locked_shoot_prompt


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

    def test_wrong_vocal_and_clothes_cannot_pass(self):
        blocks={1:'<Subject 1> sings into camera wearing a hoodie.'}
        errors=_errors(blocks,{'S1':'short-sleeve top and shorts'})
        self.assertIn('[ERROR][Vocal]',str(errors))
        self.assertIn('[ERROR][Wardrobe]',str(errors))
        with self.assertRaises(ValueError):
            _extract('[Shot 2] Extra camera.',plan_slots(10,[],{},False))

    def test_only_bad_shot_is_rewritten_and_temperature_is_reduced(self):
        record=[]
        replies=[
            '[Shot 1] <Subject 1> sings while sitting.\n[Shot 2] <Subject 2> gestures as the camera tracks left.',
            '[Shot 1] <Subject 1> raises his hand while the camera tilts up.',
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
                   {'S1':'<Picture 1>','S2':'<Picture 2>'},{},
                   ['a','b'],[],writer)
        self.assertIn('[Shot 1]',result)
        self.assertIn('[Shot 2] At 00:05.000',result)
        self.assertEqual([x[0] for x in record],[.4,.15])
        self.assertIn('REPAIR ONLY [Shot 1]',record[1][1])
        self.assertNotIn('REPAIR ONLY [Shot 2]',record[1][1])
        self.assertEqual(segment['prompt_profile']['writer_calls'],2)

    def test_no_lip_sync_assigned_to_terminal_instrumental_tail(self):
        slots=plan_slots(1.208,[],{},False)
        self.assertIn('No assigned visible lip-sync',slots[0]['rows'][0])
