import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from banana_mv.music_structure import validate_result,local_structure,load_structure,direction,REVISION,MODEL,VERSION
from banana_mv.audio_analysis import source_hash,audio_guidance


def prediction():
    return {'bpm':120,'beats':[.5,1,1.5,2,2.5,3,3.5],'downbeats':[.5,2.5],
            'segments':[{'start':0,'end':2,'label':'verse'},{'start':2,'end':4,'label':'chorus'}]}


class StructureTests(unittest.TestCase):
    def test_local_time_and_padding(self):
        cue=local_structure(validate_result(prediction(),4),{'start':1,'seconds':2})
        self.assertEqual(cue['downbeats_s'],[1.5])
        self.assertEqual(cue['sections'][0],{'start_s':0,'end_s':1,'predicted_label':'verse','begins_here':False})
        self.assertEqual(cue['sections'][1]['start_s'],1)
        self.assertTrue(cue['sections'][1]['begins_here'])
        tail=local_structure(validate_result(prediction(),4),{'start':3,'seconds':4})
        self.assertEqual(tail['sections'][0]['end_s'],1)
        self.assertIn('fallible',direction(cue))

    def test_invalid_predictions_rejected(self):
        for change in ({'bpm':float('nan')},{'beats':[2,1]},{'downbeats':[5]},
                       {'segments':[{'start':0,'end':4,'label':'guitar'}]},
                       {'segments':[{'start':0,'end':1,'label':'verse'}]}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_result(dict(prediction(),**change),4)

    def test_cache_bound_to_source_and_missing_runtime_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=root/'song';song.write_bytes(b'original');cache=root/'cache.json'
            identity={'version':VERSION,'source_sha256':source_hash(song),'revision':REVISION,'model':MODEL}
            cache.write_text(json.dumps(dict(prediction(),**identity)))
            with patch.dict('os.environ',{'BANANA_MUSIC_PYTHON':str(root/'missing')}):
                self.assertEqual(load_structure(song,cache,4)['bpm'],120)
                song.write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError,'尚未安裝'):
                    load_structure(song,cache,4)
            self.assertEqual(song.read_bytes(),b'changed')

    def test_final_prompt_retains_music_cues(self):
        cue=local_structure(validate_result(prediction(),4),{'start':0,'seconds':4})
        text=audio_guidance({'relative_energy':'high','energy_change_db':0,'transient_candidates_s':[],
                             'quiet_intervals_s':[],'music_structure':cue})
        for word in ('chorus','downbeats','do not cut on every beat'):
            self.assertIn(word,text)

    def test_worker_routes_structure_before_planning(self):
        from banana_mv import server
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job_id='abcdef123456';(root/job_id).mkdir();lock=threading.Lock();lock.acquire()
            seg={'index':0,'start':1,'seconds':2,'status':'waiting'}
            job={'id':job_id,'status':'running','request':{'audio_analysis':True,'music_structure':True,
                 'director_version':2,'story_plan':True,'rewrite':True,'director_schema':5},'size':[32,32],'segments':[seg]}
            def stop(*args,**kwargs):
                self.assertEqual(seg['audio_evidence']['music_structure']['sections'][1]['start_s'],1)
                raise RuntimeError('STOP_AFTER_ROUTING')
            with patch.object(server,'RUNS',root),patch.object(server,'GPU_LOCK',lock), \
                 patch.object(server,'load_analysis',return_value={'seconds':4,'pulse':None}), \
                 patch.object(server,'load_structure',return_value=validate_result(prediction(),4)) as load, \
                 patch.object(server,'segment_evidence',return_value={}), \
                 patch.object(server,'ensure_plan',side_effect=stop), \
                 patch.object(server.backend,'queue_prompt') as queue:
                server.worker(job,{'comfy_input_dir':str(root)},[],root/'song',root/'song')
                load.assert_called_once();self.assertIn('STOP_AFTER_ROUTING',job['error'])
                self.assertEqual(job['audio_analysis']['structure']['status'],'ready')
                self.assertFalse(lock.locked());queue.assert_not_called()

    def test_actual_allocator_and_clip_writer_receive_music_evidence(self):
        from unittest.mock import Mock
        from banana_mv import server
        from banana_mv.story_plan import ensure_plan
        from test_shoot_plan import ShootPlanTests,allocation,native_prompt
        from test_unified_direction import timeline
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=ShootPlanTests().fixture(root)
            rows=timeline()
            for s in rows:
                s['audio_evidence']={'relative_energy':'medium','energy_change_db':0,
                    'transient_candidates_s':[],'quiet_intervals_s':[],
                    'music_structure':local_structure(validate_result(prediction(),4),s)}
            allocator=Mock(return_value=allocation())
            plan=ensure_plan(cfg,req,rows,images,root,allocator)
            upper=json.loads(allocator.call_args.args[2][0][1])
            self.assertEqual(upper['timeline'][0]['audio_evidence'],rows[0]['audio_evidence'])
            seg=dict(rows[1],director_plan=plan['segments'][1])
            writer=Mock(return_value=native_prompt(1))
            with patch.object(server.backend,'rewrite_local',writer):
                output=server.local_prompt(cfg,req,seg,images,None)
            lower=writer.call_args.args[2][0][1]
            context=json.loads(lower.split('Clip timing and audio context:\n',1)[1])
            self.assertEqual(context['audio_evidence'],rows[1]['audio_evidence'])
            self.assertIn('Write their timing into the shots',lower)
