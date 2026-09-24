'use strict';
let state=null,arm='jev',view='orders',stream=null,lastArrival=0,connected=false;
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=value=>value==null?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(value));
const num=value=>value==null?'—':Number(value).toLocaleString('en-US',{maximumFractionDigits:4});
const pct=value=>value==null?'—':`${(Number(value)*100).toFixed(0)}%`;
const date=value=>value==null?'—':new Date(value*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
const clock=value=>value==null?'—':new Date(value*1000).toLocaleTimeString('zh-CN',{hour12:false});
const relative=(value,now=state?.server_time)=>value==null?'尚无记录':`${Math.max(0,Math.floor(now-value))} 秒前`;
const safeLink=url=>{try {const u=new URL(url);return u.protocol==='https:'?esc(u.href):'#';}catch{return '#';}};
const empty=(title,body)=>`<div class="empty"><span class="empty-icon">◇</span><b>${esc(title)}</b><p>${esc(body)}</p></div>`;
const labels={judgment:'完成信号判断',entry_rejected:'放弃开仓',entry_scheduled:'已生成模拟买单',candidate_skipped:'跳过候选',paper_fill:'模拟成交',order_result:'执行结果',order_cancelled:'取消订单',execution_error:'执行异常',judgment_error:'判断异常',model_budget_skip:'模型额度已用完',interrupted_evidence_skipped:'跳过中断的消息',exit_pending:'等待退出'};
const reasons={GROUP_ALREADY_EXPOSED:'同一事件组已有持仓或订单',COOLDOWN:'同组仍在冷却期',EXPOSURE_CAP:'达到仓位预算上限',CASH_RESERVED:'可用现金不足',INVENTORY_UNPRICED:'库存无法完整估值',DRAWDOWN_PAUSE:'触及账户亏损限制',MARKET_UNHEALTHY:'市场状态或规则不满足条件',ONE_SIDED_BOOK:'盘口缺少买方或卖方',PRICE_OR_SPREAD:'价格或价差超出范围',ROUNDTRIP_COST:'预计往返成本过高',NO_BIDS:'没有可用买盘',MARKET_CHANGED_OR_CLOSED:'市场发生变化或关闭',COST_CHANGED_AT_ARRIVAL:'到达时交易成本变化',RISK_PAUSE_AT_ARRIVAL:'到达时触发风控',ONE_SIDED_AT_ARRIVAL:'到达时盘口缺少一侧',take_profit:'止盈',stop_loss:'止损',time_exit:'持仓超时',opposite_evidence:'出现反向证据',exit_retry:'重试退出',signal:'方向信号',PENDING:'待执行',EXECUTED:'已执行（可能部分）',EXPIRED:'已过期',CANCELLED:'已取消',NO_FILL:'未成交',DUST:'不足最小订单量'};
function setNumber(id,value){const el=$(id);el.textContent=money(value);el.classList.toggle('positive',Number(value)>0);el.classList.toggle('negative',Number(value)<0);}
function table(headers,body){return `<table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table>`;}
function sideTag(outcome){return `<span class="tag ${outcome==='NO'?'no':''}">${esc(outcome||'未知')}</span>`;}
function render(){
 if(!state)return;
 const a=state.accounts[arm];if(!a)return;
 $('equity').textContent=money(a.equity);$('cash').textContent=money(a.cash);setNumber('pnl',a.total_pnl);
 $('equity-note').textContent=Number(a.unpriced_shares)>0?'存在未估值库存 · 当前为保守下界':'现金 + 可清算持仓（已扣退出费用）';
 $('cash-note').textContent=`可用 ${money(a.available_cash)} · 预留 ${money(a.reserved)}`;
 $('pnl-note').textContent=`相对初始 ${money(a.initial_cash)} · 模型费用另计`;
 $('position-count').textContent=String(a.positions.length).padStart(2,'0');$('holdings-count').textContent=a.positions.length;
 $('position-note').textContent=`持仓成本 ${money(a.inventory_cost)} / 上限 ${money(state.parameters.max_exposure)}`;
 setNumber('realized',a.realized);setNumber('unrealized',a.unrealized);setNumber('daily',a.daily_pnl);
 $('daily-note').textContent=a.daily_complete?'UTC 当日完整观察窗口':`非完整日数据 · 起点 ${date(a.daily_start)}`;
 $('evidence-count').textContent=state.evidence_total-state.baseline_total;
 $('judge-note').textContent=arm==='jev'?'Jev 结构化判断':'固定文本匹配规则';
 // Flow counters deliberately distinguish all-account totals from the selected account.
 $('judgment-count').textContent=state.event_counts.judgment||0;
 $('rejected-count').textContent=state.event_counts.entry_rejected||0;
 $('fill-count').textContent=Object.values(state.accounts).reduce((n,a)=>n+(a.orders.EXECUTED||0),0);
 $('pipeline-note').textContent=`全实验统计：${state.baseline_total} 条旧消息仅建立基线；${state.evidence_total-state.baseline_total} 条后续消息。判断、拒绝与执行数量含两个独立账户，不代表独立事件数。`;
 $('positions-content').innerHTML=a.positions.length?table(['市场 / 方向','份额','成本均价 / 份','持仓成本','开仓时间','状态'],a.positions.map(p=>`<tr><td class="market-cell">${esc(p.question)} ${sideTag(p.outcome)}</td><td class="numeral">${num(p.qty)}</td><td class="numeral">${money(p.average_cost)}</td><td class="numeral">${money(p.cost)}</td><td>${date(p.opened)}</td><td>${p.exit_pending?'等待卖出':'持有中'}</td></tr>`).join('')):empty('当前没有持仓','等待新的相关证据，并通过方向、交易成本和风险筛选后，bot 才会尝试开仓。');
 renderChart();renderTimeline();renderExecution();
 $('source-health').innerHTML=state.sources.map(s=>{const ok=!s.last_error&&s.last_success&&state.server_time-s.last_success<180;return `<span class="source-pill"><i class="dot ${ok?'ok':'bad'}"></i>${esc(s.id==='apple'?'Apple':s.id==='take2'?'Take-Two':s.id)} · ${s.last_error?esc(s.last_error):relative(s.last_success)}</span>`;}).join('');
 $('news').innerHTML=state.evidence.length?state.evidence.slice(0,12).map(e=>`<article class="news-item"><a href="${safeLink(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ↗</a><div class="news-meta"><span>${esc(e.source)}</span><span>收到 ${date(e.ts)}</span><span class="baseline">${e.baseline?'历史基线 · 不交易':e.processed===-1?'中断后跳过':'后续消息 · 不等于交易信号'}</span></div></article>`).join(''):empty('等待第一批消息','源首次加载会建立基线，旧消息不会触发交易。');
 $('market-count').textContent=`${state.markets.length} 个合约`;
 $('markets').innerHTML=state.markets.map(m=>{const fresh=m.received_at&&state.server_time-m.received_at<120;const ok=fresh&&m.accepting&&m.rule_matches;return `<div class="market-row"><i class="dot ${ok?'ok':'bad'}"></i><div><p>${esc(m.question)}</p><small>${esc(m.group)} · ${!fresh?'数据过期或未加载':!m.rule_matches?'规则变化':!m.accepting?'暂停接受订单':'市场开放 · 仍需策略筛选'}</small></div></div>`;}).join('');
 const p=state.parameters,m=state.model;
 const pairs=[['每笔预算',money(p.order_budget)],['总成本上限',money(p.max_exposure)],['相对初始资金亏损暂停',money(p.max_drawdown)],['止盈 / 止损',`${pct(p.take_profit_fraction)} / ${pct(p.stop_loss_fraction)}`],['最长持仓',`${p.max_hold_seconds/3600} 小时`],['今日 Jev 尝试',`${m.daily_attempts} / ${m.daily_limit}`],['累计 Jev 尝试',`${m.attempts} / ${m.total_limit}`],['已知模型费用',money(m.known_cost)],['费用未知的调用',`${m.unknown_cost_records} 次`],['消息 / 持仓盘口',`${p.source_poll_seconds}s / ${p.book_poll_seconds}s`],['实验开始',date(state.created_at)],['推送方式',`SSE / ${state.stream?.observer||'snapshot'}`]];
 $('parameters').innerHTML=pairs.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
 $('errors').innerHTML=state.errors.length?`<p class="muted small">最近异常记录（历史记录不代表当前仍异常）</p>`+state.errors.slice(0,4).map(e=>`<div class="error-row">${date(e.ts)} · ${esc(e.kind)} ${esc(e.error||'')} ${e.seconds?`${Math.round(e.seconds)} 秒观测缺口`:''}</div>`).join(''):'<p class="muted small">目前没有记录到异常。</p>';
 $('experiment').textContent=state.experiment;
 renderStatus();
}
function renderStatus(){
 $('connection').className=`dot ${connected?'ok':'bad'}`;
 $('connection-text').textContent=connected?'SSE 已连接':'连接中断 · 正在重连';
 if(!state)return;
 const elapsed=(Date.now()-lastArrival)/1000,now=state.server_time+elapsed;
 const stale=state.heartbeat==null||now-state.heartbeat>120||now<state.heartbeat;
 const status=state.status==='stopped'?'stopped':stale?'stale':state.status;
 $('bot-status').textContent=({running:'● Bot 心跳正常',stopped:'■ Bot 已停止',stale:'! Bot 心跳过期',waiting:'◌ 等待 Bot 启动'})[status];
 $('bot-status').className=`badge ${status==='running'?'':'warn'}`;
 $('heartbeat').textContent=`最近心跳 ${relative(state.heartbeat,now)}`;
 $('updated').textContent=`状态推送 ${clock(state.server_time)} · 时间为本地时区`;
 const a=state.accounts[arm],warnings=[];
 if(!connected)warnings.push('推送连接中断，当前保留的是上一次数据；浏览器正在重连。');
 if(status!=='running')warnings.push('Bot 心跳已停止或过期，页面在线不代表策略仍在运行。');
 if(Number(a?.unpriced_shares)>0)warnings.push(`有 ${num(a.unpriced_shares)} 份库存无法估值；净值和未实现盈亏是保守下界。`);
 if(a?.mark_ts&&now-a.mark_ts>60)warnings.push('估值时间已过期，请勿把旧数值当成当前可成交价格。');
 $('alert').hidden=!warnings.length;$('alert').textContent=warnings.join(' ');
}
function renderTimeline(){
 const filter=$('activity-filter').value;
 const list=state.decisions.filter(e=>(!e.arm||e.arm===arm)&&(filter==='all'||(filter==='judgment'&&e.kind==='judgment')||(filter==='rejected'&&/rejected|skipped|error|budget/.test(e.kind))||(filter==='execution'&&/scheduled|fill|order|exit/.test(e.kind))));
 const opened=new Set([...document.querySelectorAll('.event[open]')].map(e=>e.dataset.id));
 $('timeline').innerHTML=list.length?list.map(e=>{
  const answers=e.answers,ev=e.evidence;
  let explanation=reasons[e.reason]||e.reason||'';
  if(e.kind==='judgment') explanation=e.side?`方向支持 ${e.side}，继续检查盘口和风险`:'没有产生可用信号：弃权或未通过筛选门槛';
  const score=answers?`<div class="scores"><span>相关 ${pct(answers.relevant.probability)}</span><span>清晰 ${pct(answers.clear.probability)}</span><span>${esc(answers.direction.choice)} ${pct(answers.direction.probabilities[answers.direction.choice])}</span></div><p>分类概率不是事件发生概率；阈值为相关 90%、清晰 80%、方向 80%。</p>`:'';
  return `<details class="event" data-id="${e.id}" ${opened.has(String(e.id))?'open':''}><summary><div><div class="event-title">${esc(labels[e.kind]||e.kind)}${e.outcome?' · '+esc(e.outcome):''}</div><p class="event-sub">${esc(e.question||explanation||'系统事件')}</p></div><time>${clock(e.ts)}</time></summary><div class="event-detail"><p>${esc(explanation)}</p>${score}${e.latency!=null?`<p>模型请求耗时 ${e.latency.toFixed(3)} 秒</p>`:''}${ev?`<p><a href="${safeLink(ev.url)}" target="_blank" rel="noopener noreferrer">${esc(ev.title)} ↗</a></p><p>发布时间 ${date(ev.published)} · 收到时间 ${date(ev.ts)}</p><p>${esc(ev.text)}</p>`:'<p>该事件没有附带新的消息证据。</p>'}</div></details>`;
 }).join(''):empty('尚无符合筛选的决策','这里只展示真实记录。收到相关的新消息后，判断、放弃和成交过程会自动出现。');
}
function renderExecution(){
 const list=state[view].filter(o=>o.arm===arm);
 if(!list.length){$('execution-content').innerHTML=empty(view==='orders'?'尚无模拟订单':'尚无模拟成交','仅有方向判断还不够；交易成本、风险检查和到达时的盘口都会影响成交。');return;}
 $('execution-content').innerHTML=view==='orders'?table(['决定时间','市场','操作','限价','预算','状态','原因'],list.map(o=>`<tr><td>${date(o.decision)}</td><td class="market-cell">${esc(o.question)}</td><td>${o.side==='BUY'?'买入':'卖出'} ${sideTag(o.outcome)}</td><td class="numeral">${num(o.price_limit)}</td><td>${o.side==='BUY'?money(o.budget):'卖出持仓'}</td><td>${esc(reasons[o.status]||o.status)}</td><td>${esc(reasons[o.reason]||o.reason)}</td></tr>`).join('')):table(['成交时间','市场','操作','份额','价格','手续费','现金变动'],list.map(f=>`<tr><td>${date(f.ts)}</td><td class="market-cell">${esc(f.question)}</td><td>${f.side==='BUY'?'买入':'卖出'} ${sideTag(f.outcome)}</td><td class="numeral">${num(f.qty)}</td><td class="numeral">${num(f.price)}</td><td class="numeral">${num(f.fee)}</td><td class="numeral">${money(f.cash_delta)}</td></tr>`).join(''));
}
function renderChart(){
 const series=Object.entries(state.accounts).map(([name,a])=>[name,a.history]);
 const points=series.flatMap(([,h])=>h);
 if(!points.length){$('chart').innerHTML='<text x="300" y="95">等待第一笔估值记录</text>';return;}
 const xs=points.map(p=>p.ts),ys=points.map(p=>Number(p.equity));
 const lo=Math.min(...xs),hi=Math.max(...xs),ylo=Math.min(...ys),yhi=Math.max(...ys),pad=Math.max((yhi-ylo)*.2,1);
 const x=v=>64+(v-lo)/Math.max(1,hi-lo)*710,y=v=>160-(v-(ylo-pad))/(yhi-ylo+pad*2)*140;
 let svg='';
 for(let i=0;i<4;i++){let value=ylo-pad+(yhi-ylo+pad*2)*i/3,cy=y(value);svg+=`<line class="grid" x1="64" x2="775" y1="${cy}" y2="${cy}"/><text x="3" y="${cy+4}">${value.toFixed(2)}</text>`;}
 for(const [name,h]of series){let d='';h.forEach((p,i)=>{const gap=i&&p.ts-h[i-1].ts>420;d+=`${!i||gap?'M':'L'}${x(p.ts).toFixed(2)},${y(Number(p.equity)).toFixed(2)} `;});svg+=`<path class="series ${name==='jev'?'jev':'rules'}" d="${d}"/>`;if(h.length){const p=h[h.length-1];svg+=`<circle class="point-${name==='jev'?'jev':'rules'}" cx="${x(p.ts)}" cy="${y(Number(p.equity))}" r="3"/>`;}}
 $('chart').innerHTML=svg;$('chart-start').textContent=date(lo);$('chart-end').textContent=date(hi);
 $('chart-note').textContent=points.some(p=>Number(p.unpriced_qty)>0)?'含无法估值库存的下界':'仅展示真实观测点';
}
function connect(){
 if(stream)stream.close();
 connected=false;renderStatus();
 stream=new EventSource('/api/events');
 stream.addEventListener('state',e=>{try{state=JSON.parse(e.data);lastArrival=Date.now();connected=true;render();}catch{connected=false;renderStatus();}});
 stream.addEventListener('unavailable',()=>{connected=false;renderStatus();$('alert').hidden=false;$('alert').textContent='账本暂时不可用或正在初始化。等待服务器恢复推送；不显示虚构余额。';});
 stream.onerror=()=>{connected=false;renderStatus();};
}
document.querySelectorAll('[data-arm]').forEach(b=>b.addEventListener('click',()=>{arm=b.dataset.arm;document.querySelectorAll('[data-arm]').forEach(x=>{x.classList.toggle('selected',x===b);x.setAttribute('aria-pressed',String(x===b));});render();}));
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{view=b.dataset.view;document.querySelectorAll('[data-view]').forEach(x=>{x.classList.toggle('selected',x===b);x.setAttribute('aria-pressed',String(x===b));});if(state)renderExecution();}));
$('activity-filter').addEventListener('change',()=>{if(state)renderTimeline();});$('refresh').addEventListener('click',connect);
// This timer only ages the on-screen freshness label; it performs no HTTP request.
setInterval(()=>{if(lastArrival&&Date.now()-lastArrival>35000)connected=false;renderStatus();},1000);
window.addEventListener('pagehide',()=>stream?.close());
window.addEventListener('pageshow',e=>{if(e.persisted)connect();});
connect();
