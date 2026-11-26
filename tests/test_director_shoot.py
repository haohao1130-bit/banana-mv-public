"""Camera choices belong to 9B. Python owns vocal permissions, not cuts."""
import unittest

from banana_mv.body_form import declared_body_forms
from banana_mv.director_shoot import (
    _free_commission, _safe_vocals, parse_director_shots,
    write_director_shoot_prompt,
)


def cue(start, end, *roles):
    return {'clip_start': start, 'clip_end': end, 'subjects': list(roles)}


class FreeDirectorShotsTests(unittest.TestCase):
    def setUp(self):
        self.cast = {'S1': '<Picture 2>', 'S2': '<Picture 3>'}
        self.fixed = 'S1 = <Picture 2>, male singer\nS2 = <Picture 3>, female singer'
        self.config = {'rewriter': {'temperature': .7, 'thinking': False}}

    def test_emotional_spoken_exchange_stays_two_shots_despite_five_vocal_windows(self):
        cues = [cue(0, 5.645, 'S2'), cue(6.868, 8.360, 'S1'),
                cue(8.848, 10, 'S1')]
        response = (
            'subject_definitions:\nKnown cast.\n'
            'summary:\nThe monk listens.\nretention_analysis:\nAudio fully copied.\n'
            'detailed_description:\n'
            '[Shot 1] A steady two-shot: her hurt expression changes '
            'as the monk silently lowers his wooden fish. Camera creeps forward.\n'
            '[Shot 2] At 00:05.645, Reverse angle to the monk alone. '
            'He is speaking the next line as the camera holds still; '
            'her eyes soften in the foreground. Keep this angle throughout '
            'both vocal entries and the instrumental breaths.\n'
            'overall_soundscape:\nInvented effects.\n'
            'non_diegetic_music:\nInvented new score.\n'
        )
        blocks, slots = parse_director_shots(response, 10, cues)
        self.assertEqual([s['start'] for s in slots], [0, 5.645])
        self.assertEqual(len(slots), 2)
        self.assertEqual(len(slots[1]['rows']), 4)
        blocks, audit = _safe_vocals(blocks, slots, self.fixed)
        self.assertEqual(audit, [])
        self.assertIn('He is speaking', blocks[2])
        self.assertIn('camera holds still', blocks[2])
        self.assertIn('instrumental breaths', blocks[2])
        writer_calls = []
        def writer(cfg, sys, parts, seed):
            writer_calls.append((sys, parts))
            return response
        req = {'srt_cues': [
            {'start': 0, 'end': 5.645, 'text': '[S2] 怨'},
            {'start': 6.868, 'end': 8.360, 'text': '[S1] 貧僧沒說妳不該恨'},
            {'start': 8.848, 'end': 10, 'text': '[S1] 只是想問'}],
            'rewrite_retries': 0, 'dynamic_cuts': True}
        segment = {'index': 9, 'start': 0, 'seconds': 10}
        output = write_director_shoot_prompt(
            self.config, req, segment,
            '白素貞受傷質問；和尚放下木魚，安靜回答。',
            self.fixed, self.cast, {}, ['tail', 'monk', 'snake'],
            [], writer,
        )
        self.assertEqual(len(writer_calls), 1)
        self.assertIn('SRT CAST HINTS', output)
        self.assertIn('6.868–8.360s: If showing lip-sync, use <Subject 1> (SRT S1)', output)
        self.assertIn('8.360–8.848s: No SRT cast hint', output)
        self.assertIn('8.848–10.000s: If showing lip-sync, use <Subject 1> (SRT S1)', output)
        self.assertEqual(output.count('[Shot '), 2)
        self.assertIn('[Shot 2] At 00:05.645', output)
        self.assertNotIn('At 00:06.868', output)
        self.assertNotIn('At 00:08.360', output)
        self.assertNotIn('Invented new score', output)
        self.assertIn('He is speaking', output)
        self.assertEqual(segment['prompt_profile']['director_shot_count'], 2)
        self.assertEqual(segment['prompt_profile']['source'], 'python_srt_free_camera')
        commission = writer_calls[0][1][-1][1]
        self.assertNotIn('LOCKED SHOT SLOTS', commission)
        self.assertIn('YOU CHOOSE SHOT COUNT', commission)

    def test_missing_cut_time_is_filled_at_the_midpoint_instead_of_rewriting(self):
        cues = [cue(0, 10, 'S1')]
        raw = ('detailed_description:\n[Shot 1] <Subject 1> sings.\n'
               '[Shot 2] <Subject 1> spins.\n[Shot 3] At 00:08.000, <Subject 1> bows.')
        blocks, slots = parse_director_shots(raw, 10, cues)
        self.assertEqual([slot['start'] for slot in slots], [0.0, 4.0, 8.0])
        self.assertEqual(blocks[2], '<Subject 1> spins.')

    def test_dash_separated_and_song_time_cuts_never_get_a_second_timestamp(self):
        cues = [cue(0, 10, 'S1')]
        raw = ('detailed_description:\n[Shot 1] <Subject 1> sings.\n'
               '[Shot 2] At 00:12.300 — <Subject 1> spins.\n[Shot 3] At 00:14.100 — <Subject 1> bows.')
        blocks, slots = parse_director_shots(raw, 10, cues, (), 10.0)   # 32b314ea7d8d 第 2 段
        self.assertEqual([slot['start'] for slot in slots], [0.0, 2.3, 4.1])
        self.assertEqual(blocks[2], '<Subject 1> spins.')
        bad = ('detailed_description:\n[Shot 1] <Subject 1> sings.\n'
               '[Shot 2] At 00:08.200 cut to <Subject 1>.\n[Shot 3] At 00:14.000 cut back.')
        with self.assertRaises(ValueError):   # 超出這段：退回重寫，不能均分再疊一組時間
            parse_director_shots(bad, 10, cues, (), 90.0)

    def test_free_camera_commission_carries_the_full_shared_setup(self):
        shared = ('@圖片1＝西索＝S1\n@圖片2＝庫洛洛＝S2\n'
                  '兩人的皮膚始終維持自然真人膚色；彩色光芒屬於外部光源與反射。')
        commission = _free_commission(
            {'intensity': 'high'}, {'seconds': 10}, 'S1 坐上椅子。',
            {'S1': '<Picture 1>', 'S2': '<Picture 2>'}, {}, [cue(1, 3, 'S1')], fixed=shared)
        self.assertIn('SHARED SETUP', commission)
        self.assertIn('彩色光芒屬於外部光源與反射', commission)
        self.assertNotIn('＝S1', commission)          # 跟精簡通告單一樣，給 9B 的版本拿掉角色代號
        self.assertNotIn('SHARED SETUP', _free_commission(
            {'intensity': 'high'}, {'seconds': 10}, 'S1 坐上椅子。',
            {'S1': '<Picture 1>', 'S2': '<Picture 2>'}, {}, [cue(1, 3, 'S1')]))

    def test_seconds_style_cut_times_are_accepted(self):
        # 251892bee152：9B 照官方範例寫 At 1.500s，三份稿都被當成「沒寫時間」退回。
        raw = ('detailed_description:\n[Shot 1] At 0.000s, wide.\n[Shot 2] At 1.500s, POV doors.\n'
               '[Shot 3] At 3.2 秒，overhead.\n[Shot 4] At 00:05.200, blanket.\n'
               '[Shot 5] At 7.5–8.8s: close.\n[Shot 6] At 18.8s, whip pan.')
        blocks, slots = parse_director_shots(raw, 10, [], (), 10.0)
        self.assertEqual([slot['start'] for slot in slots], [0.0, 1.5, 3.2, 5.2, 7.5, 8.8])
        self.assertEqual(blocks[2], 'POV doors.')
        self.assertEqual(blocks[5], 'close.')
        # 沒有 At 的「3 seconds later」不是切鏡時間，照舊用前後中點補。
        blocks, slots = parse_director_shots(
            'detailed_description:\n[Shot 1] wide.\n[Shot 2] 3 seconds later she turns.', 10, [], ())
        self.assertIn('3 seconds later', blocks[2])

    def test_millisecond_slot_cut_times_are_rejected(self):
        # 529e579d3225：9B 把 2.8 秒寫成 At 00:00.002，整串 0.002、0.005… 被放行送進 H3。
        raw = ('detailed_description:\n[Shot 1] wide.\n[Shot 2] At 00:00.002, overhead.\n'
               '[Shot 3] At 00:00.005, blanket.\n[Shot 4] At 00:00.008, wide.')
        with self.assertRaisesRegex(ValueError, 'At 00:02.800'):
            parse_director_shots(raw, 15, [], ())

    def test_odd_clock_spellings_read_as_seconds(self):
        raw = ('detailed_description:\n[Shot 1] wide.\n[Shot 2] At 00:00:02.800, hours form.\n'
               '[Shot 3] At 00:05:300, colon millis.\n[Shot 4] At 00:08,250, comma decimal.\n'
               '[Shot 5] At 00:11, she turns.')
        blocks, slots = parse_director_shots(raw, 15, [], ())
        self.assertEqual([slot['start'] for slot in slots], [0.0, 2.8, 5.3, 8.25, 11.0])
        self.assertEqual(blocks[3], 'colon millis.')
        self.assertEqual(blocks[5], 'she turns.')

    def test_rejected_drafts_leave_their_reason_on_the_clip(self):
        good = ('detailed_description:\n[Shot 1] <Subject 1> waits.\n'
                '[Shot 2] At 00:04.000 <Subject 2> answers.')
        bad = ('detailed_description:\n[Shot 1] <Subject 1> waits.\n'
               '[Shot 2] At 00:14.000 <Subject 2> answers.')
        replies = iter([bad, good])
        segment = {'index': 0, 'start': 0, 'seconds': 10}
        write_director_shoot_prompt(
            self.config, {'srt_cues': [], 'rewrite_retries': 0}, segment, '兩人對峙。',
            self.fixed, self.cast, {}, ['tail', 'monk', 'snake'], [], lambda *a: next(replies))
        self.assertEqual(len(segment['writer_rejections']), 1)
        self.assertEqual(segment['writer_rejections'][0]['kind'], 'format')
        self.assertIn('strictly increase', segment['writer_rejections'][0]['reason'])

    def test_free_camera_shared_setup_names_subjects_not_pictures(self):
        # 82d34b772bf0《大乘蕉宗住持》：共同設定的 <Picture N> 讓 9B 在鏡頭內文寫圖片編號，
        # 一直被退回局部修稿；接續段的 <Picture 1> 其實是上一段尾幀。
        shared = ('@圖片1＝蕉大師＝S1\n@圖片2＝小語＝S2\n'
                  '面對S2的攻勢，擅長從容架招。\n面對S1偷懶及狡辯，會翻白眼。')
        commission = _free_commission(
            {'intensity': 'high'}, {'seconds': 10}, 'S1 逃跑。',
            {'S1': '<Picture 2>', 'S2': '<Picture 3>'}, {}, [cue(1, 3, 'S2')], fixed=shared)
        setup = commission.split('=== 1.')[0]
        self.assertNotIn('<Picture', setup)
        self.assertNotIn('@圖片', setup)
        self.assertIn('蕉大師＝<Subject 1>', setup)
        self.assertIn('小語＝<Subject 2>', setup)
        self.assertIn('面對小語的攻勢', setup)       # 不能被刪成「面對的攻勢」
        self.assertIn('面對蕉大師偷懶', setup)

    def test_cross_srt_handoff_keeps_authorized_rap_and_singing_in_one_shot(self):
        cues = [cue(0, 4, 'S1'), cue(4.2, 10, 'S2')]
        raw = ('detailed_description:\n[Shot 1] <Subject 1> raps with visible '
               'jaw tension; the camera sweeps behind the snake as '
               '<Subject 2> sings and the water coils upward.')
        blocks, slots = parse_director_shots(raw, 10, cues)
        corrected, audit = _safe_vocals(blocks, slots, self.fixed)
        self.assertEqual(audit, [])
        self.assertIn('<Subject 1> raps', corrected[1])
        self.assertIn('<Subject 2> sings', corrected[1])
        self.assertIn('water coils upward', corrected[1])

    def test_first_9b_draft_uses_configured_temperature_and_director_policy(self):
        calls = []
        def writer(cfg, system, parts, seed):
            calls.append((cfg['rewriter']['temperature'], system, parts[-1][1]))
            return ('subject_definitions:\nKnown cast.\nsummary:\nCurrent scene.\n'
                    'retention_analysis:\nOriginal track.\ndetailed_description:\n'
                    '[Shot 1] <Subject 2> sings while gliding through rain and '
                    'the camera tracks her full snake body.\n'
                    'overall_soundscape:\nOriginal.\nnon_diegetic_music:\nOriginal.')
        req = {'srt_cues': [{'start': 0, 'end': 10, 'text': '[S2] 歌聲'}],
               'rewrite_retries': 0, 'dynamic_cuts': True}
        output = write_director_shoot_prompt(
            self.config, req, {'index': 0, 'start': 0, 'seconds': 10},
            '白素貞在雨中滑行。', self.fixed, self.cast, {}, ['tail', 'monk', 'snake'],
            [], writer, direction_policy='ADAPTATION: FREE. Dynamic editing is enabled.')
        self.assertEqual(calls[0][0], .7)
        self.assertIn('CREATIVE MV FILM DIRECTOR', calls[0][1])
        self.assertIn('ADAPTATION: FREE', calls[0][2])
        self.assertIn('Dynamic editing is enabled', calls[0][2])
        self.assertIn('full snake body', output)

    def test_v6_body_form_is_copied_to_commission_and_h3_identity(self):
        fixed = (
            '【共同設定】\n'
            '<Picture 1> = S1 = 蕉大師\n'
            '<Picture 2> = S2 = 白素貞\n'
            '■ S1 蕉大師\n成年男子，僧衣。\n'
            '■ S2 白素貞（形態固定，全片一致）\n'
            '修行千年的化形白蛇妖。上半身是人形女子。'
            '腰部以下是一整條連續的純白色蛇軀（白色鱗片，無下肢結構），'
            '一路細長收尾成蛇尾，是她身體的一部分，全片只有這一條。\n'
            '■ S2 的用詞表\n・滑行、貼地滑行\n'
            '【分段通告單】\nACT 01\n未來結局：舞台同台演唱。\n'
        )
        anatomy = declared_body_forms(fixed)
        self.assertEqual(set(anatomy), {'S2'})
        self.assertIn('腰部以下是一整條連續的純白色蛇軀', anatomy['S2'])
        self.assertIn('無下肢結構', anatomy['S2'])
        self.assertNotIn('舞台同台演唱', anatomy['S2'])
        commission = _free_commission(
            {'intensity': 'high'}, {'seconds': 10},
            '白素貞貼地滑行到古寺門口，昂首演唱。',
            {'S1': '<Picture 1>', 'S2': '<Picture 2>'}, {}, [cue(1, 3, 'S2')],
            body_form=anatomy)
        self.assertIn('BODY FORM / ANATOMY', commission)
        self.assertIn('無下肢結構', commission)
        self.assertNotIn('未來結局', commission)
        calls = []
        def writer(cfg, system, parts, job):
            calls.append(parts[-1][1])
            return ('subject_definitions:\nBoth actors.\nsummary:\nCurrent scene.\n'
                    'retention_analysis:\nOriginal music.\ndetailed_description:\n'
                    '[Shot 1] <Subject 2> glides on the wet temple steps, '
                    'snake scales catching the lightning.\n'
                    'overall_soundscape:\nOriginal.\nnon_diegetic_music:\nOriginal.')
        segment = {'index': 0, 'start': 0, 'seconds': 10}
        native = write_director_shoot_prompt(
            self.config,
            {'srt_cues': [{'start': 1, 'end': 3, 'text': '[S2] 憤怒'}],
             'rewrite_retries': 0},
            segment, '白素貞貼地滑行到古寺門口，昂首演唱。',
            fixed, {'S1': '<Picture 1>', 'S2': '<Picture 2>'},
            {}, ['monk', 'snake'], [], writer, body_form=anatomy)
        definitions = native.split('subject_definitions:\n', 1)[1].split('summary:', 1)[0]
        self.assertIn('BODY FORM / ANATOMY', definitions)
        self.assertIn('無下肢結構', definitions)
        self.assertIn('只有這一條', definitions)
        self.assertNotIn('舞台同台演唱', definitions)
        self.assertIn('BODY FORM', native.split('retention_analysis:\n')[1])
        self.assertIn('無下肢結構', calls[0])
        self.assertEqual(segment['body_form'], anatomy)
        self.assertIn('snake scales catching the lightning', native)

    def test_human_with_no_body_form_uses_existing_reference_defaults(self):
        fixed = 'S1 = <Picture 1>, adult singer\nS2 = <Picture 2>, adult singer'
        self.assertEqual(declared_body_forms(fixed), {})
        body = _free_commission(
            {'intensity': 'normal'}, {'seconds': 10}, '兩人演唱。',
            {'S1': '<Picture 1>', 'S2': '<Picture 2>'}, {}, [],
            body_form=declared_body_forms(fixed))
        self.assertNotIn('BODY FORM / ANATOMY', body)

    def test_one_take_is_valid_even_when_singer_changes(self):
        cues = [cue(0, 4, 'S2'), cue(4.5, 10, 'S1')]
        response = (
            'subject_definitions:\nKnown cast.\nsummary:\nScene.\n'
            'retention_analysis:\nAudio unchanged.\n'
            'detailed_description:\n'
            'One unbroken lateral tracking shot passes from the white snake '
            'to the monk, both naturally reacting to the music, without a camera cut.\n'
            'overall_soundscape:\nOriginal.\nnon_diegetic_music:\nOriginal.'
        )
        blocks, slots = parse_director_shots(response, 10, cues)
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]['start'], 0)
        self.assertEqual(slots[0]['end'], 10)
        self.assertIn('lateral tracking shot', blocks[1])

    def test_rapid_rap_can_choose_several_own_camera_cuts(self):
        cues = [cue(0, 10, 'S1')]
        response = (
            'detailed_description:\n'
            '[Shot 1] Monk raps into camera, aggressive low angle.\n'
            '[Shot 2] At 00:01.500, Aerial shot reveals flooded plaza.\n'
            '[Shot 3] At 00:03.800, A camera tracks the moving wooden fish.\n'
            '[Shot 4] At 00:06.200, Snake-side reverse angle watches waves collide.\n'
            '[Shot 5] At 00:08.700, A wide hero view resolves the physical duel.\n'
            'overall_soundscape:\nOriginal.'
        )
        blocks, slots = parse_director_shots(response, 10, cues)
        self.assertEqual(len(slots), 5)
        self.assertEqual([s['start'] for s in slots], [0, 1.5, 3.8, 6.2, 8.7])
        self.assertEqual([s['end'] for s in slots], [1.5, 3.8, 6.2, 8.7, 10])
        self.assertIn('aerial', blocks[2].lower())

    def test_unauthorized_singer_is_silenced_without_moving_the_camera(self):
        cues = [cue(0, 10, 'S2')]
        response = ('detailed_description:\n[Shot 1] <Subject 1> raps while '
                    'the camera pans left around the white snake.\n'
                    'overall_soundscape:\nOriginal.')
        blocks, slots = parse_director_shots(response, 10, cues)
        fixed, audit = _safe_vocals(blocks, slots, self.fixed)
        self.assertEqual(len(audit), 1)
        self.assertNotIn('raps', fixed[1])
        self.assertIn('camera pans left', fixed[1])

    def test_precise_scene_and_costume_transition_stays_authoritative(self):
        cues = [cue(0, 4, 'S1'), cue(4, 10, 'S2')]
        schedule = [
            {'start': 0, 'end': 9.26, 'scene': 'beach / shoreline',
             'wardrobe': {'S2': 'white bikini'}},
            {'start': 9.26, 'end': 10, 'scene': 'nighttime apartment',
             'wardrobe': {'S2': 'dry reference dress'}},
        ]
        wrong = ('detailed_description:\n'
                 '[Shot 1] They play in the water.\n'
                 '[Shot 2] At 00:06.000, Both leave the sea.')
        with self.assertRaisesRegex(ValueError, '9.260s'):
            parse_director_shots(wrong, 10, cues, schedule)
        right = ('detailed_description:\n'
                 '[Shot 1] They play in the water.\n'
                 '[Shot 2] At 00:09.260, Now in the apartment, already dry.')
        _, slots = parse_director_shots(right, 10, cues, schedule)
        self.assertEqual([s['start'] for s in slots], [0, 9.26])

    def test_current_event_not_future_plot_is_all_the_camera_model_gets(self):
        commission = _free_commission(
            {'intensity': 'high'}, {'seconds': 10},
            '白素貞正在質問，蕉大師只做無聲反應。',
            self.cast, {'S1': 'grey monk robe'},
            [cue(0, 10, 'S2')], True)
        self.assertIn('白素貞正在質問', commission)
        self.assertIn('CURRENT OUTFIT: grey monk robe', commission)
        self.assertIn('OPENING CONTINUITY', commission)
        self.assertNotIn('LOCKED SHOT SLOTS', commission)
        self.assertNotIn('final concert', commission)
        self.assertNotIn('future ending', commission)
        self.assertIn('SRT CAST HINTS', commission)
        self.assertIn('ONE-SHOT', commission)
