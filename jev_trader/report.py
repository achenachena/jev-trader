"""Local reports: liquidation lower bound, incomplete marks and UTC daily change."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from .core import dec, D


def report(db_path, output, now=None):
    now=time.time() if now is None else now
    db=sqlite3.connect(db_path)
    db.row_factory=sqlite3.Row
    config=json.loads(db.execute("SELECT value FROM meta WHERE key='config'").fetchone()[0])
    day=datetime.fromtimestamp(now,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    result={'mode':'PAPER_ONLY','experiment':config['experiment'],'as_of_utc':datetime.fromtimestamp(now,timezone.utc).isoformat(),
            'accounts':{},'health':{},'fees_in_pnl':True,'model_cost_separate':True}
    result['implementation_hash']=(db.execute("SELECT value FROM meta WHERE key='implementation_hash'").fetchone() or [None])[0]
    for a in db.execute('SELECT * FROM accounts'):
        mark=db.execute('SELECT * FROM valuations WHERE arm=? ORDER BY id DESC LIMIT 1',(a['arm'],)).fetchone()
        positions=[dict(p) for p in db.execute('SELECT * FROM positions WHERE arm=?',(a['arm'],)) if dec(p['qty'])>0]
        changed=db.execute('SELECT MAX(updated) FROM positions WHERE arm=?',(a['arm'],)).fetchone()[0]
        mark_current=bool(mark and (changed is None or changed<=mark['ts']))
        beginning=db.execute('SELECT * FROM valuations WHERE arm=? AND ts<=? ORDER BY ts DESC LIMIT 1',(a['arm'],day)).fetchone()
        if beginning is None:
            beginning=db.execute('SELECT * FROM valuations WHERE arm=? ORDER BY ts LIMIT 1',(a['arm'],)).fetchone()
        # If fills happened after the last mark, old holdings cannot be combined
        # with new cash: use cash plus zero inventory as a clearly unpriced bound.
        equity=dec(mark['equity']) if mark_current else dec(a['cash'])
        cost=sum((dec(p['cost']) for p in positions),D(0))
        liquidation=dec(mark['liquidation']) if mark_current else D(0)
        account={'cash':a['cash'],'realized_pnl':a['realized'],
                 'inventory_cost':str(cost),
                 'liquidation_lower_bound':str(liquidation),
                 'equity_lower_bound':str(equity),
                 'total_pnl_lower_bound':str(equity-dec(config['initial_cash'])),
                 'unrealized_pnl_lower_bound':str(liquidation-cost),
                 'unpriced_shares':mark['unpriced_qty'] if mark_current else str(sum((dec(p['qty']) for p in positions),D(0))),
                 'valuation_matches_inventory':mark_current,
                 'mark_age_seconds':now-mark['ts'] if mark else None,
                 'daily_pnl_lower_bound':str(equity-dec(beginning['equity'])) if beginning else None,
                 'daily_window_start_utc':datetime.fromtimestamp(beginning['ts'],timezone.utc).isoformat() if beginning else None,
                 'daily_window_complete':bool(beginning and day-60<=beginning['ts']<=day),
                 'open_positions':positions,
                 'orders':{r[0]:r[1] for r in db.execute('SELECT status,COUNT(*) FROM orders WHERE arm=? GROUP BY status',(a['arm'],))}}
        result['accounts'][a['arm']]=account
    result['health']['event_counts']={r[0]:r[1] for r in db.execute('SELECT kind,COUNT(*) FROM events GROUP BY kind')}
    result['health']['evidence_count']=db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]
    result['health']['baseline_evidence_count']=db.execute('SELECT COUNT(*) FROM evidence WHERE baseline=1').fetchone()[0]
    result['health']['last_heartbeat']=db.execute("SELECT MAX(ts) FROM events WHERE kind='heartbeat'").fetchone()[0]
    result['health']['recent_errors']=[dict(r) for r in db.execute("SELECT ts,kind,payload FROM events WHERE kind LIKE '%error' OR kind IN ('rule_changed','coverage_gap') ORDER BY id DESC LIMIT 10")]
    costs=[]
    for row in db.execute("SELECT payload FROM events WHERE kind='judgment'"):
        j=json.loads(row[0])
        if j['arm']=='jev':
            costs.append(j['result'].get('cost'))
    result['model_cost_known_usd']=str(sum((dec(c) for c in costs if c is not None),D(0)))
    result['model_cost_unknown_successes']=sum(c is None for c in costs)
    result['model_attempts']=int((db.execute("SELECT value FROM meta WHERE key='calls_total'").fetchone() or ['0'])[0])
    result['model_attempts_without_successful_cost_record']=result['model_attempts']-len(costs)
    folder=Path(output); folder.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    tmp=folder/'latest.json.tmp';tmp.write_text(payload);tmp.replace(folder/'latest.json')
    lines=['# Jev Trader 模拟账户报告','',f"更新时间：{result['as_of_utc']}",'',
           '**仅模拟，没有真实下单。两个账户各自 $1,000，不能把收益相加。**','',
           '| 账户 | 现金 | 已实现盈亏 | 净值下界 | 累计盈亏下界 | 无法估值份额 |',
           '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name,a in result['accounts'].items():
        lines.append(f"| {name} | {dec(a['cash']):.4f} | {dec(a['realized_pnl']):.4f} | {dec(a['equity_lower_bound']):.4f} | {dec(a['total_pnl_lower_bound']):.4f} | {a['unpriced_shares']} |")
    lines += ['', '净值按可卖出的买盘深度、退出费用和深度折扣计算；未能估值的库存按零计下界，不等于已经亏损。',
              'UTC 日变化与估值时刻、持仓和拒单明细见 latest.json；首次启动当天为部分日期。',
              f"模型接口已报告费用：${result['model_cost_known_usd']}；无成功费用记录的尝试：{result['model_attempts_without_successful_cost_record']}。",'',
              '价格和新闻来自轮询快照。没有成交、样本不足以及来源中断均应保留，不能补造收益。','',
              '```json',json.dumps(result['health'],ensure_ascii=False,indent=2),'```']
    tmp=folder/'latest.md.tmp';tmp.write_text('\n'.join(lines)+'\n');tmp.replace(folder/'latest.md')
    db.close()
    return result
