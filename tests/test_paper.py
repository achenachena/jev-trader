import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from jev_trader.core import D, Store, dec, fee, simulate
from jev_trader.demo import FixtureAPI, fixture_config
from jev_trader.engine import Bot
from jev_trader.adapters import parse_feed
from unittest.mock import patch


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.t=[2_000_000_000.0]
        self.clock=lambda:self.t[0]
        self.api=FixtureAPI(self.clock)
        self.config=fixture_config()
        self.bot=Bot(self.config,':memory:',self.api,self.clock)

    def tearDown(self):
        self.bot.db.close()

    def news(self):
        return {'id':'new','source':'fixture','url':'fixture','published':self.clock(),
                'title':'device released','text':'device now available'}

    def open(self):
        self.bot.cycle()
        self.t[0]+=2;self.api.news=[self.news()];self.bot.cycle()
        self.t[0]+=3;self.bot.cycle()

    def test_walks_depth_and_limit_without_midpoint(self):
        b={'asks':[{'price':'.6','size':'10'},{'price':'.4','size':'2'}]}
        f=simulate(b,'BUY','.5','0','1',budget='10')
        self.assertEqual(sum(dec(x['quantity']) for x in f),D(2))
        self.assertEqual(f[0]['price'],'0.4')

    def test_fee_and_budget_never_overspend(self):
        self.assertEqual(fee(D(100),D('.5'),D('.05')),D('1.25'))
        for price in ('.01','.13','.5','.99'):
            f=simulate({'asks':[{'price':price,'size':'100000'}]},'BUY','1','.05','.5',budget='10')
            self.assertLessEqual(sum(dec(x['price'])*dec(x['quantity'])+dec(x['fee']) for x in f),D(10))

    def test_baseline_and_duplicate_news_never_trade(self):
        self.api.news=[self.news()];self.bot.cycle()
        self.t[0]+=10;self.bot.cycle()
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)

    def test_open_close_cash_reconciles_and_idempotent(self):
        self.open()
        self.assertEqual(len(self.bot.open_positions()),2)
        order=self.bot.db.execute("SELECT id FROM orders WHERE side='BUY' LIMIT 1").fetchone()[0]
        self.assertEqual(self.bot.store.execute(order,self.api.book('yes'),'.05','5',self.config,self.clock()),'ALREADY_HANDLED')
        self.api.bid='.49';self.api.ask='.5'
        self.t[0]+=3;self.bot.cycle();self.t[0]+=3;self.bot.cycle()
        self.assertEqual(len(self.bot.open_positions()),0)
        for a in self.bot.db.execute('SELECT * FROM accounts'):
            self.assertEqual(dec(a['cash'])-1000,dec(a['realized']))
            flow=sum((dec(r[0]) for r in self.bot.db.execute('SELECT cash_delta FROM fills JOIN orders ON orders.id=fills.order_id WHERE arm=?',(a['arm'],))),D(0))
            self.assertEqual(dec(a['cash']),1000+flow)

    def test_arrival_price_move_prevents_fill(self):
        self.bot.cycle();self.t[0]+=2;self.api.news=[self.news()];self.bot.cycle()
        self.api.ask='.6';self.api.bid='.59';self.t[0]+=3;self.bot.cycle()
        self.assertEqual(len(self.bot.open_positions()),0)

    def test_partial_exit_keeps_inventory(self):
        self.open();self.api.bid='.49';self.api.ask='.5';self.api.size='12'
        self.t[0]+=15000;self.bot.cycle();self.t[0]+=3;self.bot.cycle()
        self.assertEqual(len(self.bot.open_positions()),2)
        self.assertTrue(all(dec(p['qty'])>0 for p in self.bot.open_positions()))
        old=[p['qty'] for p in self.bot.open_positions()]
        self.t[0]+=3;self.bot.cycle();self.t[0]+=3;self.bot.cycle()
        # Same snapshot depth cannot be consumed a second time by the same arm.
        self.assertEqual(old,[p['qty'] for p in self.bot.open_positions()])

    def test_no_bids_does_not_fabricate_exit(self):
        self.open()
        original=self.api.book
        def no_bids(token):
            b=original(token);b['bids']=[];b['content_hash']='empty';return b
        self.api.book=no_bids;self.t[0]+=15000;self.bot.cycle()
        self.assertEqual(len(self.bot.open_positions()),2)
        v=self.bot.db.execute('SELECT * FROM valuations ORDER BY id DESC LIMIT 1').fetchone()
        self.assertGreater(dec(v['unpriced_qty']),0)

    def test_transaction_rollback_on_fill_write_failure(self):
        self.bot.cycle();self.t[0]+=2;self.api.news=[self.news()];self.bot.cycle();self.t[0]+=3
        self.bot.db.execute("CREATE TRIGGER fail_fill BEFORE INSERT ON fills BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        order=self.bot.db.execute('SELECT id FROM orders LIMIT 1').fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.bot.store.execute(order,self.api.book('yes'),'.05','5',self.config,self.clock())
        self.assertEqual(len(self.bot.open_positions()),0)
        self.assertTrue(all(dec(r[0])==1000 for r in self.bot.db.execute('SELECT cash FROM accounts')))

    def test_expired_order_not_filled_after_restart_gap(self):
        self.bot.cycle();self.t[0]+=2;self.api.news=[self.news()];self.bot.cycle()
        self.t[0]+=100;self.bot.cycle()
        self.assertEqual(len(self.bot.open_positions()),0)
        self.assertEqual(self.bot.db.execute("SELECT COUNT(*) FROM orders WHERE status='EXPIRED'").fetchone()[0],2)

    def test_config_change_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.sqlite';s=Store(p,self.config);s.db.close()
            changed=copy.deepcopy(self.config);changed['order_budget']='11'
            with self.assertRaises(ValueError):Store(p,changed)

    def test_model_has_no_real_order_transport(self):
        import jev_trader.adapters as a
        text=Path(a.__file__).read_text()
        self.assertNotIn('POLYMARKET_PRIVATE_KEY',text)
        self.assertNotIn('/order"',text)

    def test_atom_excerpt_and_host_allowlist(self):
        xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>News</title><link href="https://www.apple.com/newsroom/test/"/><updated>2026-09-24T01:00:00Z</updated><content>Device available</content></entry></feed>'
        items=parse_feed(xml,{'id':'apple','article_hosts':['www.apple.com']})
        self.assertEqual(items[0]['text'],'News\nDevice available')
        self.assertEqual(parse_feed(xml,{'id':'other','article_hosts':['example.com']}),[])

    def test_stale_newly_seen_article_is_not_a_trade(self):
        self.bot.cycle();self.t[0]+=2
        e=self.news();e['published']-=7200;self.api.news=[e];self.bot.cycle()
        self.assertEqual(self.bot.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)

    def test_group_limit_blocks_correlated_second_contract(self):
        self.open()
        spec=self.config['markets'][0]
        self.assertEqual(self.bot.risk_reason('jev',spec),'GROUP_ALREADY_EXPOSED')

    def test_market_rule_change_cancels_pending_entry(self):
        self.bot.cycle();self.t[0]+=2;self.api.news=[self.news()];self.bot.cycle()
        original=self.api.market
        def changed(spec):
            m=original(spec);m['signature']='changed';return m
        self.api.market=changed;self.t[0]+=3;self.bot.cycle()
        self.assertEqual(len(self.bot.open_positions()),0)
        self.assertEqual(self.bot.db.execute("SELECT COUNT(*) FROM orders WHERE status='CANCELLED'").fetchone()[0],2)

    def test_unknown_fee_curve_refused(self):
        from jev_trader.adapters import market
        raw={'conditionId':'x','outcomes':['Yes','No'],'clobTokenIds':['yes','no']}
        info={'t':[{'t':'yes','o':'Yes'},{'t':'no','o':'No'}],'fd':{'r':'.05','e':2,'to':True}}
        with patch('jev_trader.adapters.get_json',side_effect=[raw,info]):
            with self.assertRaises(ValueError):market({'id':'x'})

    def test_restart_preserves_cash_and_news_deduplication(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.sqlite';bot=Bot(self.config,path,self.api,self.clock)
            bot.cycle();self.t[0]+=2;self.api.news=[self.news()];bot.cycle();self.t[0]+=3;bot.cycle()
            balances=[tuple(r) for r in bot.db.execute('SELECT * FROM accounts ORDER BY arm')]
            orders=bot.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0];bot.db.close()
            restored=Bot(self.config,path,self.api,self.clock);restored.cycle()
            self.assertEqual(balances,[tuple(r) for r in restored.db.execute('SELECT * FROM accounts ORDER BY arm')])
            self.assertEqual(orders,restored.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0])
            restored.db.close()


if __name__=='__main__':unittest.main()
