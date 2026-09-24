"""Decimal order-book simulation and transactional paper ledger."""
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import hashlib
import json
import sqlite3
import time

D = Decimal
UNIT = D('0.000001')


def dec(value):
    result = D(str(value))
    if not result.is_finite():
        raise ValueError('Non-finite number')
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def levels(raw, side):
    values = {}
    for row in raw.get(side, []):
        p, q = dec(row['price']), dec(row['size'])
        if not 0 < p < 1 or q < 0:
            raise ValueError('Invalid book level')
        values[p] = values.get(p, D(0)) + q
    return sorted(values.items(), reverse=side == 'bids')


def liquidity_hash(book, side):
    name = 'asks' if side == 'BUY' else 'bids'
    return digest({'token':book['asset_id'],'side':name,
                   'levels':[(str(p),str(q)) for p,q in levels(book,name)]})


def fee(qty, price, rate):
    # Cash-equivalent fee model; round up to micro-dollar conservatively.
    return (qty * rate * price * (1-price)).quantize(UNIT, rounding=ROUND_UP)


def simulate(book, side, limit, rate, haircut, budget=None, quantity=None, consumed=None):
    """Taker FAK: no fill outside limit, never use midpoint, partial fills allowed."""
    limit, rate, haircut = map(dec, (limit, rate, haircut))
    if side not in ('BUY', 'SELL') or not 0 <= rate <= 1 or not 0 < haircut <= 1:
        raise ValueError('Unsupported fill parameters')
    available = dec(budget) if side == 'BUY' else dec(quantity)
    if available < 0:
        raise ValueError('Negative order size')
    fills = []
    for p, raw_qty in levels(book, 'asks' if side == 'BUY' else 'bids'):
        if (side == 'BUY' and p > limit) or (side == 'SELL' and p < limit):
            break
        capacity = max(D(0), raw_qty * haircut - dec((consumed or {}).get(str(p), 0)))
        if side == 'BUY':
            # Reserve one fee quantum before sizing, then round quantity down.
            q = min(capacity, max(D(0),available-UNIT) / (p + rate*p*(1-p)))
        else:
            q = min(capacity, available)
        q = q.quantize(UNIT, rounding=ROUND_DOWN)
        if q <= 0:
            continue
        f = fee(q, p, rate)
        # Rounding up the fee must never overspend a micro-dollar budget.
        if side == 'BUY' and q*p+f > available:
            q = max(D(0), q-UNIT)
            f = fee(q, p, rate)
        if q <= 0 or (side == 'BUY' and q*p+f > available):
            continue
        fills.append({'price': str(p), 'quantity': str(q), 'fee': str(f)})
        available -= q*p+f if side == 'BUY' else q
        if available <= 0:
            break
    return fills


