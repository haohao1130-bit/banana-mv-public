"""5070-only supervisor API safety contract; no process termination in HTTP."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from banana_mv import server


class Browser:
    headers = {
        'X-Banana-Control': '5070-restart',
        'Content-Type': 'application/json',
        'Origin': 'https://desktop.example.ts.net',
        'Host': 'desktop.example.ts.net',
        'Sec-Fetch-Site': 'same-origin',
    }


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        self.restart = home / 'restart-request.json'
        self.heartbeat = home / 'restart-controller.heartbeat'
        self.heartbeat.write_text('alive', encoding='utf-8')
        patches = (
            patch.object(server, 'RESTART_REQUEST', self.restart),
            patch.object(server, 'RESTART_HEARTBEAT', self.heartbeat),
            patch.object(server.backend, 'PORT', 8193),
            patch.dict(os.environ, {'BANANA_SUPERVISED_RESTART': '1'}),
            patch.object(server.backend, 'load_config', return_value={'comfy_url':'test'}),
            patch.object(server.backend, 'comfy', return_value={'queue_running': [], 'queue_pending': []}),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_accepts_only_supervised_idle_confirmed_request(self):
        self.assertTrue(server.restart_capability()['available'])
        result = server.request_desktop_restart(Browser(), {'confirm':'restart-5070'})
        self.assertTrue(result['ok'])
        self.assertTrue(self.restart.is_file())
        with self.assertRaisesRegex(ValueError, '已送出'):
            server.request_desktop_restart(Browser(), {'confirm':'restart-5070'})

    def test_offline_supervisor_disables_button_and_request(self):
        self.heartbeat.unlink()
        self.assertFalse(server.restart_capability()['available'])
        with self.assertRaises(ValueError):
            server.request_desktop_restart(Browser(), {'confirm':'restart-5070'})

    def test_running_mv_refuses_to_restart(self):
        with server.GPU_LOCK:
            self.assertTrue(server.restart_capability()['busy'])
            with self.assertRaises(ValueError):
                server.request_desktop_restart(Browser(), {'confirm':'restart-5070'})
        self.assertFalse(self.restart.exists())

    def test_comfy_queued_work_refuses_to_restart(self):
        with patch.object(server.backend, 'comfy',
                          return_value={'queue_running': [1], 'queue_pending': []}):
            with self.assertRaisesRegex(ValueError, '工作'):
                server.request_desktop_restart(Browser(), {'confirm':'restart-5070'})
        self.assertFalse(self.restart.exists())

    def test_cross_origin_and_missing_headers_refuse_to_restart(self):
        for overrides in (
            {'Origin': 'https://evil.example'},
            {'Sec-Fetch-Site': 'cross-site'},
            {'X-Banana-Control': ''},
            {'Content-Type': 'text/plain'},
        ):
            class Attempt:
                headers = dict(Browser.headers, **overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                server.request_desktop_restart(Attempt(), {'confirm':'restart-5070'})
        self.assertFalse(self.restart.exists())

    def test_refuses_if_not_explicitly_enabled_by_5070_launcher(self):
        with patch.dict(os.environ, {'BANANA_SUPERVISED_RESTART': '0'}):
            self.assertFalse(server.restart_capability()['available'])
            with self.assertRaises(ValueError):
                server.request_desktop_restart(Browser(), {'confirm':'restart-5070'})


if __name__ == '__main__':
    unittest.main()
