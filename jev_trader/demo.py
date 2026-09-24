"""Deterministic synthetic end-to-end demonstration, never a backtest."""
import copy
import json
from pathlib import Path
from .core import digest
from .engine import Bot
from .report import report


class FixtureAPI:
    def __init__(self, clock):
        self.clock=clock
        self.news=[]
        self.bid='0.39'
        self.ask='0.40'
        self.size='100'

    def market(self,spec):
        return {'id':spec['id'],'signature':'fixture','question':'Device publicly available?',
                'rule':'YES if device publicly available by the deadline.', 'tokens':{'YES':'yes','NO':'no'},
                'condition_id':'fixture','accepting':True,'closed':False,'rate':'0.05','minimum':'5',
                'tick':'0.01','end':self.clock()+99999,'received_at':self.clock()}

    def book(self, token):
        b={'asset_id':token,'bids':[{'price':self.bid,'size':self.size}],
           'asks':[{'price':self.ask,'size':self.size}],'received_at':self.clock(),'timestamp':'fixture'}
        b['content_hash']=digest({k:b[k] for k in ('asset_id','bids','asks')})
        return b

    def get(self,url):
        return b'fixture'

    def parse_feed(self,data,source):
        return copy.deepcopy(self.news)

    def judge(self,m,e,previous=''):
        return {'fixture':True,'started_at':self.clock(),'finished_at':self.clock(),'cost':'0','usage':{},
                'answers':{'relevant':{'probability':1},'clear':{'probability':1},
                           'direction':{'choice':'SUPPORTS_YES','probabilities':{'SUPPORTS_YES':1,'SUPPORTS_NO':0,'NO_SIGNAL':0}}}}

    def rule_signal(self,spec,e):
        return 'YES'


def fixture_config():
    config=json.loads((Path(__file__).resolve().parents[1]/'config/paper.json').read_text())
    config['experiment']='SYNTHETIC_DEMO_NOT_STRATEGY_PNL'
    config['max_roundtrip_fraction']='0.10'
    config['markets']=[{'id':'fixture','source':'fixture','group':'fixture','keywords':['device'],
                        'approved_signature':'fixture'}]
    config['sources']=[{'id':'fixture','url':'fixture','article_hosts':[]}]
    config['source_poll_seconds']=1
    config['book_poll_seconds']=1
    config['metadata_poll_seconds']=1
    return config


def demo(output):
    output=Path(output)/'synthetic-demo'
    output.mkdir(parents=True,exist_ok=True)
    path=output/'demo.sqlite'
    if path.exists():
        raise ValueError('Demo database exists; choose a new --output directory')
    t=[2_000_000_000.0]
    clock=lambda:t[0]
    api=FixtureAPI(clock)
    bot=Bot(fixture_config(),path,api,clock)
    bot.cycle()  # First observation creates source baseline, no trade.
    t[0]+=2
    api.news=[{'id':'fixture-update','source':'fixture','url':'fixture','published':t[0],
               'title':'Device available','text':'Official: device is now available.'}]
    bot.cycle()  # Rules and mocked Jev schedule entries.
    t[0]+=3;bot.cycle()  # Arrival-time ask executes, real-like cash/fee/depth logic.
    api.bid='0.49';api.ask='0.50'
    t[0]+=3;bot.cycle()  # Take-profit schedules closing orders.
    t[0]+=3;bot.cycle()  # Sell holdings at bids, no complementary-token shortcut.
    bot.mark_and_exit()
    result=report(path,output,clock())
    assert all(not a['open_positions'] for a in result['accounts'].values())
    assert bot.db.execute('SELECT COUNT(*) FROM fills').fetchone()[0]==4
    bot.db.close()
    print(json.dumps({'synthetic_only':True,'round_trips':2,'report':str(output/'latest.md')},indent=2))
