import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from banana_mv import services

class AssetReuseTests(unittest.TestCase):
    def test_content_identity_legacy_and_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);lib=root/'library';lib.mkdir()
            cfg={'comfy_input_dir':str(root/'input')}
            def image(color):
                buf=io.BytesIO();Image.new('RGB',(8,8),color).save(buf,format='PNG')
                return buf.getvalue()
            body=image('red')
            with patch.object(services,'LIBRARY',lib):
                first=services.add_asset(cfg,'first.png',body)
                self.assertEqual(services.add_asset(cfg,'renamed.png',body)['id'],first['id'])
                second=services.add_asset(cfg,'first.png',image('blue'))
                self.assertNotEqual(second['id'],first['id'])
                index=services.library_index()
                for row in index:
                    row.pop('sha256',None);row.pop('content_stat',None)
                (lib/'library.json').write_text(json.dumps(index))
                target=root/'input'/first['comfy_name'];target.unlink()
                digest=hashlib.sha256(body).hexdigest()
                self.assertEqual(services.find_asset(cfg,digest,len(body))['id'],first['id'])
                self.assertEqual(target.read_bytes(),body)
                with patch.object(services.hashlib,'file_digest',side_effect=AssertionError('rehashed')):
                    self.assertEqual(services.find_asset(cfg,digest,len(body))['id'],first['id'])
                (lib/first['file']).unlink()
                self.assertIsNone(services.find_asset(cfg,digest,len(body)))
                for digest,size in [('bad',1),('0'*64,-1),('0'*64,True)]:
                    with self.assertRaises(ValueError):services.find_asset(cfg,digest,size)
