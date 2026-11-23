import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from banana_mv import room_switch


class RoomSwitchEnvironmentTests(unittest.TestCase):
    def test_clean_environment_drops_this_rooms_python_setup(self):
        env = room_switch.clean_environment({
            'PATH': r'F:\venv\Scripts;C:\Windows', 'VIRTUAL_ENV': r'F:\venv', 'PYTHONPATH': 'x',
            'BANANA_DATA': 'z', 'CONDA_PREFIX': 'c', 'SystemRoot': r'C:\Windows'})
        self.assertEqual(sorted(env), ['PATH', 'SystemRoot'])

    def test_switch_resets_path_and_passes_clean_environment(self):
        handler = SimpleNamespace(headers={'Origin': 'http://127.0.0.1:8193', 'Host': '127.0.0.1:8193',
                                           'X-Banana-Control': '5070-room-switch'},
                                  send_json=Mock(), server=SimpleNamespace(shutdown=Mock()))
        backend = SimpleNamespace(PORT=8193, comfy=Mock(return_value={'queue_running': [], 'queue_pending': []}),
                                  load_config=Mock(return_value={}))
        lock = MagicMock(); lock.acquire.return_value = True
        with patch.object(room_switch, 'launcher', return_value=Path('/tmp/Bootstrap.ps1')), \
             patch.dict(room_switch.os.environ, {'VIRTUAL_ENV': r'F:\mv-venv', 'BANANA_DATA': 'x'}), \
             patch.object(room_switch.subprocess, 'Popen') as spawn, \
             patch.object(room_switch.subprocess, 'CREATE_NEW_CONSOLE', 16, create=True):
            room_switch.switch(handler, 'film', backend, lock)
        args, kwargs = spawn.call_args
        command = args[0][args[0].index('-Command') + 1]
        self.assertTrue(command.startswith("$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine')"))
        self.assertNotIn('VIRTUAL_ENV', kwargs['env'])
        self.assertNotIn('BANANA_DATA', kwargs['env'])


if __name__ == '__main__':
    unittest.main()
