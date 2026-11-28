"""Routing and isolation regression tests for 35B's advisory library."""
import unittest

from banana_mv.director import MODES
from banana_mv.director_library import VERSION, MODE_LIBRARY, build_library, creative_prompt


class DirectorLibraryTests(unittest.TestCase):
    def test_all_specialties(self):
        self.assertEqual(set(MODES), set(MODE_LIBRARY))
        for mode in MODES:
            segment = {'index': 0, 'seconds': 10, 'director_plan': {'mode': mode, 'event': 'Current event'}}
            text, info = build_library({'director': 'auto'}, segment)
            self.assertEqual(info['mode'], mode)
            self.assertIn('selected specialty: ' + mode, text)
            self.assertIn('optional creative ingredients', text)
            self.assertLess(info['words'], 2200 if mode == 'dance' else 1000)

    def test_explicit_dance_without_adapters(self):
        segment = {'index': 0, 'seconds': 15, 'director_plan': {'mode': 'performance', 'event': 'Waacking dance duel'}}
        text, info = build_library({'director': 'dance'}, segment)
        self.assertEqual(info['mode'], 'dance')
        self.assertIn('Waacking', text)
        self.assertNotIn('ACTIVE DOWNSTREAM ADAPTERS', text)
        self.assertNotIn('Guitar phrase', text)

    def test_adapters_are_independent_and_zero_weight_is_off(self):
        req = {'director': 'dance', 'action_loras': {
            'dance': {'enabled': True, 'strength': .7},
            'beat_sync': {'enabled': True, 'strength': 1.0},
            'choreography': {'enabled': True, 'strength': 0},
        }}
        text, info = build_library(req, {'seconds': 15})
        self.assertEqual(info['active_loras'], ['dance', 'beat_sync'])
        self.assertIn('Beat-sync adapter is mounted', text)
        self.assertNotIn('Choreography adapter is mounted', text)
        self.assertIn('No new trigger words', text)

    def test_local_scope_and_rotation(self):
        req = {'director': 'auto', 'prompt': 'FUTURE_ONLY_SECRET'}
        seg = {'index': 0, 'director_plan': {'mode': 'dance', 'event': 'duet'}, 'seconds': 10}
        first, _ = build_library(req, seg)
        second, _ = build_library(req, dict(seg, index=1))
        self.assertNotEqual(first, second)
        self.assertNotIn('FUTURE_ONLY_SECRET', first)

    def test_natural_short_take_and_metadata(self):
        seg = {'index': 1, 'seconds': 3, 'director_plan': {'mode': 'story', 'event': 'quiet reaction'}}
        system = creative_prompt('OFFICIAL', {'intensity': 'normal', 'dynamic_cuts': False}, seg)
        self.assertTrue(system.startswith('OFFICIAL'))
        self.assertIn('Natural intensity', system)
        self.assertIn('Short interval', system)
        self.assertIn('disabled dynamic editing', system)
        self.assertEqual(seg['director_library']['version'], VERSION)

    def test_v2_example_routes_and_source(self):
        from banana_mv.director_examples import EXAMPLES, VERSION as EXAMPLE_VERSION
        self.assertEqual(set(EXAMPLES), set(MODES))
        for mode in MODES:
            segment = {'index': 0, 'seconds': 15, 'director_plan': {'mode': mode, 'event': 'Current event'}}
            prompt = creative_prompt('OFFICIAL', {'director': mode}, segment)
            self.assertEqual(segment['director_library']['example_version'], EXAMPLE_VERSION)
            self.assertEqual(segment['director_library']['example_mode'], mode)
            self.assertIn('NOT THE CURRENT COMMISSION', prompt)
            self.assertIn(EXAMPLES[mode]['body'], prompt)
            self.assertLess(segment['director_library']['example_words'], 500)
            if mode == 'dance':
                self.assertIn('knee-height 24mm', prompt)
                self.assertIn('completes the sweep', prompt)
            else:
                self.assertNotIn('knee-height 24mm', prompt)

    def test_35b_removes_short_example_but_9b_keeps_it(self):
        from banana_mv.director_shoot import _free_commission
        from banana_mv.shoot_plan import _auto_filming, AUTO_FILMING
        args = ({}, {'seconds': 15}, 'Current scene', {'S1': '<Picture 1>', 'S2': '<Picture 2>'}, {}, [])
        legacy = _free_commission(*args)
        creative = _free_commission(*args, creative35=True)
        self.assertIn('ONE-SHOT SHAPE', legacy)
        self.assertNotIn('ONE-SHOT SHAPE', creative)
        self.assertIn('Write only detailed_description:', creative)
        self.assertNotIn('Write native SIX H3 Ref2VA sections', creative)
        self.assertIn('Python assembles the other five H3 fields', creative)
        policy = 'POLICY_SENTINEL'
        ordered = _free_commission(*args, direction_policy=policy, creative35=True)
        self.assertLess(ordered.index(policy), ordered.index('Current scene'))
        self.assertLess(ordered.index('Current scene'), ordered.index('DELIVER THE FINISHED SHOTS'))
        self.assertEqual(_auto_filming({}), AUTO_FILMING)
        self.assertNotIn('Use only the shot details', _auto_filming({'director35': {}}))
        self.assertIn('fully developed creative decisions', _auto_filming({'director35': {}}))

    def test_dance_full_categories_not_rotating(self):
        from banana_mv.dance_library import DANCE_CATEGORIES, dance_prompt
        self.assertEqual(len(DANCE_CATEGORIES), 6)
        self.assertEqual(sum(map(len, DANCE_CATEGORIES.values())), 108)
        first = dance_prompt({'index': 0})
        second = dance_prompt({'index': 5})
        self.assertEqual(first, second)
        for category, entries in DANCE_CATEGORIES.items():
            self.assertIn(category, first)
            for name, _ in entries:
                self.assertIn(name + ': ', first)
        _, info = build_library({'director': 'dance'}, {'index': 2})
        self.assertEqual(info['dance_entries'], 108)

    def test_music_evidence_is_local_and_optional(self):
        from banana_mv.dance_library import audio_context
        self.assertEqual(audio_context({'seconds': 15}), '')
        text = audio_context({'seconds': 5, 'audio_evidence': {
            'relative_energy': 'medium',
            'pulse_estimate': {'bpm_estimate': 120, 'ambiguous_half_double_tempo': True},
            'music_structure': {'bpm': 120, 'beats_s': [0.5, 4.5, 99], 'downbeats_s': [0.5],
                                'sections': [{'start_s': 0, 'end_s': 5, 'predicted_label': 'verse'}]}}})
        self.assertIn('Predicted BPM: 120', text)
        self.assertIn('0.500, 4.500', text)
        self.assertNotIn('99.000', text)
        self.assertIn('half/double-tempo ambiguity', text)
        self.assertIn('not heard audio', text)

    def test_motif_memory_uses_previous_delivered_shots_only(self):
        from banana_mv.dance_library import dance_memory, dance_prompt
        p = 'detailed_description:\n[Shot 1] Cross-step and waacking. [Shot 2] At 00:04.000, Pivot toward <Picture 2>.\noverall_soundscape:\nPopping'
        memory = dance_memory([(0, p), (1, p), (3, 'detailed_description:\n[Shot 1] FUTURE_SECRET')], 2)
        self.assertIn(('Waacking', 2), memory['motifs'])
        self.assertNotIn(('Popping', 2), memory['motifs'])
        self.assertIn('Pivot toward [earlier reference]', memory['previous_last_shot'])
        self.assertNotIn('00:04.000', memory['previous_last_shot'])
        self.assertNotIn('FUTURE_SECRET', dance_prompt({'dance_memory': memory}))
        self.assertIn('not visual observation', dance_prompt({'dance_memory': memory}))
        self.assertEqual(dance_memory([(0, p)], 2)['previous_last_shot'], '')


    def test_shot_only_35b_assembles_native_without_extra_call(self):
        from banana_mv.director_shoot import write_director_shoot_prompt
        calls = []
        def rewrite(cfg, system, parts, _):
            calls.append((cfg, system, parts))
            return ('detailed_description:\n[Shot 1] <Subject 1> steps forward. '
                    '<Subject 2> watches.\n[Shot 2] At 00:02.500, '
                    '<Subject 2> turns toward the audience.')
        req = {'director': 'dance', 'srt_cues': [
            {'start': .25, 'end': 4.5, 'text': '[S1] example lyric'}]}
        seg = {'index': 0, 'start': 0, 'seconds': 5,
               'director_plan': {'mode': 'dance', 'event': 'Current scene'}}
        cfg = {'director35': {}, 'rewriter': {'thinking': True, 'temperature': .7}}
        output = write_director_shoot_prompt(
            cfg, req, seg, 'Current scene', '',
            {'S1': '<Picture 1>', 'S2': '<Picture 2>'}, {},
            [None, None], [], rewrite)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0]['rewriter']['thinking'])
        system = calls[0][1]
        task = calls[0][2][-1][1]
        self.assertIn('You are the cinematic MV director', system)
        self.assertIn('banana-dance-library-v3', system)
        self.assertIn('REFERENCE EXAMPLE', system)
        self.assertIn('knee-height 24mm', system)
        self.assertNotIn('350-500', system)
        self.assertNotIn('coffee shop', system)
        self.assertIn('Write only detailed_description:', task)
        for field in ('subject_definitions', 'summary', 'retention_analysis',
                      'detailed_description', 'overall_soundscape', 'non_diegetic_music'):
            self.assertIn(field + ':', output)
        self.assertIn('[Shot 2] At 00:02.500, <Subject 2> turns toward the audience.', output)
        self.assertIn('SRT CAST HINTS', output)
        self.assertIn('<Audio 1>: fully_copy', output)
        self.assertEqual(seg['prompt_profile']['draft_contract'], '35b-director-first-v1')

    def test_shot_only_35b_retry_and_legacy_contract(self):
        from banana_mv.director_shoot import write_director_shoot_prompt, DIRECTOR_SYSTEM
        for creative in (True, False):
            calls = []
            def rewrite(cfg, system, parts, _):
                calls.append((system, parts[-1][1]))
                if len(calls) == 1:
                    return 'Invalid reply'
                return 'detailed_description:\n[Shot 1] <Subject 1> steps forward.'
            req = {'director': 'dance'}
            seg = {'index': 0, 'start': 0, 'seconds': 5}
            cfg = {'rewriter': {'thinking': False}}
            if creative:
                cfg['director35'] = {}
            output = write_director_shoot_prompt(
                cfg, req, seg, 'Current scene', '',
                {'S1': '<Picture 1>', 'S2': '<Picture 2>'}, {},
                [None, None], [], rewrite)
            self.assertEqual(len(calls), 2)
            self.assertIn('[Shot 1] <Subject 1> steps forward.', output)
            if creative:
                self.assertIn('Reissue only detailed_description', calls[1][1])
            else:
                self.assertEqual(calls[0][0], DIRECTOR_SYSTEM)
                self.assertIn('Reissue the SIX H3 sections', calls[1][1])
                self.assertIn('ONE-SHOT SHAPE', calls[0][1])
                self.assertNotIn('draft_contract', seg['prompt_profile'])


    def test_clip_phase_uses_existing_source_ending_policy(self):
        from banana_mv.mv_scope import clip_ending, ending_contract
        from banana_mv.director_shoot import _clip_phase_note, _free_commission
        req = {'project_scope': 'full', 'ending_policy_version': 2, 'segment_seconds': 15}
        segments = [{'index': 0, 'start': 0, 'seconds': 15},
                    {'index': 1, 'start': 15, 'seconds': 15},
                    {'index': 2, 'start': 30, 'seconds': 2}]
        contract = ending_contract(req, 32, segments)
        for i, phase in enumerate(('CONTINUING', 'RESOLVING', 'TERMINAL_HOLD')):
            seg = dict(segments[i], song_seconds=32, segment_count=3,
                       direction_ending_contract=contract)
            info = clip_ending(req, seg)
            # Never dump the ending plan or its resolution into the commission.
            info['resolution'] = 'FUTURE_PLOT_SECRET'
            note = _clip_phase_note(info)
            self.assertIn('CLIP PHASE: ' + phase, note)
            self.assertNotIn('FUTURE_PLOT_SECRET', note)
            if i == 0:
                self.assertIn('not a story ending', note)
                self.assertIn('motivated local pause', note)
            for creative35 in (True, False):
                task = _free_commission(req, seg, 'CURRENT_EVENT_SENTINEL',
                    {'S1': '<Picture 1>', 'S2': '<Picture 2>'}, {}, [],
                    creative35=creative35, ending=info)
                self.assertEqual(task.count('CLIP PHASE:'), 1)
                self.assertIn(note, task)
                self.assertLess(task.index(note), task.index('CURRENT_EVENT_SENTINEL'))
                self.assertNotIn('FUTURE_PLOT_SECRET', task)

    def test_excerpt_last_clip_not_a_finale(self):
        from banana_mv.mv_scope import clip_ending
        from banana_mv.director_shoot import _clip_phase_note
        req = {'project_scope': 'excerpt', 'ending_policy_version': 2}
        seg = {'index': 1, 'start': 15, 'seconds': 15,
               'song_seconds': 30, 'segment_count': 2}
        self.assertIn('CLIP PHASE: EXCERPT', _clip_phase_note(clip_ending(req, seg)))
        self.assertEqual(_clip_phase_note(None), '')


if __name__ == '__main__':
    unittest.main()


class ValidatedExampleTests(unittest.TestCase):
    def test_style_picks_validated_martial_and_stage_variants(self):
        from banana_mv.director_examples import select_example
        self.assertIn('小小拳王', select_example('action', '拳擊擂台 uppercut')['source'])
        self.assertIn('大乘蕉宗住持', select_example('action', 'wing chun push hands')['source'])
        self.assertIn('大乘蕉宗住持', select_example('action', '')['source'])
        self.assertIn('最大功率', select_example('performance', 'cabaret rap entrance')['source'])
        # Latin keywords match whole words only.
        self.assertIn('illustrative', select_example('performance', 'dynamic chorus')['source'])
        self.assertIsNone(select_example('unknown', 'boxing'))
