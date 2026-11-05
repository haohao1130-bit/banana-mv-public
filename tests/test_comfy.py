"""Real HTTP requests to a fake ComfyUI, without model or GPU execution."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from banana_mv import comfy


class ComfyTests(unittest.TestCase):
    def test_http_queue_history_download_and_rejection(self):
        requests=[]
        class Fake(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path=='/free':
                    self.send_response(200);self.end_headers();return
                requests.append(payload)
                result={'prompt_id':'p1'} if payload['prompt'] else {'error':'invalid'}
                data=json.dumps(result).encode();self.send_response(200);self.end_headers();self.wfile.write(data)
            def do_GET(self):
                if self.path=='/empty':
                    self.send_response(200);self.end_headers();return
                if self.path=='/html':
                    self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
                    self.wfile.write(b'<html>not JSON</html>');return
                if self.path.startswith('/view?'):
                    self.send_response(200);self.end_headers();self.wfile.write(b'video-bytes');return
                data=json.dumps({'p1':{'status':{'completed':True},'outputs':{'result':{'text':['rewritten']}}}}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Fake)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        cfg={'comfy_url':f'http://127.0.0.1:{server.server_port}'}
        try:
            self.assertEqual(comfy.comfy(cfg,'/free',{'unload_models':True,'free_memory':True}),{})
            with self.assertRaisesRegex(RuntimeError,'/empty.*空內容'):comfy.comfy(cfg,'/empty')
            with self.assertRaisesRegex(RuntimeError,'/html.*非 JSON'):comfy.comfy(cfg,'/html')
            self.assertEqual(comfy.queue_prompt(cfg,{'1':{'class_type':'example'}}),'p1')
            self.assertTrue(comfy.wait_prompt(cfg,'p1')['status']['completed'])
            self.assertTrue(requests[0]['client_id'].startswith('banana-'))
            with self.assertRaisesRegex(RuntimeError,'拒絕'):
                comfy.queue_prompt(cfg,{})
            with tempfile.TemporaryDirectory() as tmp:
                dest=Path(tmp)/'result.mp4';comfy.comfy_download(cfg,{'filename':'x.mp4'},dest)
                self.assertEqual(dest.read_bytes(),b'video-bytes')
            # Full local-rewriter HTTP path: successful text followed by an empty /free acknowledgement.
            from banana_mv import services
            from PIL import Image
            with tempfile.TemporaryDirectory() as tmp:
                rewrite_cfg=services.load_config()
                rewrite_cfg.update(comfy_url=cfg['comfy_url'],comfy_input_dir=tmp)
                self.assertEqual(services.rewrite_local(rewrite_cfg,'guide',
                    [('text','<Picture 1>'),('image',Image.new('RGB',(32,32),'red'))],'http-test'),'rewritten')
                self.assertEqual(list(Path(tmp).glob('*.jpg')),[])
            with patch.object(comfy,'history_entry',return_value={'status':{'status_str':'error',
                'messages':[['execution_error',{'node_type':'Test','exception_message':'bad tag'}]]}}):
                with self.assertRaisesRegex(RuntimeError,'Test: bad tag'):comfy.wait_prompt(cfg,'p1')
        finally:
            server.shutdown();server.server_close()
