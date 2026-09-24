"""Small polling paper bot. All execution is local and recorded in SQLite."""
from datetime import datetime, timezone
import json
import re
import time
from pathlib import Path

from . import adapters
from .core import D, Store, dec, digest, levels, simulate, liquidity_hash


class Bot:
    def __init__(self, config, path, api=adapters, clock=time.time):
        if config['mode'] != 'paper' or config['version'] != 1:
            raise ValueError('Only paper mode version 1 exists')
        if set(config['arms']) != {'jev','rules'} or len(config['markets']) > 12:
            raise ValueError('Expected two paper arms and at most 12 markets')
        for name in ('initial_cash','order_budget','max_exposure','max_drawdown','max_spread','max_roundtrip_fraction'):
            if dec(config[name]) <= 0:
                raise ValueError('Invalid positive config parameter')
        if not 0 < dec(config['depth_fraction']) <= 1:
            raise ValueError('Invalid depth fraction')
        if dec(config['order_budget']) > dec(config['max_exposure']):
            raise ValueError('Order budget exceeds exposure cap')
        self.config,self.api,self.clock = config,api,clock
        self.store = Store(path, config, clock())
        self.db = self.store.db
        code_hash=digest({p.name:p.read_text() for p in sorted(Path(__file__).parent.glob('*.py'))})
        previous_hash=self.store.get('implementation_hash')
        if previous_hash and previous_hash!=code_hash:
            self.db.close()
            raise ValueError('Implementation changed: use a new experiment/database')
        with self.db:
            self.store.set('implementation_hash',code_hash)
        self.markets = {}
        self.last_meta = self.last_sources = self.last_mark = 0
        prior = self.db.execute("SELECT MAX(ts) FROM events WHERE kind='heartbeat'").fetchone()[0]
        self.previous_clock = prior if prior is not None else clock()

    def log(self, kind, payload):
        with self.db:
            self.store.event(kind,payload,self.clock())

    def snapshot(self, token):
        b = self.api.book(token)
        self.log('book',b)
        return b

    def refresh_markets(self):
        for spec in self.config['markets']:
            try:
                m = self.api.market(spec)
                self.markets[spec['id']] = m
                self.log('market',m)
                if m['signature'] != spec['approved_signature']:
                    self.log('rule_changed',{'market':spec['id']})
            except Exception as exc:
                self.markets.pop(spec['id'],None)
                self.log('market_error',{'market':spec['id'],'error':type(exc).__name__})
        self.last_meta = self.clock()

    def safe_market(self, spec, entry=True):
        m = self.markets.get(spec['id'])
        if not m or self.clock()-m['received_at']>120 or not m['accepting']:
            return None
        if entry and (m['signature']!=spec['approved_signature'] or
                      (m['end'] and self.clock()+self.config['max_hold_seconds']+60>=m['end'])):
            return None
        return m

    def open_positions(self, arm=None):
        rows = self.db.execute('SELECT * FROM positions'+(' WHERE arm=?' if arm else ''),
                               (arm,) if arm else ()).fetchall()
        return [r for r in rows if dec(r['qty'])>0]

    def risk_reason(self, arm, spec):
        positions = self.open_positions(arm)
        pending = self.db.execute("SELECT * FROM orders WHERE arm=? AND side='BUY' AND status='PENDING'",(arm,)).fetchall()
        if any(p['event_group']==spec['group'] for p in positions+pending):
            return 'GROUP_ALREADY_EXPOSED'
        recent = self.db.execute("SELECT MAX(decision) FROM orders WHERE arm=? AND event_group=? AND side='BUY' AND status='EXECUTED'",
                                 (arm,spec['group'])).fetchone()[0]
        if recent is not None and self.clock()-recent < self.config['cooldown_seconds']:
            return 'COOLDOWN'
        exposure = sum((dec(p['cost']) for p in positions),D(0))+sum((dec(p['budget']) for p in pending),D(0))
        budget = dec(self.config['order_budget'])
        if exposure+budget>dec(self.config['max_exposure']):
            return 'EXPOSURE_CAP'
        cash = dec(self.db.execute('SELECT cash FROM accounts WHERE arm=?',(arm,)).fetchone()[0])
        if cash-sum((dec(p['budget']) for p in pending),D(0))<budget:
            return 'CASH_RESERVED'
        mark = self.db.execute('SELECT * FROM valuations WHERE arm=? ORDER BY id DESC LIMIT 1',(arm,)).fetchone()
        if positions and (not mark or self.clock()-mark['ts']>60 or dec(mark['unpriced_qty'])>0):
            return 'INVENTORY_UNPRICED'
        equity = dec(mark['equity']) if mark else cash
        if dec(self.config['initial_cash'])-equity>=dec(self.config['max_drawdown']):
            return 'DRAWDOWN_PAUSE'
        return None

    def schedule_entry(self, arm, spec, outcome, evidence_id, decision_at):
        m = self.safe_market(spec)
        reason = self.risk_reason(arm,spec)
        if not m or reason:
            self.log('entry_rejected',{'arm':arm,'market':spec['id'],'reason':reason or 'MARKET_UNHEALTHY'})
            return
        b = self.snapshot(m['tokens'][outcome])
        asks,bids = levels(b,'asks'),levels(b,'bids')
        if not asks or not bids:
            self.log('entry_rejected',{'arm':arm,'market':spec['id'],'reason':'ONE_SIDED_BOOK'})
            return
        ask,bid = asks[0][0],bids[0][0]
        if not dec(self.config['min_entry_price'])<=ask<=dec(self.config['max_entry_price']) or ask-bid>dec(self.config['max_spread']):
            self.log('entry_rejected',{'arm':arm,'market':spec['id'],'reason':'PRICE_OR_SPREAD'})
            return
        rate = dec(m['rate'])
        roundtrip = (ask-bid+rate*ask*(1-ask)+rate*bid*(1-bid))/ask
        if roundtrip>dec(self.config['max_roundtrip_fraction']):
            self.log('entry_rejected',{'arm':arm,'market':spec['id'],'reason':'ROUNDTRIP_COST','fraction':str(roundtrip)})
            return
        limit = min(dec(self.config['max_entry_price']),ask+dec(m['tick'])*self.config['slippage_ticks'])
        now = self.clock()
        order = digest({'arm':arm,'market':spec['id'],'evidence':evidence_id,'action':'BUY'})
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (order,arm,spec['id'],m['tokens'][outcome],spec['group'],'BUY',str(limit),self.config['order_budget'],None,
                 decision_at,max(now,decision_at)+self.config['execution_delay_seconds'],
                 now+self.config['order_expiry_seconds'],'PENDING','signal'))
            self.store.event('entry_scheduled',{'order':order,'arm':arm,'market':spec['id'],'outcome':outcome},now)

    def schedule_exit(self, p, b, m, reason):
        if self.db.execute("SELECT 1 FROM orders WHERE position_id=? AND status='PENDING'",(p['id'],)).fetchone():
            return
        bids = levels(b,'bids')
        with self.db:
            self.db.execute('UPDATE positions SET exit_pending=1 WHERE id=?',(p['id'],))
            if not bids:
                self.store.event('exit_pending',{'position':p['id'],'reason':'NO_BIDS'},self.clock())
                return
            now = self.clock()
            limit = max(dec(m['tick']),bids[0][0]-dec(m['tick'])*self.config['slippage_ticks'])
            order = digest({'position':p['id'],'at':now,'action':'SELL'})
            self.db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (order,p['arm'],p['market'],p['token'],p['event_group'],'SELL',str(limit),'0',p['id'],
                 now,now+self.config['execution_delay_seconds'],now+self.config['order_expiry_seconds'],'PENDING',reason))

    def process_orders(self):
        for o in self.db.execute("SELECT * FROM orders WHERE status='PENDING' ORDER BY due").fetchall():
            now = self.clock()
            if now<o['due']:
                continue
            if now>o['expires']:
                with self.db:
                    self.db.execute("UPDATE orders SET status='EXPIRED' WHERE id=?",(o['id'],))
                continue
            spec = next(s for s in self.config['markets'] if s['id']==o['market'])
            try:
                # Re-read fee, accepting state, token mapping and rule at actual arrival.
                self.markets[spec['id']] = self.api.market(spec)
                m = self.safe_market(spec,entry=o['side']=='BUY')
                if not m or o['token'] not in m['tokens'].values():
                    with self.db:
                        self.db.execute("UPDATE orders SET status='CANCELLED' WHERE id=?",(o['id'],))
                    self.log('order_cancelled',{'order':o['id'],'reason':'MARKET_CHANGED_OR_CLOSED'})
                    continue
                b = self.snapshot(o['token'])
                if o['side']=='BUY':
                    asks,bids=levels(b,'asks'),levels(b,'bids')
                    reason=None
                    if not asks or not bids:
                        reason='ONE_SIDED_AT_ARRIVAL'
                    else:
                        ask,bid=asks[0][0],bids[0][0]
                        rate=dec(m['rate'])
                        friction=(ask-bid+rate*ask*(1-ask)+rate*bid*(1-bid))/ask
                        if ask-bid>dec(self.config['max_spread']) or friction>dec(self.config['max_roundtrip_fraction']):
                            reason='COST_CHANGED_AT_ARRIVAL'
                    last_mark=self.db.execute('SELECT * FROM valuations WHERE arm=? ORDER BY id DESC LIMIT 1',(o['arm'],)).fetchone()
                    if last_mark and (dec(self.config['initial_cash'])-dec(last_mark['equity'])>=dec(self.config['max_drawdown']) or dec(last_mark['unpriced_qty'])>0):
                        reason='RISK_PAUSE_AT_ARRIVAL'
                    if reason:
                        with self.db:
                            self.db.execute("UPDATE orders SET status='CANCELLED' WHERE id=?",(o['id'],))
                        self.log('order_cancelled',{'order':o['id'],'reason':reason})
                        continue
                result = self.store.execute(o['id'],b,m['rate'],m['minimum'],self.config,self.clock())
                self.log('order_result',{'order':o['id'],'status':result})
            except Exception as exc:
                self.log('execution_error',{'order':o['id'],'error':type(exc).__name__})

    def mark_and_exit(self):
        totals = {arm:{'cost':D(0),'value':D(0),'unpriced':D(0)} for arm in self.config['arms']}
        cached = {}
        for p in self.open_positions():
            t = totals[p['arm']]
            t['cost']+=dec(p['cost'])
            spec = next(s for s in self.config['markets'] if s['id']==p['market'])
            m = self.safe_market(spec,entry=False)
            if not m:
                t['unpriced']+=dec(p['qty'])
                self.log('position_unpriced',{'position':p['id'],'reason':'MARKET_CLOSED_OR_UNHEALTHY'})
                continue
            try:
                if p['token'] not in cached:
                    cached[p['token']]=self.snapshot(p['token'])
                b = cached[p['token']]
                fills = simulate(b,'SELL',m['tick'],m['rate'],self.config['depth_fraction'],quantity=p['qty'],
                                 consumed=self.store.consumption(p['arm'],p['token'],liquidity_hash(b,'SELL'),'SELL'))
                qty = sum((dec(f['quantity']) for f in fills),D(0))
                value = sum((dec(f['quantity'])*dec(f['price'])-dec(f['fee']) for f in fills),D(0))
                if dec(p['qty'])<dec(m['minimum']):
                    qty,value=D(0),D(0)
                t['value']+=value
                t['unpriced']+=dec(p['qty'])-qty
                full = qty==dec(p['qty'])
                ret = (value-dec(p['cost']))/dec(p['cost']) if full else None
                reason = 'exit_retry' if p['exit_pending'] else None
                if self.clock()-p['opened']>=self.config['max_hold_seconds']:
                    reason='time_exit'
                elif ret is not None and ret>=dec(self.config['take_profit_fraction']):
                    reason='take_profit'
                elif ret is not None and ret<=-dec(self.config['stop_loss_fraction']):
                    reason='stop_loss'
                if reason:
                    self.schedule_exit(p,b,m,reason)
            except Exception as exc:
                t['unpriced']+=dec(p['qty'])
                self.log('valuation_error',{'position':p['id'],'error':type(exc).__name__})
        with self.db:
            for arm,t in totals.items():
                cash = dec(self.db.execute('SELECT cash FROM accounts WHERE arm=?',(arm,)).fetchone()[0])
                self.db.execute('INSERT INTO valuations(ts,arm,cash,inventory_cost,liquidation,equity,unpriced_qty) VALUES(?,?,?,?,?,?,?)',
                    (self.clock(),arm,str(cash),str(t['cost']),str(t['value']),str(cash+t['value']),str(t['unpriced'])))
        self.last_mark=self.clock()

    def handle_evidence(self, evidence, previous=''):
        for spec in self.config['markets']:
            if spec['source']!=evidence['source'] or not any(re.search(p,evidence['text'],re.I) for p in spec['keywords']):
                continue
            m=self.safe_market(spec)
            if not m:
                self.log('candidate_skipped',{'evidence':evidence['id'],'market':spec['id'],'reason':'MARKET_UNHEALTHY'})
                continue
            for arm in self.config['arms']:
                try:
                    if arm=='rules':
                        side=self.api.rule_signal(spec,evidence)
                        result={'direction':side,'finished_at':self.clock()}
                    else:
                        day=datetime.fromtimestamp(self.clock(),timezone.utc).date().isoformat()
                        with self.db:
                            total=int(self.store.get('calls_total') or 0)
                            daily=int(self.store.get('calls_'+day) or 0)
                            if total>=self.config['model_max_total_calls'] or daily>=self.config['model_max_daily_calls']:
                                self.store.event('model_budget_skip',{'evidence':evidence['id'],'market':spec['id']},self.clock())
                                continue
                            self.store.set('calls_total',total+1)
                            self.store.set('calls_'+day,daily+1)
                        # Pre-judgment book anchors the latency diagnostic; no trading off it.
                        self.snapshot(m['tokens']['YES'])
                        result=self.api.judge(m,evidence,previous)
                        a=result['answers']
                        direction=a['direction']['choice']
                        side=direction.removeprefix('SUPPORTS_') if direction!='NO_SIGNAL' else None
                        if (dec(a['relevant']['probability'])<dec(self.config['relevance_threshold']) or
                            dec(a['clear']['probability'])<dec(self.config['clarity_threshold']) or
                            dec(a['direction']['probabilities'][direction])<dec(self.config['direction_threshold'])):
                            side=None
                    decision=self.clock()
                    self.log('judgment',{'arm':arm,'market':spec['id'],'evidence':evidence['id'],'side':side,'result':result})
                    if not side:
                        continue
                    for p in self.open_positions(arm):
                        if p['market']==spec['id'] and p['token']!=m['tokens'][side]:
                            self.schedule_exit(p,self.snapshot(p['token']),m,'opposite_evidence')
                    self.schedule_entry(arm,spec,side,evidence['id'],decision)
                except Exception as exc:
                    self.log('judgment_error',{'arm':arm,'market':spec['id'],'evidence':evidence['id'],'error':type(exc).__name__})

    def poll_sources(self):
        for source in self.config['sources']:
            try:
                entries=self.api.parse_feed(self.api.get(source['url']),source)
                first=not self.store.get('source_initialized_'+source['id'])
                for e in entries:
                    seen=self.db.execute('SELECT processed FROM evidence WHERE id=?',(e['id'],)).fetchone()
                    if seen:
                        if seen['processed']==0:
                            with self.db:
                                self.db.execute('UPDATE evidence SET processed=-1 WHERE id=?',(e['id'],))
                                self.store.event('interrupted_evidence_skipped',{'id':e['id']},self.clock())
                        continue
                    now=self.clock()
                    previous=self.db.execute('SELECT text FROM evidence WHERE source=? AND url=? ORDER BY ts DESC LIMIT 1',
                                             (source['id'],e['url'])).fetchone()
                    age=now-e['published'] if e['published'] is not None else None
                    eligible=not first and age is not None and -60<=age<=self.config['max_evidence_age_seconds']
                    # At-most-once: on crash do not replay old signals as if just received.
                    with self.db:
                        self.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?)',
                            (e['id'],e['source'],e['url'],now,e['published'],e['title'],e['text'],int(first),0 if eligible else 1))
                        self.store.event('evidence_seen',{'id':e['id'],'source':source['id'],'baseline':first,
                                                        'eligible':eligible,'published_at':e['published']},now)
                    if eligible:
                        self.handle_evidence(e,previous[0] if previous else '')
                        with self.db:
                            self.db.execute('UPDATE evidence SET processed=1 WHERE id=?',(e['id'],))
                with self.db:
                    self.store.set('source_initialized_'+source['id'],'1')
                    self.store.event('source_ok',{'source':source['id'],'entries':len(entries),'baseline':first},self.clock())
            except Exception as exc:
                self.log('source_error',{'source':source['id'],'error':type(exc).__name__})
        self.last_sources=self.clock()

    def cycle(self):
        now=self.clock()
        if now<self.previous_clock-1:
            raise ValueError('System clock moved backwards; restart after clock repair')
        if now-self.previous_clock>120:
            self.log('coverage_gap',{'seconds':now-self.previous_clock})
        self.previous_clock=now
        if now-self.last_meta>=self.config['metadata_poll_seconds']:
            self.refresh_markets()
        self.process_orders()
        if now-self.last_mark>=self.config['book_poll_seconds']:
            self.mark_and_exit()
        if now-self.last_sources>=self.config['source_poll_seconds']:
            self.poll_sources()
        self.log('heartbeat',{'markets_healthy':len(self.markets)})
