import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from banana_mv import server


class DownloadNameTests(unittest.TestCase):
    def handler(self, path):
        handler = object.__new__(server.Handler)
        handler.path = path
        handler.send_file = Mock()
        handler.send_json = Mock()
        return handler

    def test_download_serves_the_videos_copy_with_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, videos = Path(tmp, 'job'), Path(tmp, 'videos')
            work.mkdir(); videos.mkdir()
            (work / 'final.mp4').write_bytes(b'master')
            (work / 'final_v001.mp4').write_bytes(b'master')
            (work / 'final_v002.mp4').write_bytes(b'upscaled!')
            current = videos / '幽冥食堂_abc_v001.mp4'; current.write_bytes(b'master')
            upscaled = videos / '幽冥食堂_abc_v001_1440p_v002.mp4'; upscaled.write_bytes(b'upscaled!')
            job = {'id': 'abc', 'title': '幽冥食堂', 'current_master': 1, 'output_video': str(current),
                   'final_versions': [{'version': 1, 'file': 'final_v001.mp4'},
                                      {'version': 2, 'file': 'final_v002.mp4', 'output_video': str(upscaled)}]}
            with patch.object(server, 'read_state', return_value=job), patch.object(server, 'job_dir', return_value=work):
                h = self.handler('/api/mv/file?id=abc'); h.do_GET()
                self.assertEqual(h.send_file.call_args.args[0], current)
                self.assertEqual(h.send_file.call_args.kwargs['filename'], '幽冥食堂_abc_v001.mp4')
                h = self.handler('/api/mv/file?id=abc&version=2'); h.do_GET()
                self.assertEqual(h.send_file.call_args.args[0], upscaled)
                self.assertEqual(h.send_file.call_args.kwargs['filename'], '幽冥食堂_abc_v001_1440p_v002.mp4')
                current.unlink()   # 另存失敗或舊專案：仍可下載，用作品名當檔名
                h = self.handler('/api/mv/file?id=abc'); h.do_GET()
                self.assertEqual(h.send_file.call_args.args[0], work / 'final.mp4')
                self.assertEqual(h.send_file.call_args.kwargs['filename'], '幽冥食堂_abc_v001.mp4')


if __name__ == '__main__':
    unittest.main()
