import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from banana_mv import server


class DownloadNameTests(unittest.TestCase):
    def get(self, path):
        handler = object.__new__(server.Handler)
        handler.path = path
        handler.send_file = Mock()
        handler.send_json = Mock()
        handler.do_GET()
        return handler

    def test_downloads_use_the_videos_copy_and_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, videos = Path(tmp, 'job'), Path(tmp, 'videos')
            work.mkdir(); videos.mkdir()
            for name, data in (('final.mp4', b'master'), ('final_v001.mp4', b'master'), ('final_v002.mp4', b'upscaled!')):
                (work / name).write_bytes(data)
            upscaled = videos / '白蛇_abc_v001_1440p_v002.mp4'; upscaled.write_bytes(b'upscaled!')
            job = {'id': 'abc', 'title': '白蛇', 'current_master': 1,
                   'final_versions': [{'version': 1, 'file': 'final_v001.mp4'},
                                      {'version': 2, 'file': 'final_v002.mp4', 'output_video': str(upscaled)}]}
            with patch.dict('os.environ', {'BANANA_FINISHED_VIDEOS': str(videos)}), \
                 patch.object(server, 'read_state', return_value=job), patch.object(server, 'job_dir', return_value=work):
                h = self.get('/api/mv/file?id=abc&version=2&download=1')     # 2K 版：給 videos 裡那份
                self.assertEqual(h.send_file.call_args.args[0], upscaled)
                self.assertEqual(h.send_file.call_args.kwargs['download_name'], upscaled.name)
                h = self.get('/api/mv/file?id=abc&version=1&download=1')     # 沒另存的版本：仍有作品名檔名
                self.assertEqual(h.send_file.call_args.kwargs['download_name'], '白蛇_abc_v001.mp4')
                h = self.get('/api/mv/file?id=abc&version=2')                # 播放不帶下載檔名
                self.assertNotIn('download_name', h.send_file.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
