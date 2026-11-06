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
            '=== CLIP 1 action ===\nCURRENT_COUNTER: <Picture 2>, already transformed, blocks an attack.\n'
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
            self.assertEqual(task['local_srt'][0]['clip_start'],1)
            self.assertEqual(task['local_srt'][0]['text'],'CURRENT_CUE')
            self.assertEqual(task['ending']['phase'],'resolving')
            self.assertEqual(task['ending']['local_settle_by'],3.5)
            self.assertEqual(seg['prompt_profile']['writer_calls'],1)

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
            self.assertIn('<Picture 2> is the human',text)
            self.assertIn('<Picture 3> is the non-singing hero',text)
            self.assertIn('<Picture 3>, already transformed',text)
            labels=[value for kind,value in writer.call_args.args[2] if kind=='text'][1:]
            self.assertEqual(labels,['<Picture 1>:','<Picture 2>:','<Picture 3>:'])
            self.assertIn('<Picture 1>',task['first_frame'])

    def test_native_enhancement_keeps_parallel_script_and_authored_camera_prose(self):
        # Simulated model delivery tests routing/preservation, not 9B quality.
        from banana_mv.shoot_plan import NATIVE_ENHANCER_SYSTEM, DYNAMIC_EDITING
        setup=('<Picture 1> sings only on the concert stage. <Picture 2> is the '
               'silent courier in a separate station. These spaces never merge.')
        script=('Intercut the singer leaning into the microphone and the courier '
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
                         director_plan={'index':0,'mode':'story','event':script})
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
                self.assertIn('Original prompt:\nShared world and reference roles:\n'+setup,text)
                self.assertIn('Current clip script:\n'+script,text)
                self.assertIn('Allocate shot durations and cut timing',text)
                self.assertEqual(DYNAMIC_EDITING in text,dynamic)
                self.assertNotIn('3–5',text)
                if not dynamic:self.assertIn('Prefer motivated longer takes.',text)
                graph=server.build_workflow(['one.png','two.png'],'song.wav',32,32,245,got,42)
                self.assertEqual(graph['7']['inputs']['prompt'],camera)

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
                            row={'index':0,'mode':mode,'event':script}
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
                self.assertFalse((work/'02_prompt.txt').exists())
                first=(work/'00_part.mp4').read_bytes();saved=(work/'01_prompt.txt').read_text()
                job['resuming']=True;lock.acquire()
                server.worker(job,cfg,images,root/'song.wav',root/'song.wav')
                self.assertEqual(job['status'],'done',job.get('error'))
                self.assertEqual(model.call_count,4)  # One allocation + three native directors.
                self.assertEqual((work/'00_part.mp4').read_bytes(),first)
                self.assertEqual((work/'01_prompt.txt').read_text(),saved)
                self.assertEqual([g['7']['inputs']['prompt'] for g in graphs],
                                 [outputs[0],outputs[1],outputs[1],outputs[2]])
                self.assertTrue(all(g['7']['inputs']['audio_mode']=='lock_source' for g in graphs))
                for call in model.call_args_list[1:]:
                    self.assertNotIn('PRIVATE_FULL_STORY',call.args[2][0][1])


if __name__=='__main__':unittest.main()

