#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竞赛面板 HTML（毛玻璃质感，CoinW 专属配色）。自包含，无外部依赖。
   /contest/view 路由把 __BOOT__ 替换成首屏 snapshot JSON。"""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CoinW · ETH 竞赛</title>
<style>
  :root{
    --bg0:#060912; --bg1:#0b1226; --ink:#e9eefb; --ink-dim:#93a1c4;
    --cw-blue:#3b82f6; --cw-blue-2:#60a5fa; --cw-cyan:#22d3ee; --cw-teal:#2dd4bf;
    --up:#34d399; --down:#fb7185; --warn:#fbbf24;
    --glass:rgba(255,255,255,.055); --glass-2:rgba(255,255,255,.09);
    --stroke:rgba(255,255,255,.12); --stroke-2:rgba(255,255,255,.2);
    --shadow:0 8px 40px rgba(0,0,0,.45);
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%}
  body{
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
    color:var(--ink); background:var(--bg0); overflow-x:hidden;
    -webkit-font-smoothing:antialiased;
  }
  .bg{position:fixed;inset:0;z-index:-1;background:
    radial-gradient(900px 600px at 12% -8%, rgba(59,130,246,.28), transparent 60%),
    radial-gradient(820px 560px at 96% 4%, rgba(34,211,238,.22), transparent 58%),
    radial-gradient(1000px 700px at 50% 120%, rgba(45,212,191,.14), transparent 60%),
    linear-gradient(180deg,var(--bg1),var(--bg0));}
  .bg::after{content:"";position:absolute;inset:0;opacity:.5;
    background-image:radial-gradient(rgba(255,255,255,.04) 1px,transparent 1px);
    background-size:36px 36px;mask:linear-gradient(180deg,#000,transparent 85%);}
  .wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
  .card{background:var(--glass);border:1px solid var(--stroke);border-radius:20px;
    backdrop-filter:blur(22px) saturate(140%);-webkit-backdrop-filter:blur(22px) saturate(140%);
    box-shadow:var(--shadow);padding:20px 22px}
  .row{display:grid;gap:18px}
  @media(min-width:900px){.row.two{grid-template-columns:1fr 1fr}}

  header{display:flex;align-items:center;justify-content:space-between;gap:16px;
    flex-wrap:wrap;margin-bottom:22px}
  .brand{display:flex;align-items:center;gap:13px}
  .logo{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;
    background:linear-gradient(135deg,var(--cw-blue),var(--cw-cyan));
    box-shadow:0 6px 24px rgba(59,130,246,.5);font-weight:800;color:#04121f;font-size:18px}
  .brand h1{font-size:19px;font-weight:700;letter-spacing:.3px}
  .brand p{font-size:12px;color:var(--ink-dim);margin-top:1px}
  .meta{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .pill{padding:7px 13px;border-radius:999px;background:var(--glass-2);border:1px solid var(--stroke);
    font-size:12px;color:var(--ink-dim);display:flex;gap:7px;align-items:center}
  .pill b{color:var(--ink);font-variant-numeric:tabular-nums}
  .dot{width:7px;height:7px;border-radius:50%;background:var(--up);box-shadow:0 0 10px var(--up)}

  .vs{position:relative}
  .vs .badge{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
    width:56px;height:56px;border-radius:50%;display:none;place-items:center;font-weight:800;
    background:linear-gradient(135deg,#1b2540,#0d1426);border:1px solid var(--stroke-2);
    box-shadow:var(--shadow);z-index:2;font-size:15px;letter-spacing:1px}
  @media(min-width:900px){.vs .badge{display:grid}}
  .side-title{display:flex;align-items:center;gap:9px;margin-bottom:14px}
  .side-title .tag{font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
    padding:4px 9px;border-radius:7px}
  .tag.tv{background:rgba(34,211,238,.16);color:var(--cw-cyan);border:1px solid rgba(34,211,238,.35)}
  .tag.vps{background:rgba(59,130,246,.16);color:var(--cw-blue-2);border:1px solid rgba(59,130,246,.35)}
  .side-title h2{font-size:14px;color:var(--ink-dim);font-weight:600}
  .big{font-size:40px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-1px}
  .big small{font-size:15px;font-weight:700;margin-left:6px;color:var(--ink-dim)}
  .sub{margin-top:6px;font-size:13px;color:var(--ink-dim);font-variant-numeric:tabular-nums}
  .grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:18px}
  @media(max-width:560px){.grid4{grid-template-columns:repeat(2,1fr)}}
  .kpi{background:var(--glass-2);border:1px solid var(--stroke);border-radius:13px;padding:11px 12px}
  .kpi .k{font-size:11px;color:var(--ink-dim);letter-spacing:.4px}
  .kpi .v{margin-top:4px;font-size:16px;font-weight:700;font-variant-numeric:tabular-nums}
  .win-glow{box-shadow:0 0 0 1px rgba(52,211,153,.35),0 10px 50px rgba(52,211,153,.18)}

  .up{color:var(--up)} .down{color:var(--down)} .dim{color:var(--ink-dim)}

  .chart-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
  .chart-head h3{font-size:14px;font-weight:700}
  .legend{display:flex;gap:16px;font-size:12px;color:var(--ink-dim)}
  .legend i{display:inline-block;width:22px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
  svg{display:block;width:100%;height:230px}

  .posrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:12px;margin-top:6px}
  .posrow .kpi .v{font-size:14px}

  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th{text-align:left;color:var(--ink-dim);font-weight:600;padding:8px 8px;border-bottom:1px solid var(--stroke);
    font-size:11px;letter-spacing:.5px;text-transform:uppercase}
  td{padding:9px 8px;border-bottom:1px solid rgba(255,255,255,.06);font-variant-numeric:tabular-nums;white-space:nowrap}
  tr:last-child td{border-bottom:0}
  .badge-s{font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:6px}
  .s-long{background:rgba(52,211,153,.16);color:var(--up)}
  .s-short{background:rgba(251,113,133,.16);color:var(--down)}
  .tier{font-size:10.5px;color:var(--ink-dim);border:1px solid var(--stroke);border-radius:5px;padding:1px 5px;margin-left:5px}
  .cfg{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
  .cfg span{font-size:11.5px;color:var(--ink-dim);background:var(--glass-2);border:1px solid var(--stroke);
    padding:5px 10px;border-radius:8px}
  .empty{color:var(--ink-dim);text-align:center;padding:26px 0;font-size:13px}
  .sec{margin-top:18px}
  .sec h3{font-size:13px;color:var(--ink-dim);margin-bottom:10px;font-weight:600;letter-spacing:.5px}
</style>
</head>
<body>
<div class="bg"></div>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="logo">C</div>
      <div><h1>CoinW · ETH 竞赛</h1><p>TV 实盘战法　vs　VPS 自主指标 · 影子对比</p></div>
    </div>
    <div class="meta">
      <span class="pill"><span class="dot"></span>ETH <b id="px">--</b></span>
      <span class="pill">更新 <b id="upd">--</b></span>
      <span class="pill">已跑 <b id="days">--</b></span>
    </div>
  </header>

  <div class="row two vs">
    <div class="badge">VS</div>
    <div class="card" id="card-tv">
      <div class="side-title"><span class="tag tv">TV 实盘</span><h2>TradingView 战法 · 真钱</h2></div>
      <div class="big" id="tv-ret">--</div>
      <div class="sub" id="tv-sub">--</div>
      <div class="grid4" id="tv-kpi"></div>
    </div>
    <div class="card" id="card-vps">
      <div class="side-title"><span class="tag vps">VPS 影子</span><h2>150m 唐奇安突破 + ADX 门控 · 模拟</h2></div>
      <div class="big" id="vps-ret">--</div>
      <div class="sub" id="vps-sub">--</div>
      <div class="grid4" id="vps-kpi"></div>
    </div>
  </div>

  <div class="card sec">
    <div class="chart-head">
      <h3>累计净值曲线</h3>
      <div class="legend"><span><i style="background:var(--cw-cyan)"></i>TV 实盘</span><span><i style="background:var(--cw-blue-2)"></i>VPS 影子</span></div>
    </div>
    <svg id="chart" viewBox="0 0 1000 230" preserveAspectRatio="none"></svg>
  </div>

  <div class="card sec" id="pos-card" style="display:none">
    <h3 style="font-size:14px;font-weight:700;margin-bottom:4px">VPS 当前持仓（模拟）</h3>
    <div class="posrow" id="pos"></div>
  </div>

  <div class="row two sec">
    <div class="card">
      <div class="sec" style="margin-top:0"><h3>TV 实盘 · 最近平仓</h3></div>
      <div id="tv-tbl"></div>
    </div>
    <div class="card">
      <div class="sec" style="margin-top:0"><h3>VPS 影子 · 最近平仓</h3></div>
      <div id="vps-tbl"></div>
    </div>
  </div>

  <div class="card sec">
    <h3>策略参数</h3>
    <div class="cfg" id="cfg"></div>
  </div>
</div>

<script>
const BOOT = __BOOT__;
const fmt = (n,d=2)=> (n==null||isNaN(n))?'--':Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const sign = n => (n>0?'+':'')+fmt(n);
const cls = n => n>0?'up':(n<0?'down':'dim');
const ago = ts => { if(!ts) return '--'; const s=Math.max(0,(Date.now()/1000-ts)); if(s<60)return Math.floor(s)+'s前'; if(s<3600)return Math.floor(s/60)+'分前'; if(s<86400)return Math.floor(s/3600)+'时前'; return Math.floor(s/86400)+'天前'; };
const dur = ts => { if(!ts) return '--'; const d=(Date.now()/1000-ts)/86400; return d<1? (d*24).toFixed(1)+'h' : d.toFixed(1)+'d'; };
const tstr = ts => { if(!ts) return '--'; const x=new Date(ts*1000); return (x.getMonth()+1)+'/'+x.getDate()+' '+String(x.getHours()).padStart(2,'0')+':'+String(x.getMinutes()).padStart(2,'0'); };

function kpis(m){
  return [
    ['净收益 U', sign(m.net), cls(m.net)],
    ['交易', m.n, 'dim'],
    ['胜率', fmt(m.win_rate,1)+'%', m.win_rate>=50?'up':'dim'],
    ['盈亏比', fmt(m.profit_factor,2), m.profit_factor>=1?'up':'down'],
    ['均盈 U', fmt(m.avg_win), 'up'],
    ['均亏 U', fmt(m.avg_loss), 'down'],
    ['期望 U', sign(m.expectancy,2), cls(m.expectancy)],
    ['最大回撤 U', fmt(m.max_dd), 'down'],
  ];
}
function paintKpi(el,m){
  el.innerHTML = kpis(m).map(([k,v,c])=>`<div class="kpi"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join('');
}

function curve(pts,color,W,H,lo,hi,t0,t1){
  if(!pts||pts.length<2) return '';
  const x=t=> t1>t0? (t-t0)/(t1-t0)*W : W/2;
  const y=v=> hi>lo? H-8-((v-lo)/(hi-lo))*(H-16) : H/2;
  let d='M '+x(pts[0][0]).toFixed(1)+' '+y(pts[0][1]).toFixed(1);
  for(let i=1;i<pts.length;i++) d+=' L '+x(pts[i][0]).toFixed(1)+' '+y(pts[i][1]).toFixed(1);
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`;
}

function render(s){
  document.getElementById('px').textContent = fmt(s.last_price);
  document.getElementById('upd').textContent = ago(s.updated_ts);
  document.getElementById('days').textContent = dur(s.started_ts);

  const tvm=s.tv.metrics, vm=s.shadow.metrics;
  document.getElementById('tv-ret').innerHTML = `<span class="${cls(tvm.ret_pct)}">${sign(tvm.ret_pct)}<small>%</small></span>`;
  document.getElementById('vps-ret').innerHTML = `<span class="${cls(vm.ret_pct)}">${sign(vm.ret_pct)}<small>%</small></span>`;
  document.getElementById('tv-sub').innerHTML = `净 <b class="${cls(tvm.net)}">${sign(tvm.net)} U</b> · ${tvm.n} 笔 · 基准 ${fmt(s.tv.base_equity)} U`;
  document.getElementById('vps-sub').innerHTML = `净 <b class="${cls(vm.net)}">${sign(vm.net)} U</b> · ${vm.n} 笔 · 基准 ${fmt(s.config.shadow_equity)} U`;
  paintKpi(document.getElementById('tv-kpi'),tvm);
  paintKpi(document.getElementById('vps-kpi'),vm);
  document.getElementById('card-tv').classList.toggle('win-glow', tvm.n>0 && tvm.ret_pct>vm.ret_pct);
  document.getElementById('card-vps').classList.toggle('win-glow', vm.n>0 && vm.ret_pct>tvm.ret_pct);

  // chart
  const a=s.tv.equity_curve||[], b=s.shadow.equity_curve||[];
  const all=a.concat(b);
  const svg=document.getElementById('chart');
  if(all.length<2){ svg.innerHTML=`<text x="500" y="120" fill="#93a1c4" font-size="13" text-anchor="middle">等待成交数据…</text>`; }
  else{
    const W=1000,H=230;
    const ts=all.map(p=>p[0]), vs=all.map(p=>p[1]).concat([0]);
    let lo=Math.min(...vs), hi=Math.max(...vs); if(hi===lo){hi+=1;lo-=1;}
    const pad=(hi-lo)*0.12; lo-=pad; hi+=pad;
    const t0=Math.min(...ts), t1=Math.max(...ts);
    const zeroY = hi>lo? H-8-((0-lo)/(hi-lo))*(H-16) : H/2;
    svg.innerHTML =
      `<line x1="0" y1="${zeroY.toFixed(1)}" x2="${W}" y2="${zeroY.toFixed(1)}" stroke="rgba(255,255,255,.14)" stroke-dasharray="4 5"/>`+
      curve(a,'#22d3ee',W,H,lo,hi,t0,t1)+
      curve(b,'#60a5fa',W,H,lo,hi,t0,t1)+
      `<text x="6" y="14" fill="#93a1c4" font-size="11">${fmt(hi,0)} U</text>`+
      `<text x="6" y="${H-6}" fill="#93a1c4" font-size="11">${fmt(lo,0)} U</text>`;
  }

  // open pos
  const p=s.shadow.open, pc=document.getElementById('pos-card');
  if(p){
    pc.style.display='block';
    const u = (p.side==='LONG'? (s.last_price-p.entry): (p.entry-s.last_price))*p.qty_left;
    const items=[
      ['方向', `<span class="badge-s ${p.side==='LONG'?'s-long':'s-short'}">${p.side}</span>`],
      ['档位', 'tier'+p.tier+' (ADX '+fmt(p.adx,1)+')'],
      ['进场', fmt(p.entry)], ['ATR', fmt(p.atr,2)],
      ['数量', fmt(p.qty,4)+' → '+fmt(p.qty_left,4)],
      ['TP1', fmt(p.tp1)+(p.tp1_done?' ✓':'')], ['TP2', fmt(p.tp2)+(p.tp2_done?' ✓':'')],
      ['硬止损', fmt(p.hard_sl)], ['雷达止损', p.cur_stop>0?fmt(p.cur_stop):'--'],
      ['峰值', fmt(p.best)],
      ['浮动 U', `<span class="${cls(u)}">${sign(u)}</span>`],
      ['持有', dur(p.open_ts)],
    ];
    document.getElementById('pos').innerHTML = items.map(([k,v])=>`<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
  } else pc.style.display='none';

  document.getElementById('tv-tbl').innerHTML  = tvTable(s.tv.closed);
  document.getElementById('vps-tbl').innerHTML = vpsTable(s.shadow.closed);

  const c=s.config;
  document.getElementById('cfg').innerHTML = [
    `周期 ${c.tf_min}m`, `唐奇安 ${c.donchian_n} 根`,
    `ADX 门控 ${c.adx_gate}/${c.adx_mid}/${c.adx_strong}`,
    `硬止损 ${c.hard_sl_atr_mult}×ATR`,
    `taker ${(c.taker_fee*100).toFixed(3)}% · 返佣 ${(c.rebate*100).toFixed(0)}%`,
    `模拟基准 ${fmt(c.shadow_equity,0)} U`,
  ].map(x=>`<span>${x}</span>`).join('');
}

function tvTable(rows){
  if(!rows||!rows.length) return `<div class="empty">还没有已平仓的 TV 实盘单</div>`;
  const r=rows.slice().reverse().slice(0,15);
  return `<table><thead><tr><th>开仓</th><th>方向</th><th>进→出</th><th>净 U</th><th>回报</th><th>方式</th></tr></thead><tbody>`+
    r.map(t=>`<tr><td class="dim">${tstr(t.open_ts)}</td>
      <td><span class="badge-s ${t.side==='LONG'?'s-long':'s-short'}">${t.side||'--'}</span></td>
      <td class="dim">${fmt(t.entry)} → ${fmt(t.exit)}</td>
      <td class="${cls(t.net)}">${sign(t.net)}</td>
      <td class="${cls(t.ret_pct)}">${sign(t.ret_pct)}%</td>
      <td class="dim">${t.reason||''}</td></tr>`).join('')+`</tbody></table>`;
}
function vpsTable(rows){
  if(!rows||!rows.length) return `<div class="empty">还没有已平仓的 VPS 影子单</div>`;
  const r=rows.slice().reverse().slice(0,15);
  return `<table><thead><tr><th>开仓</th><th>方向</th><th>进场</th><th>净 U</th><th>回报</th><th>出场</th></tr></thead><tbody>`+
    r.map(t=>`<tr><td class="dim">${tstr(t.open_ts)}</td>
      <td><span class="badge-s ${t.side==='LONG'?'s-long':'s-short'}">${t.side}</span><span class="tier">t${t.tier}</span></td>
      <td class="dim">${fmt(t.entry)}</td>
      <td class="${cls(t.net)}">${sign(t.net)}</td>
      <td class="${cls(t.ret_pct)}">${sign(t.ret_pct)}%</td>
      <td class="dim">${t.reason}</td></tr>`).join('')+`</tbody></table>`;
}

async function tick(){
  try{ const r=await fetch('../contest',{cache:'no-store'}); if(r.ok) render(await r.json()); }catch(e){}
}
render(BOOT);
setInterval(tick, 20000);
</script>
</body>
</html>"""
