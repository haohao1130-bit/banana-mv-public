"""CPU-only contract checks for the optional 35B transport."""
import unittest
import io
from banana_mv import director35

class ImageStub:
    def convert(self,mode):
        assert mode=='RGB'
        return self
    def save(self,buf,format,quality):
        assert format=='JPEG'
        buf.write(b'image bytes')

class Director35Tests(unittest.TestCase):
    def test_old_projects_remain_9b(self):
        self.assertIsNone(director35.options({}))
        self.assertIsNone(director35.options({'director_engine':'9b'}))
    def test_default_mtp_and_experts(self):
        self.assertEqual(director35.options({'director_engine':'35b'}),
                         {'ctx':16384,'moe':36,'kv':'q8_0','mtp':True,'max_tokens':4096})
    def test_invalid_options(self):
        for override in ({'director35_mtp':'false'},{'director35_cpu_moe':23},
                         {'director35_context':8192,'director35_output':8192},
                         {'director35_kv':'unsupported'}):
            with self.subTest(override=override),self.assertRaises(ValueError):
                director35.options({'director_engine':'35b',**override})
    def test_preserve_interleaved_picture_order(self):
        msg=director35.messages('system',[('text','<Picture 1>:'),('image',ImageStub()),
                                           ('text','<Picture 2>:'),('image',ImageStub()),
                                           ('text','current commission')])
        self.assertEqual(msg[0]['content'],'system')
        parts=msg[1]['content']
        self.assertEqual([p['type'] for p in parts],['text','image_url','text','image_url','text'])
        self.assertEqual(parts[0]['text'],'<Picture 1>:')
        self.assertEqual(parts[2]['text'],'<Picture 2>:')
        self.assertTrue(parts[1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
        self.assertEqual(parts[-1]['text'],'current commission')
    def test_text_only(self):
        msg=director35.messages('system',[('text','first'),('text','second')])
        self.assertEqual(msg[1]['content'],'first\nsecond')

if __name__=='__main__':
    unittest.main()
