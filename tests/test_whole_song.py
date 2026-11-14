"""Exercise whole-MV planning, review and H3 handoff without a GPU."""
from contextlib import ExitStack
import json
from unittest import TestCase, mock

from banana_mv import server, whole_song
from banana_mv.core import segments
import test_plan_review


class WholeSongTests(TestCase):
    setUp = test_plan_review.PlanReviewTests.setUp
    plan = test_plan_review.PlanReviewTests.plan

    def test_single_call_from_audio_through_review_to_h3(self):
        self.job['request'].update(
            director_schema=whole_song.VERSION, audio_analysis=False, preview_zh=True,
            prompt='終於帶我來玩水了，@圖片1 是小語',
            lyrics='', srt_cues=[{'start': 2, 'end': 4, 'text': '歌曲參考'}],
        )
        self.job['segments'] = segments(9, 4)
        for segment in self.job['segments']:
            segment.update(song_seconds=9, segment_count=3)
        self.model.return_value = {
            'setup': '夏日寫實，<Picture 1> 是小語。',
            'shots': [
                {'at': 0, 'mode': 'story', 'visual': '小語入園'},
                {'at': 3, 'mode': 'comedy', 'visual': '滑水出發',
                 'continuation': '延續滑行，落水後笑出聲'},
                {'at': 6, 'mode': 'story', 'visual': '夕陽下揮手',
                 },
            ],
        }
        analysis = mock.Mock(return_value={'pulse': None})
        evidence = {'transient_candidates_s': [1.25]}
        with mock.patch.object(server, 'load_analysis', analysis), mock.patch.object(
            server, 'segment_evidence', return_value=evidence
        ):
            self.plan()
        analysis.assert_called_once()
        self.model.assert_called_once()
        task = json.loads(self.model.call_args.args[2][0][1])
        self.assertIn('終於帶我來玩水了', task['brief'])
        self.assertNotIn('clip_windows', task)
        self.assertEqual(task['music']['transient_candidates_s'], [1.25, 5.25])
        self.assertEqual(task['srt'][0]['start'], 2)

        saved = server.read_state(self.job['id'])
        with mock.patch.object(server.threading, 'Thread'):
            approved = server.open_furnace(self.job['id'], saved['plan_revision'])
        with ExitStack() as stack:
            for obj, name, value in [
                (server, 'valid_part', lambda p, *_: p.is_file()),
                (server, 'audio_window', lambda src, dest, *_: dest.write_bytes(b'audio')),
                (server, 'wait_generation', mock.Mock(return_value={})),
                (server, 'video_info', mock.Mock(return_value={})),
                (server.backend, 'comfy_download', lambda c, i, d: d.write_bytes(b'raw')),
                (server, 'trim_video', lambda s, d, *_, **kw: d.write_bytes(b'part')),
                (server, 'assemble', lambda p, s, d, *_: d.write_bytes(b'final')),
                (server, 'export_finished_video', mock.Mock()),
            ]:
                stack.enter_context(mock.patch.object(obj, name, value))
            server.worker(approved, self.cfg, self.images, self.root/'song.wav', self.root/'song.wav')
        self.assertEqual(approved['status'], 'done', approved.get('error'))
        self.model.assert_called_once()
        prompts = [call.args[1]['7']['inputs']['prompt'] for call in self.queue.call_args_list]
        self.assertEqual(len(prompts), 3)
        self.assertIn('At 00:03.000, 滑水出發', prompts[0])
        self.assertNotIn('夕陽下揮手', prompts[0])
        self.assertIn('延續滑行', prompts[1])
        self.assertNotIn('滑水出發', prompts[1])
        self.assertIn('Continue this shot already in progress.', prompts[2])
        self.assertIn('夕陽下揮手', prompts[2])

    def test_manual_bracketed_common_settings_apply_to_each_workflow_once(self):
        req = self.job['request']
        req.update(
            director_schema=whole_song.DIRECT_SCRIPT, direct_script=True,
            rewrite=False, story_plan=False, dynamic_cuts=False, plan_review=True,
            prompt=("【參考圖】\n@圖片1 是快遞員。\n@圖片2 是機車。\n"
                    "【59秒連續劇情與攝影機運動】\n【00:00–00:04｜最後一單！】\n快遞員開車。\n"
                    "【00:04–00:08.00｜抵達！】\n快遞員抵達。\n"
                    "【最終畫面原則】\nFPV 一鏡到底。"),
        )
        self.job['segments'] = segments(8, 4)
        self.plan()
        self.model.assert_not_called()
        for i, segment in enumerate(self.job['segments']):
            self.assertIn('FPV 一鏡到底。', segment['fixed_reference_settings'])
            self.assertNotIn('FPV 一鏡到底。', segment['director_plan']['event'])
            prompt = server.local_prompt(self.cfg, req, segment, ['actor.png', 'bike.png'], bool(i))
            self.assertEqual(prompt.count('FPV 一鏡到底。'), 1)
            self.assertIn(f'<Picture {i+1}> 是快遞員。', prompt)
            self.assertIn(f'<Picture {i+2}> 是機車。', prompt)
            self.assertNotIn('Singing shots use', prompt)
        self.assertIn('FPV 一鏡到底。', self.job['plan_preview_setup'])

    def test_manual_timeline_clips_crossing_cue_on_local_clock(self):
        req = self.job['request']
        req.update(
            director_schema=whole_song.DIRECT_SCRIPT, direct_script=True,
            rewrite=False, story_plan=False, dynamic_cuts=False, plan_review=True,
            prompt=("【00:00.00–00:06.98】\n攝影機沿車輪往前。\n"
                    "【00:06.98–00:13.00】\n機車繼續沿道路前進。\n"
                    "鏡頭倒飛進入市場。\n"),
        )
        self.job['segments'] = segments(13, 10)
        self.plan()
        first, second = self.job['segments']
        first_prompt = server.local_prompt(self.cfg, req, first, self.images, None)
        second_prompt = server.local_prompt(self.cfg, req, second, self.images, True)
        self.assertEqual(first_prompt.count('[Shot '), 1)
        self.assertIn('每個時間碼是目前鏡頭裡的動作提示', first_prompt)
        self.assertIn('6.980–10.000 秒\n機車繼續沿道路前進。', first_prompt)
        self.assertIn('0.000–3.000 秒\n鏡頭倒飛進入市場。', second_prompt)
        self.assertIn('[Shot 1] <Picture 1> 是上一段交接的起始畫面。', second_prompt)
        self.assertIn('攝影機倒飛時，載具仍照原稿沿自己的路線行駛。', second_prompt)
        self.assertNotIn('Phase inside chapter', first_prompt)
        self.assertNotIn('鏡頭倒飛進入市場。', first_prompt)
        self.model.assert_not_called()

    def test_manual_draft_slices_authored_times_without_9b(self):
        self.job['request'].update(
            director_schema=whole_song.DIRECT_SCRIPT, direct_script=True,
            rewrite=False, story_plan=False, audio_analysis=False, preview_zh=True,
            prompt=("01｜角色設定\n小語是 @圖片1。\n"
                    "CHAPTER 01｜00:00–00:08\n入園與戲水\n"
                    "00:00–00:04\n小語推開園門。\n"
                    "00:04–00:08\n小語滑入水池。\n"
                    "SEGMENT 02｜00:08–00:09\n道別\n"
                    "00:08–00:09\n小語向售票員揮手。\n"
                    "05｜剪輯設定\n維持原曲。\n最後畫面停留在笑容。"),
        )
        self.job['segments'] = segments(9, 4)
        self.plan()
        self.model.assert_not_called()
        opening, middle, ending = self.job['segments']
        prompt = server.local_prompt(self.cfg, self.job['request'], middle, self.images, True)
        self.assertIn('<Picture 2>', prompt)
        self.assertIn('小語滑入水池。', prompt)
        self.assertNotIn('小語向售票員揮手。', prompt)
        self.assertNotIn('小語滑入水池。', opening['director_plan']['event'])
        self.assertIn('小語向售票員揮手。', ending['director_plan']['event'])
        self.assertIn('最後畫面停留在笑容。', ending['director_plan']['event'])
        self.assertNotIn('最後畫面', self.job['plan_preview_setup'])
        self.assertIn('維持原曲。', self.job['plan_preview_setup'])
        self.model.assert_not_called()
