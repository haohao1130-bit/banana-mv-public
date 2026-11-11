"""Stable Unicode FFprobe uploads across Windows/Python runtimes."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from banana_mv.core import command, probe


class FFProbeUploadTests(unittest.TestCase):
    def test_subprocess_decodes_ffprobe_utf8_like_working_vnext(self):
        fake=SimpleNamespace(returncode=0, stdout='{"streams":[]}', stderr='')
        with patch('banana_mv.core.subprocess.run', return_value=fake) as run:
            self.assertEqual(command(['ffprobe', '-of', 'json']), '{"streams":[]}')
        run.assert_called_once_with(
            ['ffprobe', '-of', 'json'], capture_output=True,
            text=True, encoding='utf-8', errors='replace')

    def test_unicode_audio_metadata_is_retained(self):
        content='{"streams":[{"codec_type":"audio"}],"format":{"tags":{"title":"香蕉拳王"}}}'
        with patch('banana_mv.core.command', return_value=content):
            metadata=probe('music.mp3')
        self.assertEqual(metadata['format']['tags']['title'], '香蕉拳王')
        self.assertEqual(metadata['streams'][0]['codec_type'], 'audio')

    def test_missing_ffprobe_capture_is_a_diagnostic_not_none_type(self):
        for bad in (None, ''):
            with self.subTest(bad=bad),patch('banana_mv.core.command',return_value=bad):
                with self.assertRaisesRegex(RuntimeError,'ffprobe returned no JSON'):
                    probe('music.mp3')

    def test_invalid_ffprobe_output_has_helpful_upload_error(self):
        with patch('banana_mv.core.command',return_value='oops'):
            with self.assertRaisesRegex(RuntimeError,'ffprobe returned invalid JSON'):
                probe('music.mp3')
        with patch('banana_mv.core.command',return_value='{"format":{}}'):
            with self.assertRaisesRegex(RuntimeError,'streams list'):
                probe('music.mp3')


if __name__=='__main__':
    unittest.main()