class Store:
    def __init__(self, path, config, now=None):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS accounts(arm TEXT PRIMARY KEY, cash TEXT NOT NULL, realized TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY, arm TEXT, market TEXT, token TEXT,
            event_group TEXT, qty TEXT, cost TEXT, opened REAL, updated REAL, exit_pending INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, arm TEXT, market TEXT, token TEXT,
            event_group TEXT, side TEXT, price_limit TEXT, budget TEXT, position_id INTEGER,
            decision REAL, due REAL, expires REAL, status TEXT, reason TEXT);
        CREATE TABLE IF NOT EXISTS fills(id INTEGER PRIMARY KEY, order_id TEXT, ts REAL, price TEXT,
            qty TEXT, fee TEXT, cash_delta TEXT, book_hash TEXT);
        CREATE TABLE IF NOT EXISTS consumed(arm TEXT, token TEXT, book_hash TEXT, side TEXT,
            price TEXT, qty TEXT, PRIMARY KEY(arm,token,book_hash,side,price));
        CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, source TEXT, url TEXT, ts REAL,
            published REAL, title TEXT, text TEXT, baseline INTEGER, processed INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS valuations(id INTEGER PRIMARY KEY, ts REAL, arm TEXT, cash TEXT,
            inventory_cost TEXT, liquidation TEXT, equity TEXT, unpriced_qty TEXT);
        ''')
        config_hash = digest(config)
        existing = self.get('config_hash')
        if existing and existing != config_hash:
            self.db.close()
            raise ValueError('Config changed: start a new database/experiment')
        with self.db:
            self.set('config_hash', config_hash)
            if not self.get('created_at'):
                self.set('created_at', str(now if now is not None else time.time()))
                self.set('config', json.dumps(config))
            for arm in config['arms']:
                self.db.execute('INSERT OR IGNORE INTO accounts VALUES(?,?,?)',
                                (arm, config['initial_cash'], '0'))

    def get(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def set(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, str(value)))

    def event(self, kind, payload, now=None):
        self.db.execute('INSERT INTO events(ts,kind,payload) VALUES(?,?,?)',
                        (time.time() if now is None else now, kind, json.dumps(payload)))

    def consumption(self, arm, token, book_hash, side):
        return {r['price']:r['qty'] for r in self.db.execute(
            'SELECT price,qty FROM consumed WHERE arm=? AND token=? AND book_hash=? AND side=?',
            (arm, token, book_hash, side))}

    def execute(self, order_id, book, rate, minimum, config, now):
        """Order state, fills, cash, holdings, consumed depth: one atomic commit."""
        with self.db:
            o = self.db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            if o is None or o['status'] != 'PENDING':
                return 'ALREADY_HANDLED'
            if now < o['due']:
                return 'NOT_DUE'
            if now > o['expires']:
                self.db.execute("UPDATE orders SET status='EXPIRED' WHERE id=?", (order_id,))
                return 'EXPIRED'
            if book['asset_id'] != o['token'] or now-book['received_at'] > config['max_book_age_seconds'] or now < book['received_at']:
                raise ValueError('Wrong or stale snapshot')
            account = self.db.execute('SELECT * FROM accounts WHERE arm=?', (o['arm'],)).fetchone()
            cash = dec(account['cash'])
            position = None
            if o['side'] == 'SELL':
                position = self.db.execute('SELECT * FROM positions WHERE id=?', (o['position_id'],)).fetchone()
                if not position or dec(position['qty']) <= 0:
                    self.db.execute("UPDATE orders SET status='CANCELLED' WHERE id=?", (order_id,))
                    return 'CANCELLED'
                if dec(position['qty']) < dec(minimum):
                    self.db.execute("UPDATE orders SET status='DUST' WHERE id=?", (order_id,))
                    return 'DUST'
            capacity_hash = liquidity_hash(book,o['side'])
            fills = simulate(book, o['side'], o['price_limit'], rate, config['depth_fraction'],
                             budget=min(dec(o['budget']),cash) if o['side']=='BUY' else None,
                             quantity=position['qty'] if position else None,
                             consumed=self.consumption(o['arm'],o['token'],capacity_hash,o['side']))
            qty = sum((dec(f['quantity']) for f in fills), D(0))
            # Conservative: reject an opening fill below the venue minimum.
            if not fills or (o['side']=='BUY' and qty < dec(minimum)):
                self.db.execute("UPDATE orders SET status='NO_FILL' WHERE id=?", (order_id,))
                return 'NO_FILL'
            gross = sum((dec(f['quantity'])*dec(f['price']) for f in fills), D(0))
            fees = sum((dec(f['fee']) for f in fills), D(0))
            delta = -gross-fees if o['side']=='BUY' else gross-fees
            if cash+delta < 0:
                raise ValueError('Cash invariant violated')
            realized = dec(account['realized'])
            if o['side']=='BUY':
                self.db.execute('INSERT INTO positions(arm,market,token,event_group,qty,cost,opened,updated) VALUES(?,?,?,?,?,?,?,?)',
                    (o['arm'],o['market'],o['token'],o['event_group'],str(qty),str(-delta),now,now))
            else:
                fraction = qty/dec(position['qty'])
                released = dec(position['cost'])*fraction
                realized += delta-released
                self.db.execute('UPDATE positions SET qty=?,cost=?,updated=? WHERE id=?',
                    (str(dec(position['qty'])-qty),str(dec(position['cost'])-released),now,position['id']))
            self.db.execute('UPDATE accounts SET cash=?,realized=? WHERE arm=?',
                            (str(cash+delta),str(realized),o['arm']))
            for f in fills:
                old = self.consumption(o['arm'],o['token'],capacity_hash,o['side']).get(f['price'],0)
                self.db.execute('INSERT OR REPLACE INTO consumed VALUES(?,?,?,?,?,?)',
                    (o['arm'],o['token'],capacity_hash,o['side'],f['price'],str(dec(old)+dec(f['quantity']))))
                fd = dec(f['quantity'])*dec(f['price'])
                fd = -fd-dec(f['fee']) if o['side']=='BUY' else fd-dec(f['fee'])
                self.db.execute('INSERT INTO fills(order_id,ts,price,qty,fee,cash_delta,book_hash) VALUES(?,?,?,?,?,?,?)',
                    (order_id,now,f['price'],f['quantity'],f['fee'],str(fd),book['content_hash']))
            self.db.execute("UPDATE orders SET status='EXECUTED' WHERE id=?", (order_id,))
            self.event('paper_fill', {'order':order_id,'side':o['side'],'qty':str(qty),'cash_delta':str(delta)},now)
            return 'EXECUTED'
