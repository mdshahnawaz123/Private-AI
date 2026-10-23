"""Temporary loopback server exposing only viewer assets and the specified QA model."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import mimetypes
import sys

root = Path(__file__).resolve().parents[2]
assets = root / 'ui/vendor_fragments'
model = Path(sys.argv[1]).resolve(strict=True)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path).path
        if url == '/':
            target = Path(__file__).with_name('browser_smoke.html')
        elif url == '/model.frag':
            target = model
        elif url == '/bim_ai_tools.js':
            target = root / 'ui/bim_ai_tools.js'
        elif url.startswith('/assets/'):
            target = (assets / url.removeprefix('/assets/')).resolve()
            if not target.is_relative_to(assets):
                self.send_error(403)
                return
        else:
            self.send_error(404)
            return
        if not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        mime = 'application/javascript' if target.suffix in ('.mjs', '.js') else mimetypes.guess_type(target)[0]
        self.send_header('Content-Type', mime or 'application/octet-stream')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

print('Fragments smoke server: http://127.0.0.1:8766', flush=True)
ThreadingHTTPServer(('127.0.0.1', 8766), Handler).serve_forever()
