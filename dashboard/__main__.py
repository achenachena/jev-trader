"""Private dashboard server; optional supervisor for a single paper worker."""
import argparse
import base64
import binascii
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlsplit

from .data import snapshot

STATIC = Path(__file__).parent/'static'
ASSETS = {'/': ('index.html','text/html; charset=utf-8'),
          '/app.js': ('app.js','text/javascript; charset=utf-8'),
          '/style.css': ('style.css','text/css; charset=utf-8')}


def make_server(db_path, host='127.0.0.1', port=8080, password=None, hub=None):
    if host not in ('127.0.0.1','localhost') and (not password or len(password)<16):
        raise ValueError('Public binding requires DASHBOARD_PASSWORD (at least 16 characters); use HTTPS at the proxy')

    class Handler(BaseHTTPRequestHandler):
        server_version='JevDashboard'
        def log_message(self, fmt, *args):
            # Do not log credentials, URL query strings or arbitrary request bodies.
            pass

        def send(self, status, body, content_type='application/json; charset=utf-8', auth=False):
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            if auth:
                self.send_header('WWW-Authenticate','Basic realm="Jev paper dashboard", charset="UTF-8"')
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            if password is None:
                return True
            try:
                raw=self.headers.get('Authorization','')
                if not raw.startswith('Basic '): return False
                user,secret=base64.b64decode(raw[6:],validate=True).decode().split(':',1)
                return hmac.compare_digest(user,'viewer') and hmac.compare_digest(secret.encode(),password.encode())
            except (ValueError,UnicodeError,binascii.Error):
                return False

        def stream(self):
            if hub is None:
                self.send(503,b'{"error":"Stream unavailable"}')
                return
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream; charset=utf-8')
            self.send_header('Cache-Control','no-cache, no-transform')
            self.send_header('X-Accel-Buffering','no')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.connection.settimeout(20)
            # Every (re)connection gets a full state, even with Last-Event-ID.
            # IDs are stream versions, not trade IDs. Replaying trades is unnecessary.
            previous=None
            try:
                self.wfile.write(b'retry: 2000\n\n'); self.wfile.flush()
                while not hub.stopped.is_set():
                    update=hub.next(previous)
                    if update:
                        ident,kind,payload=update
                        packet=f'id: {ident}\nevent: {kind}\ndata: {payload}\n\n'.encode()
                        previous=ident
                    else:
                        packet=b': keepalive\n\n'
                    self.wfile.write(packet); self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,TimeoutError,OSError):
                pass

        def do_GET(self):
            path=urlsplit(self.path).path
            # Liveness only; worker freshness is shown separately, not inferred from HTTP 200.
            if path=='/healthz':
                self.send(200,b'{"web":"ok"}')
                return
            if not self.authorized():
                self.send(401,b'{"error":"Authentication required"}',auth=True)
                return
            if path=='/api/events':
                self.stream()
            elif path in ASSETS:
                name,kind=ASSETS[path]
                self.send(200,(STATIC/name).read_bytes(),kind)
            elif path=='/api/state':
                try:
                    state=snapshot(db_path)
                    self.send(200,json.dumps(state,ensure_ascii=False,allow_nan=False).encode())
                except (sqlite3.Error,KeyError,ValueError):
                    self.send(503,b'{"error":"Ledger unavailable or initializing"}')
            else:
                self.send(404,b'{"error":"Not found"}')

    server=ThreadingHTTPServer((host,port),Handler)
    server.daemon_threads=True
    return server


def stop_worker(worker):
    if worker and worker.poll() is None:
        worker.send_signal(signal.SIGINT)
        try:
            worker.wait(timeout=40)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait()


def main():
    parser=argparse.ArgumentParser(description='Read-only paper dashboard; optional paper worker supervision')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','8080')))
    parser.add_argument('--db',type=Path,default=Path(os.environ.get('PAPER_DB','data/paper.sqlite')))
    parser.add_argument('--with-bot',action='store_true')
    parser.add_argument('--config',type=Path,default=Path('config/paper.json'))
    parser.add_argument('--output',type=Path,default=Path(os.environ.get('PAPER_REPORTS','reports/paper')))
    args=parser.parse_args()
    from .stream import StateHub
    hub=StateHub(args.db)
    server=make_server(args.db,args.host,args.port,os.environ.get('DASHBOARD_PASSWORD') or None,hub=hub)
    server.timeout=1
    worker=None
    stopping=False
    def stop(signum,frame):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    try:
        hub.start()
        if args.with_bot:
            worker=subprocess.Popen([sys.executable,'-m','jev_trader','run','--db',str(args.db),
                '--config',str(args.config),'--output',str(args.output)],start_new_session=True)
        print(f'Dashboard listening on {args.host}:{server.server_port}; paper-only; worker={bool(worker)}',flush=True)
        while not stopping:
            if worker and worker.poll() is not None:
                print('Paper worker exited; stopping service for platform restart',file=sys.stderr,flush=True)
                raise SystemExit(1)
            server.handle_request()
    finally:
        server.server_close()
        stop_worker(worker)
        hub.close()


if __name__=='__main__':
    main()
