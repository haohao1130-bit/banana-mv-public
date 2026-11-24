import unittest

from banana_mv.live_progress import LiveProgress


class LiveSpeedTests(unittest.TestCase):
    def progress(self, live, value, maximum=8):
        live.receive({'type': 'progress', 'data': {'prompt_id': 'p', 'node': '9', 'value': value, 'max': maximum}})

    def test_seconds_per_step_from_first_report(self):
        times = iter([100.0, 120.0, 141.0])
        live = LiveProgress(clock=lambda: next(times))
        live._connection = 'connected'
        live.queued('job', 'p', {'9': {'class_type': 'SamplerCustomAdvanced'}})
        live.receive({'type': 'execution_start', 'data': {'prompt_id': 'p'}})
        self.progress(live, 1)
        self.assertNotIn('done', live.snapshot('job'))          # one report: no speed yet
        self.progress(live, 2)
        self.progress(live, 3)
        info = live.snapshot('job')
        self.assertEqual((info['value'], info['done'], info['elapsed']), (3, 2, 41.0))
        self.assertEqual(info['node'], 'SamplerCustomAdvanced')

    def test_new_node_restarts_timing(self):
        times = iter([0.0, 10.0, 50.0, 51.0])
        live = LiveProgress(clock=lambda: next(times))
        live._connection = 'connected'
        live.queued('job', 'p', {'9': {'class_type': 'TextGenerate'}, '10': {'class_type': 'SamplerCustomAdvanced'}})
        live.receive({'type': 'execution_start', 'data': {'prompt_id': 'p'}})
        self.progress(live, 100, 2000)
        self.progress(live, 1300, 2000)
        live.receive({'type': 'progress', 'data': {'prompt_id': 'p', 'node': '10', 'value': 1, 'max': 8}})
        info = live.snapshot('job')
        self.assertNotIn('done', info)
        self.assertEqual(info['node'], 'SamplerCustomAdvanced')
