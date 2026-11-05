import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

from banana_mv.core import (assemble, audio_window, build_workflow, command, dimensions,
                            duration, fallback_prompt, last_frame, output_dimensions, probe, reference_images,
                            segments, trim_video)


class TimelineTests(unittest.TestCase):
    def test_face_identity_binding_is_idempotent_and_keeps_user_text(self):
        from banana_mv.core import enforce_face_identity, normalize_mv_prompt
        original='summary:\n@圖片2 is scenery; <Audio 1>: fully_copy'
        for picture in (1,2):
            text=enforce_face_identity(original,picture)
            self.assertTrue(text.startswith(original))
            self.assertIn(f'same individual shown in <Picture {picture}>',text)
            self.assertEqual(enforce_face_identity(text,picture),text)
            self.assertNotIn('<Video',normalize_mv_prompt(text,3))
            self.assertIn('head turns, profiles, dynamic movement',text)
        switched=enforce_face_identity(enforce_face_identity(original,1),2)
        self.assertEqual(switched.count('[BANANA_FACE_IDENTITY_V1]'),1)
        self.assertIn('same individual shown in <Picture 2>',switched)
        for bad in (0,-1,True,1.5):
            with self.assertRaises(ValueError):enforce_face_identity(original,bad)

    def test_rewriter_media_tags(self):
        from banana_mv.core import normalize_mv_prompt
        self.assertEqual(normalize_mv_prompt('<Video 1> uses <Picture 2> and <Audio 1>',2),
                         'the generated clip uses <Picture 2> and <Audio 1>')
        self.assertEqual(normalize_mv_prompt('<Image 1> and < video 3 >',1),
                         '<Picture 1> and the generated clip')
        for text in ('<Audio 2>','<Picture 3>','<Picture 0>','  '):
            with self.assertRaises(ValueError):normalize_mv_prompt(text,2)

    def test_model_patches_preserve_audio_and_baseline(self):
        args=('ref.png','slice.wav',1280,736,362,'<Audio 1>',42,'tail.png')
        base=build_workflow(*args,acceleration=False,motion_lora=False)
        patched=build_workflow(*args,director_mode='action')
        for key in ('7','12','13','14','15','17'):
            self.assertEqual(base[key],patched[key])
        self.assertEqual(base['8']['inputs']['model'],['1',0])
        self.assertEqual(patched['8']['inputs']['model'],['sparse_attention',0])
        self.assertEqual(patched['attention_backend']['inputs']['model'],['motion_repair',0])
        self.assertEqual(patched['motion_repair']['inputs']['model'],['motion_combat',0])
        for intensity,strength in [('normal',0.39),('high',0.65),('extreme',0.845)]:
            g=build_workflow(*args,director_mode='action',intensity=intensity)
            self.assertEqual(g['motion_combat']['inputs']['strength_model'],strength)
        self.assertNotIn('motion_combat',build_workflow(*args,director_mode='dance'))
        for accel,motion in ((False,True),(True,False),(False,False)):
            g=build_workflow(*args,acceleration=accel,motion_lora=motion)
            self.assertEqual('sparse_attention' in g,accel)
            self.assertEqual('motion_repair' in g,motion)

    def test_attention_switches_are_independent_and_keep_legacy_graphs(self):
        args=('ref.png','slice.wav',1280,736,362,'<Audio 1>',42)
        for kitchen in (False,True):
            for sparse in (False,True):
                graph=build_workflow(*args,kitchen_attention=kitchen,sparse_attention=sparse)
                self.assertEqual('attention_backend' in graph,kitchen)
                self.assertEqual('sparse_attention' in graph,sparse)
                upstream=['attention_backend',0] if kitchen else ['motion_repair',0]
                self.assertEqual(graph['8']['inputs']['model'],['sparse_attention',0] if sparse else upstream)
                if sparse:self.assertEqual(graph['sparse_attention']['inputs']['model'],upstream)
                baseline=build_workflow(*args)
                for key in ('7','12','13','14','15','motion_repair'):
                    self.assertEqual(graph[key],baseline[key])
        for legacy in (False,True):
            self.assertEqual(build_workflow(*args,acceleration=legacy),build_workflow(*args,kitchen_attention=legacy,sparse_attention=legacy))

    def test_full_song_timeline(self):
        for seconds in (180,300,299.37):
            for chunk in (10,15):
                plan=segments(seconds,chunk)
                self.assertEqual(sum(s['frames'] for s in plan),math.ceil(seconds*24))
                self.assertTrue(all(s['seconds']<=chunk for s in plan))
                self.assertTrue(all((s['model_frames']-5)%17==0 for s in plan))
        from banana_mv.song_context import segment_context
        first=dict(segments(180)[0],song_seconds=180,segment_count=12)
        last=dict(segments(180)[-1],song_seconds=180,segment_count=12)
        self.assertIn('NOT the song ending',segment_context(first))
        self.assertIn('complete the requested final resolution',segment_context(last))

    def test_full_minute(self):
        plan=segments(60)
        self.assertEqual([s['frames'] for s in plan],[360]*4)
        self.assertEqual([s['model_frames'] for s in plan],[362]*4)
        self.assertEqual([s['start'] for s in plan],[0,15,30,45])

    def test_59_seconds_and_fractional_tail(self):
        for sec in (59,22.3,16.01,15.01,5.152):
            with self.subTest(sec=sec):
                plan=segments(sec)
                self.assertEqual(sum(s['frames'] for s in plan),math.ceil(sec*24))
                self.assertTrue(all(s['model_frames']>=s['frames'] for s in plan))
                self.assertTrue(all((s['model_frames']-5)%17==0 for s in plan))
                self.assertTrue(all(a['start_frame']+a['frames']==b['start_frame'] for a,b in zip(plan,plan[1:])))

    def test_reject_invalid_duration(self):
        for sec in (0,-1,300.001,float('nan'),float('inf')):
            with self.assertRaises(ValueError):segments(sec)

    def test_dimensions(self):
        for aspect,target,native in [('16:9',(1280,720),(1280,736)),
                                     ('9:16',(720,1280),(736,1280)),
                                     ('4:5',(720,900),(736,928)),
                                     ('1:1',(720,720),(736,736))]:
            self.assertEqual(output_dimensions(aspect),target)
            self.assertEqual(dimensions(aspect),native)
            self.assertEqual(output_dimensions(aspect,target[0]),target)
        for width in (512,720,768,1024,1920,2560):
            with self.assertRaises(ValueError):dimensions('16:9',width)
        with self.assertRaises(ValueError):dimensions('9:16',1280)
        with self.assertRaises(ValueError):dimensions('20:3',1280)

    def test_graph_routes_audio_and_preserves_identity(self):
        w=build_workflow('ref.png','slice.wav',736,416,362,'<Audio 1>',42)
        self.assertEqual(w['7']['inputs']['audio_mode'],'lock_source')
        self.assertEqual(w['13']['inputs']['latent_image'],['7',1])
        self.assertEqual(w['15']['inputs']['audio'],['7',2])
        self.assertNotIn('first_frame',w['7']['inputs'])
        c=build_workflow('ref.png','slice.wav',736,416,362,'<Audio 1>',42,'tail.png')
        self.assertEqual(c['7']['inputs']['task_type'],'Hybrid')
        self.assertEqual(c['7']['inputs']['first_frame'],['17',0])
        self.assertEqual(c['7']['inputs']['ref_images.ref_image_0'],['5',0])
        # All wire references point to existing nodes.
        for n in c.values():
            for x in n['inputs'].values():
                if isinstance(x,list):self.assertIn(x[0],c)

    def test_fallback_reference_numbering(self):
        prompt=fallback_prompt('神社',True)
        self.assertIn('<Picture 1> is the exact first frame',prompt)
        self.assertIn('performer in <Picture 2>',prompt)
        self.assertIn('<Audio 1>: fully_copy',prompt)


