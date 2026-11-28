"""Generic 35B route regression: no dependency on the dual-singer case."""
import unittest
from unittest.mock import Mock, patch

from banana_mv.director_draft import SYSTEM, VERSION, assemble
from banana_mv.shoot_plan import write_shoot_prompt


class GenericDirectorTests(unittest.TestCase):
    def test_assembly_preserves_arbitrary_cast_and_original_support(self):
        definitions = '\n'.join(f'<Subject {n}> is Dancer{n} from <Picture {n}>.' for n in range(1, 6))
        definitions += '\n<Subject 6> is the original drummer, wearing a green jacket.'
        body = '[Shot 1] <Subject 5> leads the formation; <Subject 6> strikes the drum.'
        output = assemble('subject_definitions:\n' + definitions + '\ndetailed_description:\n' + body)
        self.assertIn(definitions, output)
        self.assertIn(body, output)
        self.assertIn('<Subject 5>: partially_preserved', output)
        self.assertNotIn('<Picture 6>', output)
        self.assertEqual(output.count('overall_soundscape:'), 1)
        self.assertIn('<Audio 1>: fully_copy', output)

    def test_no_named_subjects_and_boundary_frame(self):
        raw = 'subject_definitions:\n\ndetailed_description:\n[Shot 1] Rain ripples across the empty courtyard.'
        result = assemble(raw, continuation=True)
        self.assertIn('<Picture 1> is the preceding frame', result)
        self.assertNotIn('<Subject 1>', result)
        self.assertIn('Rain ripples', result)

    def test_native_reply_compatibility_and_no_audio_invention(self):
        raw = ('subject_definitions:\n<Subject 1> is a dancer from <Picture 1>.\n'
               '<Audio 2> is new music.\nsummary:\nOld summary.\n'
               'retention_analysis:\nOld retention.\ndetailed_description:\n'
               '[Shot 1] The dancer turns.\noverall_soundscape:\nCrowd noise.\n'
               'non_diegetic_music:\nNew song.')
        result = assemble(raw)
        self.assertIn('[Shot 1] The dancer turns.', result)
        for bad in ('<Audio 2>', 'Crowd noise.', 'New song.', 'Old summary.'):
            self.assertNotIn(bad, result)

    def test_general_and_lean_cast_sizes_and_vocal_assignments(self):
        for count, tagged in ((1, False), (3, True), (5, True), (5, False)):
            for lean in (False, True):
                with self.subTest(count=count, tagged=tagged, lean=lean):
                    fixed = '\n'.join(f'<Picture {n}> = Dancer{n} = S{n}' for n in range(1, count+1))
                    req = {'director_schema': 6, 'director': 'dance',
                           'project_scope': 'full', 'ending_policy_version': 2,
                           'segment_seconds': 15, 'lean_commission': lean,
                           'shared_setup': fixed, 'rewrite_retries': 0,
                           'srt_cues': ([{'start': .25, 'end': 14.5,
                                         'text': f'[S1+S{count}] reference lyric'}] if tagged else [])}
                    seg = {'index': 0, 'start': 0, 'seconds': 15,
                           'song_seconds': 45, 'segment_count': 3,
                           'director_plan': {'handoff_version': 1, 'mode': 'dance',
                                             'event': 'The dancers exchange positions.'},
                           'fixed_reference_settings': fixed}
                    definitions = '\n'.join(f'<Subject {n}> is Dancer{n} from <Picture {n}>.' for n in range(1, count+1))
                    raw = 'subject_definitions:\n' + definitions + '\ndetailed_description:\n[Shot 1] The dancers exchange positions.'
                    if lean:
                        raw += '\nEND_STATE:\npose: Dancer1 faces forward\nmotion: traveling right\ncamera: static\nmood: confident'
                    writer = Mock(return_value=raw)
                    cfg = {'director35': {}, 'rewriter': {'thinking': True}}
                    with patch('banana_mv.shoot_plan._pictures', side_effect=lambda refs: [
                            item for n, ref in enumerate(refs, 1) for item in
                            [('text', f'<Picture {n}>:'), ('image', ref)]]):
                        output = write_shoot_prompt(cfg, req, seg, list(range(count)), None, writer)
                    self.assertEqual(writer.call_count, 1)
                    system = writer.call_args.args[1]
                    task = writer.call_args.args[2][-1][1]
                    self.assertIn('banana-dance-library-v3', system)
                    self.assertNotIn('Full-Reference Mode Rewrite Output Format Guide', system)
                    self.assertIn('CLIP PHASE: CONTINUING', task)
                    self.assertIn('The dancers exchange positions.', output)
                    self.assertIn(f'<Subject {count}> is Dancer{count}', output)
                    self.assertEqual(seg['prompt_profile']['draft_contract'], VERSION)
                    if tagged:
                        self.assertIn(f'S{count} = <Picture {count}>', task)
                        self.assertIn(f'<Picture {count}>', output)
                    if lean:
                        self.assertNotIn('END_STATE:', output)
                        self.assertIn('traveling right', seg['end_state'])


if __name__ == '__main__':
    unittest.main()
