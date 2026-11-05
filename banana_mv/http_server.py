"""HTTP helpers for the Banana frontend, including seekable local video delivery."""
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path

MAX_UPLOAD = 256 * 1024 * 1024


class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, value, code=200):
        encoded = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(encoded)

    def read_body(self, maximum=MAX_UPLOAD):
        length = int(self.headers.get('Content-Length', 0))
        if length < 0 or length > maximum:
            raise ValueError('檔案過大，單檔最多 256 MiB。')
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError('上傳未完成，請重試。')
        return body

    def body_json(self):
        value = json.loads(self.read_body(1024*1024) or b'{}')
        if not isinstance(value, dict):
            raise ValueError('請求必須為 JSON 物件。')
        return value

    def send_file(self, path):
        path = Path(path)
        if not path.is_file():
            return self.send_error(404)
        size = path.stat().st_size
        begin, end, code = 0, size-1, 200
        requested = self.headers.get('Range')
        if requested:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested.strip())
            if match and (match[1] or match[2]):
                if match[1]:
                    begin = int(match[1]); end = min(int(match[2]), size-1) if match[2] else size-1
                else:
                    begin = max(0, size-int(match[2]))
                code = 206
            if not match or not (0 <= begin <= end < size) or not (match[1] or match[2]):
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0'); self.end_headers()
                return
        count = max(0, end-begin+1)
        self.send_response(code)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(count))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-cache')
        if code == 206:
            self.send_header('Content-Range', f'bytes {begin}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        with path.open('rb') as source:
            source.seek(begin)
            while count:
                chunk = source.read(min(count, 256*1024))
                if not chunk:
                    break
                self.wfile.write(chunk); count -= len(chunk)

    def do_HEAD(self):
        self.do_GET()
