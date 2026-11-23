import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from banana_mv import server
from banana_mv.core import dimensions, output_dimensions


class DraftModeTests(unittest.TestCase):
    def test_360p_draft_sizes_are_padded_to_32(self):
        self.assertEqual(output_dimensions('16:9', 640), (640, 360))
        self.assertEqual(dimensions('16:9', 640), (640, 384))
        self.assertEqual(output_dimensions('9:16', 360), (360, 640))
        self.assertEqual(output_dimensions('16:9', 1280), (1280, 720))

    def write_draft(self, root, status='done'):
        job_id = 'abcdef123456'
        work = root / job_id
        work.mkdir()
        segments = [{'index': 0}, {'index': 1, 'prompt': 'from state'}]
        (work / '00_prompt_v1.txt').write_text('draft prompt one', encoding='utf-8')
        state = {'id': job_id, 'status': status, 'title': '小小拳王', 'segments': segments,
                 'request': {'aspect': '16:9', 'width': 640, 'sampling_steps': 4, 'mode': 'chain5',
                             'director_schema': 6, 'rewrite_retries': 2}}
        (work / 'status.json').write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        return job_id

    def test_draft_prompt_reads_saved_file_then_state(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'RUNS', Path(tmp)), \
                patch('banana_mv.core.normalize_mv_prompt', side_effect=lambda text, count: text):
            job_id = self.write_draft(Path(tmp))
            self.assertEqual(server.draft_prompt(job_id, 0, 3), 'draft prompt one')
            self.assertEqual(server.draft_prompt(job_id, 1, 3), 'from state')
            with self.assertRaises(ValueError):
                server.draft_prompt(job_id, 2, 3)

    def test_promote_starts_720p_eight_steps_with_source(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'RUNS', Path(tmp)), \
                patch.object(server, 'start', side_effect=lambda req: req) as start:
            job_id = self.write_draft(Path(tmp))
            req = server.promote_draft(job_id)
            self.assertEqual((req['width'], req['sampling_steps'], req['prompt_source_job']), (1280, 8, job_id))
            self.assertNotIn('director_schema', req)
            self.assertTrue(req['project_name'].endswith('正式版'))
            start.assert_called_once()

    def test_promote_refuses_running_draft(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'RUNS', Path(tmp)):
            job_id = self.write_draft(Path(tmp), status='running')
            with self.assertRaises(ValueError):
                server.promote_draft(job_id)
