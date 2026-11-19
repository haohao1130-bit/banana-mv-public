"""Camera choices belong to 9B. Python owns vocal permissions, not cuts."""
import unittest

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
        self.assertIn('SRT VOCAL WINDOWS', output)
        self.assertIn('6.868–8.360s: <Subject 1> (S1) ONLY', output)
        self.assertIn('8.360–8.848s: No assigned visible lip-sync', output)
        self.assertIn('8.848–10.000s: <Subject 1> (S1) ONLY', output)
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
        self.assertIn('SRT VOCAL WINDOWS', commission)
        self.assertIn('ONE-SHOT', commission)
