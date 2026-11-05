import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from banana_mv.core import command, duration, segments, source_audio_duration
from banana_mv.audio_analysis import analyze_audio, segment_evidence


class AudioTimingTests(unittest.TestCase):
    def test_mp3_container_padding_does_not_create_a_phantom_fifth_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp)/'minute.mp3'
            command(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=60',
                     '-c:a','libmp3lame',song])
            measured=source_audio_duration(song)
            # Newer FFmpeg reports gapless MP3 duration exactly; older versions include padding.
            self.assertGreaterEqual(duration(song),60)
            with patch('banana_mv.core.duration',return_value=60.04):
                self.assertEqual(len(segments(source_audio_duration(song),15)),4)
            self.assertAlmostEqual(measured,60,places=3)
            plan=segments(measured,15)
            self.assertEqual(len(plan),4)
            analysis=analyze_audio(song)
            self.assertAlmostEqual(analysis['seconds'],measured,places=3)
            for seg in plan:
                self.assertTrue(segment_evidence(analysis,seg))

    def test_genuine_short_audio_tail_is_preserved_and_legacy_padding_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=Path(tmp)/'real_tail.wav'
            command(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=60.04',song])
            actual=source_audio_duration(song)
            self.assertAlmostEqual(actual,60.04,places=3)
            plan=segments(actual,15)
            self.assertEqual(len(plan),5) # Real audio, not metadata padding: do not discard it.
            analysis=analyze_audio(song)
            self.assertNotEqual(segment_evidence(analysis,plan[-1])['relative_energy'],'unmeasured')
            legacy=dict(analysis,seconds=60,energy_dbfs=analysis['energy_dbfs'][:2400])
            evidence=segment_evidence(legacy,plan[-1])
            self.assertEqual(evidence['relative_energy'],'unmeasured')
            self.assertEqual(evidence['transient_candidates_s'],[])
            with self.assertRaisesRegex(ValueError,'時間不一致'):
                segment_evidence(legacy,{'start':61,'seconds':1})

    def test_unstarted_legacy_project_is_retimed_without_deleting_its_unused_plan(self):
        from banana_mv import server
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job_id='abcdef123456';work=root/job_id;work.mkdir()
            job={'id':job_id,'duration':60.04,'request':{'segment_seconds':15},'segments':segments(60.04,15),
                 'director_plan':{'status':'ready'}}
            saved=work/'director_plan.json';saved.write_text('old-plan-kept')
            with patch.object(server,'RUNS',root),patch.object(server,'source_audio_duration',return_value=60) as decode:
                server.repair_unstarted_timeline(job,root/'song.mp3')
                self.assertEqual(len(job['segments']),4)
                self.assertEqual(job['duration'],60)
                self.assertEqual(job['segments'][-1]['song_seconds'],60)
                self.assertNotIn('director_plan',job)
                self.assertEqual(next(work.glob('director_plan_before_timing_fix_*.json')).read_text(),'old-plan-kept')
                server.repair_unstarted_timeline(job,root/'song.mp3')
                self.assertEqual(decode.call_count,1)

    def test_started_projects_are_not_silently_retimed(self):
        from banana_mv import server
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job_id='abcdef123456';work=root/job_id;work.mkdir()
            job={'id':job_id,'duration':60.04,'request':{'segment_seconds':15},'segments':segments(60.04,15)}
            for marker in ('done','prompt_id','file'):
                previous=copy.deepcopy(job)
                if marker=='done':job['segments'][0]['status']='done'
                elif marker=='prompt_id':job['segments'][0]['prompt_id']='submitted'
                else:(work/'00_prompt.txt').write_text('existing-prompt')
                snapshot=copy.deepcopy(job)
                with patch.object(server,'RUNS',root),patch.object(server,'source_audio_duration',side_effect=AssertionError('must preserve')):
                    server.repair_unstarted_timeline(job,root/'song.mp3')
                self.assertEqual(job,snapshot)
                job=previous