class MultiReferenceTests(unittest.TestCase):
    def test_single_image_legacy_graph_is_identical(self):
        args=('slice.wav',736,416,362,'<Audio 1>',42)
        for tail in (None,'tail.png'):
            self.assertEqual(build_workflow('ref.png',*args,tail),
                             build_workflow(['ref.png'],*args,tail))

    def test_nine_references_keep_order_and_audio_connections(self):
        files=[f'image{i}.png' for i in range(9)]
        w=build_workflow(files,'slice.wav',736,416,362,'',42)
        refs=[w['7']['inputs'][f'ref_images.ref_image_{i}'] for i in range(9)]
        self.assertEqual([w[wire[0]]['inputs']['image'] for wire in refs],files)
        self.assertEqual(w['7']['inputs']['drive_audio'],['6',0])
        self.assertEqual(w['15']['inputs']['audio'],['7',2])

    def test_chain_reserves_picture_slot_without_dropping_references(self):
        files=[f'image{i}.png' for i in range(8)]
        w=build_workflow(files,'slice.wav',736,416,362,'',42,'tail.png')
        self.assertEqual(w['7']['inputs']['first_frame'],['17',0])
        self.assertEqual(w['17']['inputs']['image'],'tail.png')
        self.assertEqual(len([k for k in w['7']['inputs'] if k.startswith('ref_images.')]),8)
        with self.assertRaises(ValueError):
            build_workflow(files+['ninth.png'],'slice.wav',736,416,362,'',42,'tail.png')

    def test_uploaded_mentions_map_after_continuation_keyframe(self):
        req='@圖片1 唱歌，@圖片2 場景，@Image3 服裝'
        independent=fallback_prompt(req,image_count=3)
        chain=fallback_prompt(req,True,image_count=3)
        self.assertIn('<Picture 1> 唱歌，<Picture 2> 場景，<Picture 3> 服裝',independent)
        self.assertIn('<Picture 2> 唱歌，<Picture 3> 場景，<Picture 4> 服裝',chain)
        for continuation in (False,True):
            with self.assertRaises(ValueError):fallback_prompt('@圖片4',continuation,image_count=3)

    def test_bad_image_lists_rejected(self):
        for value in ([],[None],[''],['a']*10,{'image':'a'}):
            with self.assertRaises(ValueError):reference_images(value)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg required')
