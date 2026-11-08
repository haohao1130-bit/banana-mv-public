"""VNext production-path regressions, offline 9B/ComfyUI mocks only."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from banana_mv import server, takes
import test_shoot_plan as mv_fixtures
from test_unified_direction import timeline
from banana_mv.story_plan import ensure_plan


def native(body='[Shot 1] <Subject 1> acts.', retention='<Audio 1>: fully_copy - original recording.'):
    return ('subject_definitions:\n<Subject 1> from <Picture 1>.\n<Audio 1> is the supplied song.\n'
            'summary:\n[reference generation + audio reuse] The current event.\n'
            'retention_analysis:\n'+retention+'\ndetailed_description:\n'+body+
            '\noverall_soundscape:\nSource recording unchanged.\nnon_diegetic_music:\nThe supplied song.')


class VNextMVTests(unittest.TestCase):
    def fixture(self, root):
        images,cfg,req=mv_fixtures.ShootPlanTests().fixture(root)
        req['h3_validation_version']=1
        plan=ensure_plan(cfg,req,timeline(),images,root,Mock(return_value=mv_fixtures.allocation()))
        seg=dict(timeline()[0],director_plan=plan['segments'][0])
        return images,cfg,req,seg

    def test_new_writer_rejects_non_native_and_missing_audio_copy(self):
        for bad in ['<Picture 1> moves. <Audio 1>: fully_copy.',
                    native(retention='<Audio 1>: reference - rewrite the song.'),
                    native('[Shot 1] Setup. [Shot 2] At 00:59.000, too late.')]:
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                images,cfg,req,seg=self.fixture(Path(tmp))
                with patch.object(server.backend,'rewrite_local',return_value=bad), self.assertRaises(ValueError):
                    server.local_prompt(cfg,req,seg,images,None)

    def test_new_writer_retries_invalid_then_delivers_valid_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            images,cfg,req,seg=self.fixture(Path(tmp));req['rewrite_retries']=1
            model=Mock(side_effect=['plain malformed output',native()])
            with patch.object(server.backend,'rewrite_local',model):
                self.assertEqual(server.local_prompt(cfg,req,seg,images,None),native())
            self.assertEqual(model.call_count,2)

    def test_local_correction_uses_same_format_and_audio_contract(self):
        for bad in ['plain invalid output',native('[Shot 1] Setup. [Shot 2] At 00:59.000, late.'),
                    native(retention='<Audio 1>: partially_copy')]:
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);images,cfg,req,seg=self.fixture(root)
                with patch.object(server.backend,'rewrite_local',return_value=bad), self.assertRaises(ValueError):
                    takes.repair_prompt(cfg,{'request':req},seg,native(),'closer camera',images,None,root)

    def test_legacy_saved_prose_can_still_be_normalized(self):
        from banana_mv.core import normalize_mv_prompt
        self.assertEqual(normalize_mv_prompt('<Picture 1> acts.',1),'<Picture 1> acts.')

    def test_real_worker_stops_before_queue_or_recovers_by_format_retry(self):
        import copy
        import threading
        from contextlib import ExitStack
        for recover in (False,True):
            with self.subTest(recover=recover),tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
                root=Path(tmp);images,cfg,req,seg=self.fixture(root)
                req.update(rewrite_retries=int(recover),audio_analysis=False)
                work=root/'abcdef123456';work.mkdir()
                job={'id':work.name,'request':req,'segments':timeline(),'status':'running',
                     'size':[32,32],'images_comfy':['ref0.png','ref1.png'],'seed':42,
                     'duration':9,'output_size':[32,32]}
                outputs=[mv_fixtures.allocation(),'invalid new prompt']+([native()]*3 if recover else [])
                model=Mock(side_effect=outputs);graphs=[];lock=threading.Lock();lock.acquire()
                def queue(cfg,graph):graphs.append(copy.deepcopy(graph));return str(len(graphs))
                for owner,name,value in [(server,'RUNS',root),(server,'GPU_LOCK',lock),
                    (server.backend,'DATA',root),(server.backend,'rewrite_local',model),
                    (server,'preflight',Mock()),(server,'valid_part',lambda p,*a:p.is_file()),
                    (server,'audio_window',lambda src,dest,*a:dest.write_bytes(b'audio')),
                    (server.backend,'queue_prompt',queue),
                    (server,'wait_generation',Mock(return_value={'outputs':{'x':{'videos':[{'filename':'out.mp4'}]}}})),
                    (server.backend,'comfy_download',lambda cfg,item,dest:dest.write_bytes(b'raw')),
                    (server,'trim_video',lambda src,dest,*a:dest.write_bytes(b'part')),
                    (server,'assemble',lambda parts,song,dest,*a:dest.write_bytes(b'final'))]:
                    stack.enter_context(patch.object(owner,name,value))
                server.worker(job,cfg,images,root/'song.wav',root/'song.wav')
                self.assertEqual(job['status'],'done' if recover else 'error',job.get('error'))
                self.assertEqual(len(graphs),3 if recover else 0)
                if recover:
                    self.assertTrue(all(g['7']['inputs']['audio_mode']=='lock_source' for g in graphs))
                else:
                    self.assertFalse((work/'final.mp4').exists())
                self.assertFalse(lock.locked())
