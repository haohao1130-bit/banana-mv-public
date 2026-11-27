import unittest

from banana_mv.fire_monitor import FireWatch
from banana_mv.live_progress import LiveProgress


class FireWatchTests(unittest.TestCase):
    def test_stall_requires_continuous_low_power_and_no_progress(self):
        watch = FireWatch()
        low = {'gpu_percent': 100, 'power_w': 51}
        stage = (('prompt', 'tlu_sample', 1), 0, '精煉')
        for t in range(0, 90, 3):
            self.assertFalse(watch.check(low, stage, t))
        self.assertTrue(watch.check(low, stage, 90))
        self.assertFalse(watch.check(low, (('prompt', 'tlu_sample', 2), 93, '精煉'), 93))
        self.assertFalse(watch.check(low, None, 96))

    def test_healthy_or_missing_or_gapped_samples_reset_warning(self):
        watch = FireWatch()
        low = {'gpu_percent': 100, 'power_w': 51}
        stage = (('prompt', '13', 1), 0, '母丹')
        for t in range(0, 90, 3):
            watch.check(low, stage, t)
        self.assertFalse(watch.check(low, stage, 100))
        self.assertFalse(watch.check({'gpu_percent': 100, 'power_w': 220}, stage, 103))
        self.assertFalse(watch.check({'gpu_percent': 100, 'power_w': None}, stage, 106))
        self.assertFalse(watch.check({'gpu_percent': 2, 'power_w': 30}, stage, 109))

    def test_live_progress_sampler_only_and_clear(self):
        live = LiveProgress(clock=lambda: 10)
        live.queued('job', 'p', {'13': {'class_type': 'SamplerCustomAdvanced'},
                               'tlu_sample': {'class_type': 'SamplerCustomAdvanced'},
                               '14': {'class_type': 'VAEDecode'}})
        live._set_connection('connected')
        def emit(event, **data):
            live.receive({'type': event, 'data': dict(data, prompt_id='p')})
        emit('execution_start')
        emit('executing', node='tlu_sample')
        self.assertIsNone(live.sampling_state())
        emit('progress', node='tlu_sample', value=1, max=5)
        self.assertEqual(live.sampling_state(), (('p', 'tlu_sample', 1), 10, '精煉｜退果凍'))
        emit('progress', node='tlu_sample', value=5, max=5)
        self.assertIsNone(live.sampling_state())
        emit('executing', node='14')
        self.assertIsNone(live.sampling_state())
        live.clear('job')
        self.assertIsNone(live.sampling_state())


if __name__ == '__main__':
    unittest.main()
