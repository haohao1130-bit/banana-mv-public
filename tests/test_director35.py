"""CPU-only contract checks for the optional 35B transport."""
import unittest
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
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
                         {'ctx':16384,'moe':36,'kv':'q8_0','mtp':True,'max_tokens':4096,'reasoning_budget':-1})
    def test_thinking_defaults_and_reserve(self):
        opts=director35.options({'director_engine':'35b','rewriter_thinking':True})
        self.assertEqual((opts['ctx'],opts['max_tokens'],opts['reasoning_budget']),(32768,16384,-1))
        base={'director_engine':'35b','rewriter_thinking':True,'director35_reasoning_budget':12288}
        self.assertEqual(director35.options(base)['reasoning_budget'],12288)
        with self.assertRaises(ValueError):
            director35.options({**base,'director35_output':8192})
        with self.assertRaises(ValueError):
            director35.options({**base,'director35_reasoning_budget':True})
        # Legacy saved jobs retain explicit settings.
        opts=director35.options({'director_engine':'35b','rewriter_thinking':True,
            'director35_context':16384,'director35_output':4096})
        self.assertEqual((opts['ctx'],opts['max_tokens']),(16384,4096))
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

    def test_truncated_thinking_draft_is_saved_but_not_accepted(self):
        requests=[]
        def open_request(req,timeout):
            requests.append(json.loads(req.data))
            event={'choices':[{'delta':{'reasoning_content':'analysis','content':'partial draft'},
                              'finish_reason':'length'}]}
            return io.BytesIO(('data: '+json.dumps(event)+'\n\ndata: [DONE]\n').encode())
        lab=SimpleNamespace(BASE='http://127.0.0.1:8091',
                            OPENER=SimpleNamespace(open=open_request),
                            STOP=SimpleNamespace(is_set=lambda:False),
                            save=lambda p,v:p.write_text(json.dumps(v),encoding='utf-8'))
        opts={'thinking':True,'vision':True,'max_tokens':16384,'reasoning_budget':12288,'seed':42}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            out,metrics=director35.stream_call(lab,[],opts,path,0,{})
            self.assertEqual(out,'')
            self.assertEqual(metrics['finish_reason'],'length')
            self.assertEqual((path/'attempt1_formal.txt').read_text(encoding='utf-8'),'partial draft')
            self.assertEqual(requests[0]['reasoning_budget_tokens'],12288)
            with self.assertRaisesRegex(RuntimeError,'未完整交稿'):
                director35.stream_call(lab,[],opts,path,1,{})
            self.assertEqual(requests[1]['reasoning_budget_tokens'],0)
            self.assertFalse(requests[1]['chat_template_kwargs']['enable_thinking'])

    def test_dashboard_uses_actual_stream_counters(self):
        with director35._STATS_LOCK:
            director35._STATS.clear()
        try:
            director35._stream_stats({'prompt_progress':{'total':1000,'processed':600,'cache':200,'time_ms':4000}},'prefill')
            state=director35.snapshot()
            self.assertEqual(state['prompt_processed'],600)
            self.assertEqual(state['prefill_tps'],100)
            self.assertNotIn('decode_tps',state)
            director35._stream_stats({'timings':{'prompt_n':800,'prompt_ms':8000,'prompt_per_second':100,
                'predicted_n':60,'predicted_ms':1000,'predicted_per_second':60,'draft_n':50,'draft_n_accepted':40}},'writing',8)
            state=director35.snapshot()
            self.assertEqual(state['decode_tps'],60)
            self.assertEqual(state['output_tokens'],60)
            self.assertEqual(state['mtp_accept_pct'],80)
            self.assertEqual(state['ttft_s'],8)
            director35._stream_stats({'timings':{'predicted_per_second':float('inf'),'predicted_ms':1000}},'writing')
            self.assertEqual(director35.snapshot()['decode_tps'],60)
        finally:
            with director35._STATS_LOCK:
                director35._STATS.clear()

if __name__=='__main__':
    unittest.main()
