import argparse
import fcntl
import json
from pathlib import Path
import time
import urllib.parse

from . import adapters
from .engine import Bot
from .report import report


def main():
    parser=argparse.ArgumentParser(description='Public-data paper bot. No real trading mode exists.')
    parser.add_argument('command',choices=['run','doctor','report','discover','demo'])
    parser.add_argument('--config',type=Path,default=Path('config/paper.json'))
    parser.add_argument('--db',type=Path,default=Path('data/paper.sqlite'))
    parser.add_argument('--output',type=Path,default=Path('reports/paper'))
    parser.add_argument('--cycles',type=int,default=0,help='0 runs until interrupted')
    parser.add_argument('--query',default='apple')
    args=parser.parse_args()
    if args.command=='discover':
        result=adapters.get_json('https://gamma-api.polymarket.com/public-search?'+urllib.parse.urlencode({'q':args.query,'limit_per_type':20,'events_status':'active'}))
        for event in result.get('events',[]):
            for m in event.get('markets',[]):
                if m.get('acceptingOrders') and not m.get('closed'):
                    print(json.dumps({k:m.get(k) for k in ('id','question','endDate','negRisk','liquidityNum')},ensure_ascii=False))
        return
    if args.command=='demo':
        from .demo import demo
        demo(args.output)
        return
    if args.command=='report':
        r=report(args.db,args.output)
        print(json.dumps(r,ensure_ascii=False,indent=2))
        return
    config=json.loads(args.config.read_text())
    if args.command=='doctor':
        try:
            adapters.load_key();key=True
        except ValueError:
            key=False
        print(json.dumps({'mode':config['mode'],'gateway_key_present':key,'real_order_transport':False}))
        for spec in config['markets']:
            try:
                m=adapters.market(spec)
                b=adapters.book(m['tokens']['YES'])
                print(json.dumps({'market':spec['id'],'question':m['question'],'accepting':m['accepting'],
                    'rule_matches':m['signature']==spec['approved_signature'],'fee_rate':m['rate'],
                    'yes_bids':len(b['bids']),'yes_asks':len(b['asks'])},ensure_ascii=False))
            except Exception as exc:
                print(json.dumps({'market':spec['id'],'error':type(exc).__name__}))
        for source in config['sources']:
            try:
                items=adapters.parse_feed(adapters.get(source['url']),source)
                print(json.dumps({'source':source['id'],'entries':len(items)}))
            except Exception as exc:
                print(json.dumps({'source':source['id'],'error':type(exc).__name__}))
        return
    args.db.parent.mkdir(parents=True,exist_ok=True)
    # One process per ledger. Lock is released by the OS even after a crash.
    with open(str(args.db)+'.lock','w') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another bot already owns this database')
        bot=Bot(config,args.db)
        bot.log('started',{'config_hash':bot.store.get('config_hash')})
        count=0
        try:
            while True:
                bot.cycle()
                count+=1
                # Mark after fills, so a report never mixes new cash with old inventory.
                if count==1 or count % 3==0:
                    bot.mark_and_exit()
                    r=report(args.db,args.output)
                    print(json.dumps({'cycle':count,'at':r['as_of_utc'],'evidence':r['health']['evidence_count'],
                                      'accounts':{k:v['equity_lower_bound'] for k,v in r['accounts'].items()}},ensure_ascii=False),flush=True)
                if args.cycles and count>=args.cycles:
                    break
                time.sleep(config['loop_seconds'])
        except KeyboardInterrupt:
            bot.log('stopped',{'reason':'keyboard_interrupt'})
        finally:
            bot.mark_and_exit()
            report(args.db,args.output)
            bot.db.close()


if __name__=='__main__':
    main()