class MediaTests(unittest.TestCase):
    def test_exact_720p_landscape_and_portrait_crop_from_native_padding(self):
        with tempfile.TemporaryDirectory(prefix='banana-resolution-') as tmp:
            p=Path(tmp);song=p/'song.wav'
            command(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=duration=1','-ar','32000',song])
            for width,height,native_w,native_h in [(1280,720,1280,736),(720,1280,736,1280)]:
                raw=p/f'{width}_native.mp4';out=p/f'{width}_final.mp4'
                command(['ffmpeg','-y','-v','error','-f','lavfi','-i',f'color=c=navy:s={native_w}x{native_h}:r=24:d=1',
                         '-c:v','libx264','-threads','1',raw])
                assemble([raw],song,out,1.0,(width,height))
                v=next(s for s in probe(out)['streams'] if s['codec_type']=='video')
                self.assertEqual((v['width'],v['height']),(width,height))
                self.assertEqual(int(v['nb_frames']),24)
            with self.assertRaises(RuntimeError):
                assemble([raw],song,p/'invalid.mp4',1.0,(2560,1440))

    def test_real_media_padding_trimming_and_original_soundtrack(self):
        with tempfile.TemporaryDirectory(prefix='banana-test-') as tmp:
            p=Path(tmp)
            song=p/'song.wav'
            command(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=880:duration=1.25',
                     '-ar','32000','-ac','2',song])
            raw=p/'raw.mp4'
            command(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=s=128x96:r=24:d=2',
                     '-c:v','libx264','-threads','1','-pix_fmt','yuv420p',raw])
            audio_window(song,p/'window.wav',1.0,5.0)
            self.assertAlmostEqual(duration(p/'window.wav'),5.0,places=3)
            trim_video(raw,p/'a.mp4',24)
            trim_video(raw,p/'b.mp4',6)
            last_frame(p/'b.mp4',p/'tail.png')
            self.assertGreater((p/'tail.png').stat().st_size,0)
            assemble([p/'a.mp4',p/'b.mp4'],song,p/'final.mp4',1.25)
            info=probe(p/'final.mp4')
            vid=next(s for s in info['streams'] if s['codec_type']=='video')
            self.assertEqual(int(vid['nb_frames']),30)
            self.assertAlmostEqual(duration(p/'final.mp4'),1.25,places=2)
            # Verify the final track came from the original song rather than silent/generated clips.
            import array
            import subprocess
            decoded=subprocess.run(['ffmpeg','-v','error','-i',str(p/'final.mp4'),'-vn','-f','f32le',
                                    '-ac','1','-ar','32000','-'],capture_output=True,check=True).stdout
            samples=array.array('f');samples.frombytes(decoded)
            rms=(sum(x*x for x in samples)/len(samples))**.5
            self.assertGreater(rms,0.05)
            with self.assertRaises(RuntimeError):trim_video(raw,p/'too_long.mp4',100)


if __name__=='__main__':unittest.main()

