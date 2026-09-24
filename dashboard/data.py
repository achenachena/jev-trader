"""Consistent, read-only ledger snapshots. Never imports or starts the trader."""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
import time


def rows(db, sql, params=()):
    return [dict(r) for r in db.execute(sql, params)]


def events(db, where, params=(), limit=100):
    return [{**r, 'payload': json.loads(r['payload'])} for r in rows(
        db, 'SELECT id,ts,kind,payload FROM events WHERE '+where+' ORDER BY id DESC LIMIT ?', (*params, limit))]


def snapshot(path, now=None):
    now = time.time() if now is None else now
    # mode=ro prevents both creating a missing ledger and accidental writes.
    uri = Path(path).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=3)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        meta = dict(db.execute('SELECT key,value FROM meta'))
        cfg = json.loads(meta['config'])
        specs = {str(m['id']): m for m in cfg['markets']}
        def title(m):
            return specs.get(str(m), {}).get('question', str(m))
        market_events = events(db, "kind='market'", limit=100)
        market_info = {}
        for e in market_events:
            m = e['payload']
            market_info.setdefault(str(m['id']), m)
        def outcome(m, token):
            return next((side for side,t in market_info.get(str(m),{}).get('tokens',{}).items() if t==token), 'UNKNOWN')
        heart = events(db, "kind IN ('heartbeat','started','stopped')", limit=1)
        last_heart = events(db, "kind='heartbeat'", limit=1)
        heartbeat = last_heart[0]['ts'] if last_heart else None
        age = now-heartbeat if heartbeat is not None else None
        status = 'waiting' if age is None else ('running' if 0 <= age <= 120 else 'stale')
        if heart and heart[0]['kind']=='stopped':
            status='stopped'
        counts = dict(db.execute('SELECT kind,COUNT(*) FROM events GROUP BY kind'))
        orders = rows(db, 'SELECT * FROM orders ORDER BY decision DESC LIMIT 100')
        fills = rows(db, '''SELECT f.id,f.ts,f.price,f.qty,f.fee,f.cash_delta,o.arm,o.market,o.token,o.side,o.reason
            FROM fills f JOIN orders o ON o.id=f.order_id ORDER BY f.id DESC LIMIT 100''')
        for item in orders+fills:
            item['question']=title(item['market'])
            item['outcome']=outcome(item['market'],item['token'])
            item.pop('token',None)
        accounts={}
        midnight=datetime.fromtimestamp(now,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        for a in rows(db,'SELECT * FROM accounts'):
            arm=a['arm']
            positions=[p for p in rows(db,'SELECT * FROM positions WHERE arm=?',(arm,)) if D(p['qty'])>0]
            latest=rows(db,'SELECT * FROM valuations WHERE arm=? ORDER BY id DESC LIMIT 1',(arm,))
            mark=latest[0] if latest else None
            changed=db.execute('SELECT MAX(updated) FROM positions WHERE arm=?',(arm,)).fetchone()[0]
            matches=bool(mark and (changed is None or changed<=mark['ts']) and D(mark['cash'])==D(a['cash']))
            priced=matches and 0 <= now-mark['ts'] <= 60
            cost=sum((D(p['cost']) for p in positions),D(0))
            # A stale mark is not a current price. Keep cash and expose unknown shares.
            liquidation=D(mark['liquidation']) if priced else D(0)
            unknown=D(mark['unpriced_qty']) if priced else sum((D(p['qty']) for p in positions),D(0))
            equity=D(a['cash'])+liquidation
            beginning=rows(db,'SELECT * FROM valuations WHERE arm=? AND ts<=? ORDER BY ts DESC LIMIT 1',(arm,midnight))
            if not beginning:
                beginning=rows(db,'SELECT * FROM valuations WHERE arm=? ORDER BY ts LIMIT 1',(arm,))
            start=beginning[0] if beginning else None
            gaps=db.execute("SELECT COUNT(*) FROM events WHERE kind='coverage_gap' AND ts>=?",(midnight,)).fetchone()[0]
            for p in positions:
                p['question']=title(p['market']); p['outcome']=outcome(p['market'],p['token'])
                p['average_cost']=str(D(p['cost'])/D(p['qty']))
                p.pop('token',None)
            reserved=sum((D(r[0]) for r in db.execute("SELECT budget FROM orders WHERE arm=? AND side='BUY' AND status='PENDING'",(arm,))),D(0))
            account={**a,'initial_cash':cfg['initial_cash'],'available_cash':str(D(a['cash'])-reserved),
                'reserved':str(reserved),'equity':str(equity),'inventory_cost':str(cost),
                'liquidation':str(liquidation),'unrealized':str(liquidation-cost),'total_pnl':str(equity-D(cfg['initial_cash'])),
                'unpriced_shares':str(unknown),'valuation_current':bool(priced),'mark_ts':mark['ts'] if mark else None,
                'positions':positions,'daily_pnl':str(equity-D(start['equity'])) if start and priced else None,
                'daily_start':start['ts'] if start else None,
                'daily_complete':bool(start and midnight-60<=start['ts']<=midnight and not gaps and priced and unknown==0),
                'orders':dict(db.execute('SELECT status,COUNT(*) FROM orders WHERE arm=? GROUP BY status',(arm,)))}
            # At most one observed point per five minutes, with real timestamps.
            account['history']=rows(db,'''SELECT ts,equity,unpriced_qty FROM valuations WHERE id IN
                (SELECT MAX(id) FROM valuations WHERE arm=? AND ts>=? GROUP BY CAST(ts/300 AS INTEGER)) ORDER BY ts''',(arm,now-86400))
            accounts[arm]=account
        # Explicit allowlist: never expose model inputs, raw books, metadata or credentials.
        kinds=('judgment','entry_rejected','entry_scheduled','candidate_skipped','paper_fill','order_result',
               'order_cancelled','execution_error','judgment_error','model_budget_skip','interrupted_evidence_skipped','exit_pending')
        timeline=events(db,'kind IN ('+','.join('?'*len(kinds))+')',kinds,80)
        decisions=[]
        order_lookup={o['id']:o for o in orders}
        for e in timeline:
            p=e['payload']; result=p.get('result',{})
            o=order_lookup.get(p.get('order'),{})
            market=p.get('market',o.get('market'))
            item={'id':e['id'],'ts':e['ts'],'kind':e['kind'],'arm':p.get('arm',o.get('arm')),
                'question':title(market) if market else None,'market':market,'side':p.get('side'),
                'reason':p.get('reason',p.get('error',p.get('status'))),'outcome':p.get('outcome'),
                'evidence_id':p.get('evidence'),'order_id':p.get('order'),
                'answers':result.get('answers'),'latency':None,'evidence':None}
            if result.get('started_at') is not None and result.get('finished_at') is not None:
                item['latency']=result['finished_at']-result['started_at']
            if item['evidence_id']:
                found=rows(db,'SELECT title,url,text,published,ts FROM evidence WHERE id=?',(item['evidence_id'],))
                item['evidence']=found[0] if found else None
            decisions.append(item)
        evidence=rows(db,'SELECT id,source,url,title,ts,published,baseline,processed FROM evidence ORDER BY ts DESC LIMIT 30')
        sources=[]
        for source in cfg['sources']:
            found=[e for e in events(db,"kind IN ('source_ok','source_error')",limit=100) if e['payload'].get('source')==source['id']]
            ok=next((e for e in found if e['kind']=='source_ok'),None)
            last=found[0] if found else None
            sources.append({'id':source['id'],'url':source['url'],'last_success':ok['ts'] if ok else None,
                'last_error':last['payload'].get('error') if last and last['kind']=='source_error' else None,
                'entries':ok['payload'].get('entries') if ok else None})
        known=D(0); unknown_cost=0; successes=0
        for (raw,) in db.execute("SELECT payload FROM events WHERE kind='judgment'"):
            p=json.loads(raw)
            if p.get('arm')=='jev':
                successes+=1
                c=p['result'].get('cost')
                if c is None: unknown_cost+=1
                else: known+=D(c)
        attempts=int(meta.get('calls_total',0))
        errors=[]
        for e in events(db,"kind LIKE '%error' OR kind IN ('rule_changed','coverage_gap')",limit=10):
            p=e['payload']
            errors.append({'ts':e['ts'],'kind':e['kind'],'market':p.get('market'),'source':p.get('source'),
                           'error':p.get('error'),'seconds':p.get('seconds')})
        markets=[]
        for key,s in specs.items():
            m=market_info.get(key,{})
            markets.append({'id':key,'question':s.get('question',m.get('question',key)),'group':s['group'],'source':s['source'],
                'accepting':m.get('accepting'),'rule_matches':m.get('signature')==s['approved_signature'] if m else None,
                'received_at':m.get('received_at'),'fee_rate':m.get('rate')})
        return {'mode':'PAPER_ONLY','server_time':now,'created_at':float(meta['created_at']),
            'experiment':cfg['experiment'],'implementation_hash':meta.get('implementation_hash'),
            'status':status,'heartbeat':heartbeat,'heartbeat_age':age,'accounts':accounts,
            'orders':orders,'fills':fills,'decisions':decisions,'evidence':evidence,'sources':sources,'markets':markets,
            'evidence_total':db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],
            'baseline_total':db.execute('SELECT COUNT(*) FROM evidence WHERE baseline=1').fetchone()[0],
            'event_counts':counts,'errors':errors,'model':{'attempts':attempts,'known_cost':str(known),
                'unknown_cost_records':unknown_cost+max(0,attempts-successes),'daily_limit':cfg['model_max_daily_calls'],
                'daily_attempts':int(meta.get('calls_'+datetime.fromtimestamp(now,timezone.utc).date().isoformat(),0)),
                'total_limit':cfg['model_max_total_calls']},
            'parameters':{k:cfg[k] for k in ('order_budget','max_exposure','max_drawdown','take_profit_fraction',
                'stop_loss_fraction','max_hold_seconds','source_poll_seconds','book_poll_seconds',
                'relevance_threshold','clarity_threshold','direction_threshold')}}
