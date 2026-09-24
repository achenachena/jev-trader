"""Read-only finance views, private HTTP routes, and event-driven synchronization."""
import base64
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from jev_trader.core import Store
from dashboard.data import snapshot
from dashboard.__main__ import make_server
from dashboard.stream import StateHub


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'paper.sqlite'
        self.now=time.time()
        config=json.loads(Path('config/paper.json').read_text())
        self.store=Store(self.path,config,self.now)
        with self.store.db:
            self.store.event('heartbeat',{},self.now)
            for arm in ('jev','rules'):
                self.store.db.execute('INSERT INTO valuations(ts,arm,cash,inventory_cost,liquidation,equity,unpriced_qty) VALUES(?,?,?,?,?,?,?)',
                    (self.now,arm,'1000','0','0','1000','0'))

    def tearDown(self):
        self.store.db.close();self.temp.cleanup()

    def test_snapshot_is_readonly_and_has_no_model_input(self):
        with self.store.db:
            self.store.event('judgment',{'arm':'jev','market':'4117967','side':None,'result':{
                'input':{'secret':'NEVER_EXPOSE'},'cost':'0','answers':{}}},self.now)
        before=list(self.store.db.iterdump())
        s=snapshot(self.path,now=self.now+1)
        self.assertEqual(s['accounts']['jev']['equity'],'1000')
        self.assertEqual(s['status'],'running')
        self.assertNotIn('NEVER_EXPOSE',json.dumps(s))
        self.assertEqual(before,list(self.store.db.iterdump()))

    def test_missing_ledger_does_not_create_file(self):
        path=self.path.parent/'missing.sqlite'
        with self.assertRaises(sqlite3.OperationalError):snapshot(path)
        self.assertFalse(path.exists())

    def test_fresh_cash_not_combined_with_stale_inventory(self):
        with self.store.db:
            self.store.db.execute("UPDATE accounts SET cash='990' WHERE arm='jev'")
            self.store.db.execute('INSERT INTO positions(arm,market,token,event_group,qty,cost,opened,updated) VALUES(?,?,?,?,?,?,?,?)',
                ('jev','4117967','yes','apple-foldable','20','10',self.now+2,self.now+2))
        a=snapshot(self.path,now=self.now+3)['accounts']['jev']
        self.assertEqual(a['equity'],'990')
        self.assertEqual(a['unpriced_shares'],'20')
        self.assertFalse(a['valuation_current'])
        self.assertIsNone(a['daily_pnl'])

    def test_stale_heartbeat_and_explicit_stop(self):
        self.assertEqual(snapshot(self.path,now=self.now+121)['status'],'stale')
        with self.store.db:self.store.event('stopped',{},self.now+1)
        self.assertEqual(snapshot(self.path,now=self.now+2)['status'],'stopped')

    def test_public_binding_requires_password(self):
        with self.assertRaises(ValueError):make_server(self.path,'0.0.0.0',0)

    def test_auth_routes_and_no_write_api(self):
        server=make_server(self.path,port=0,password='test-password-123456')
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        url=f'http://127.0.0.1:{server.server_port}'
        auth='Basic '+base64.b64encode(b'viewer:test-password-123456').decode()
        try:
            for route in ('/','/api/state','/api/events'):
                with self.assertRaises(urllib.error.HTTPError) as ctx:urllib.request.urlopen(url+route)
                self.assertEqual(ctx.exception.code,401)
                ctx.exception.close()
            with urllib.request.urlopen(url+'/healthz') as r:self.assertEqual(r.status,200)
            with urllib.request.urlopen(urllib.request.Request(url+'/api/state',headers={'Authorization':auth})) as r:
                self.assertEqual(json.load(r)['mode'],'PAPER_ONLY')
                self.assertEqual(r.headers['Cache-Control'],'no-store')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(urllib.request.Request(url+'/api/state',headers={'Authorization':auth},data=b'{}'))
            self.assertEqual(ctx.exception.code,501)
            ctx.exception.close()
        finally:server.shutdown();server.server_close();worker.join()

    def test_native_notification_updates_hub_and_reconnect_gets_full_state(self):
        hub=StateHub(self.path,reconcile_seconds=60)
        hub.start()
        try:
            first=hub.next(timeout=5)
            self.assertIsNotNone(first)
            self.assertEqual(first[1],'state')
            start=time.monotonic()
            with self.store.db:self.store.db.execute("UPDATE accounts SET cash='987.65' WHERE arm='jev'")
            previous=first[0]
            while time.monotonic()-start<6:
                update=hub.next(previous,timeout=1)
                if update:
                    previous=update[0]
                    if json.loads(update[2])['accounts']['jev']['cash']=='987.65':break
            else:self.fail('Native file notification did not produce a new committed snapshot')
            self.assertEqual(json.loads(hub.next(None,timeout=1)[2])['accounts']['jev']['cash'],'987.65')
            self.assertLess(time.monotonic()-start,6)  # Must not depend on the 60s reconciliation timer.
        finally:hub.close()

    def test_sse_initial_state_and_auth(self):
        hub=StateHub(self.path);hub.start()
        server=make_server(self.path,port=0,hub=hub)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/events',timeout=5) as response:
                self.assertIn('text/event-stream',response.headers['Content-Type'])
                for _ in range(8):
                    line=response.readline().decode()
                    if line.startswith('data: '):
                        state=json.loads(line[6:]);break
                else:self.fail('Missing initial full state')
                self.assertEqual(state['accounts']['jev']['cash'],'1000')
        finally:hub.close();server.shutdown();server.server_close();worker.join()


if __name__=='__main__':unittest.main()
