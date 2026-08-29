#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竞赛面板 HTML —— iOS 风格「动态毛玻璃」浅色主题，CoinW 专属。
   自包含，无外部依赖。/contest/view 把 __BOOT__ 换成首屏 snapshot JSON。"""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>CoinW · ETH 竞赛</title>
<style>
  :root{
    --ink:#1c1c1e; --ink-2:#3a3a3c; --dim:#8a8a8e; --hair:rgba(60,60,67,.12);
    --ios-blue:#007aff; --ios-cyan:#32ade6; --ios-green:#30c760; --ios-red:#ff3b30;
    --ios-indigo:#5856d6;
    --glass:rgba(255,255,255,.55); --glass-2:rgba(255,255,255,.42);
    --glass-brd:rgba(255,255,255,.65);
    --shadow:0 10px 40px rgba(20,30,60,.10), 0 2px 8px rgba(20,30,60,.05);
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%}
  body{
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display",
      "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
    color:var(--ink); background:#eef1f7;
    -webkit-font-smoothing:antialiased; font-feature-settings:"tnum" 1,"cv05" 1;
    overflow-x:hidden;
  }
  /* 动态毛玻璃背景：缓慢漂移的彩色光斑 */
  .bg{position:fixed;inset:-20%;z-index:-2;filter:blur(60px) saturate(150%);opacity:.9}
  .blob{position:absolute;border-radius:50%;mix-blend-mode:normal;will-change:transform}
  .b1{width:46vw;height:46vw;left:-6vw;top:-8vw;background:radial-gradient(circle at 30% 30%,#7cc6ff,#3a8dff 60%,transparent 72%);animation:drift1 26s ease-in-out infinite}
  .b2{width:40vw;height:40vw;right:-8vw;top:-4vw;background:radial-gradient(circle at 60% 40%,#7ff0e6,#32ade6 62%,transparent 74%);animation:drift2 32s ease-in-out infinite}
  .b3{width:52vw;height:52vw;left:18vw;bottom:-24vw;background:radial-gradient(circle at 50% 50%,#c9b8ff,#8a7bff 58%,transparent 72%);animation:drift3 38s ease-in-out infinite}
  .b4{width:30vw;height:30vw;right:6vw;bottom:-10vw;background:radial-gradient(circle at 40% 60%,#ffd0e6,#ff9ecb 60%,transparent 74%);animation:drift1 30s ease-in-out infinite reverse}
  .bg-tint{position:fixed;inset:0;z-index:-1;background:linear-gradient(180deg,rgba(238,241,247,.35),rgba(238,241,247,.72))}
  @keyframes drift1{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(6vw,4vw) scale(1.08)}}
  @keyframes drift2{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-5vw,5vw) scale(1.1)}}
  @keyframes drift3{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(4vw,-5vw) scale(1.06)}}
  @media(prefers-reduced-motion:reduce){.blob{animation:none}}

  .wrap{max-width:1180px;margin:0 auto;padding:30px 20px 70px}
  .card{
    background:var(--glass);border:1px solid var(--glass-brd);border-radius:24px;
    backdrop-filter:blur(40px) saturate(200%);-webkit-backdrop-filter:blur(40px) saturate(200%);
    box-shadow:var(--shadow);padding:22px 24px;
    transition:transform .3s cubic-bezier(.2,.7,.2,1),box-shadow .3s;
  }
  .card:hover{transform:translateY(-2px);box-shadow:0 16px 50px rgba(20,30,60,.14),0 3px 10px rgba(20,30,60,.06)}
  .row{display:grid;gap:18px}
  @media(min-width:900px){.row.two{grid-template-columns:1fr 1fr}}
  .sec{margin-top:18px}

  header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:22px}
  .brand{display:flex;align-items:center;gap:14px}
  .logo{width:44px;height:44px;border-radius:14px;display:grid;place-items:center;color:#fff;font-weight:800;font-size:19px;
    background:linear-gradient(135deg,var(--ios-blue),var(--ios-cyan));
    box-shadow:0 8px 22px rgba(0,122,255,.35),inset 0 1px 0 rgba(255,255,255,.5)}
  .brand h1{font-size:20px;font-weight:700;letter-spacing:-.2px}
  .brand p{font-size:12.5px;color:var(--dim);margin-top:2px}
  .meta{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
  .pill{padding:8px 14px;border-radius:999px;background:var(--glass-2);border:1px solid var(--glass-brd);
    backdrop-filter:blur(20px);font-size:12px;color:var(--dim);display:flex;gap:7px;align-items:center;box-shadow:var(--shadow)}
  .pill b{color:var(--ink);font-weight:600}
  .dot{width:7px;height:7px;border-radius:50%;background:var(--ios-green);box-shadow:0 0 0 3px rgba(48,199,96,.2)}

  .vs{position:relative}
  .vs .badge{position:absolute;left:50%;top:120px;transform:translate(-50%,-50%);
    width:54px;height:54px;border-radius:50%;display:none;place-items:center;font-weight:800;font-size:14px;letter-spacing:1px;
    color:var(--ink-2);background:var(--glass);border:1px solid var(--glass-brd);
    backdrop-filter:blur(30px) saturate(180%);box-shadow:var(--shadow);z-index:3}
  @media(min-width:900px){.vs .badge{display:grid}}
  .side-title{display:flex;align-items:center;gap:10px;margin-bottom:14px}
  .tag{font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:5px 10px;border-radius:8px}
  .tag.tv{background:rgba(50,173,230,.16);color:#0a86b8;border:1px solid rgba(50,173,230,.3)}
  .tag.vps{background:rgba(0,122,255,.14);color:var(--ios-blue);border:1px solid rgba(0,122,255,.3)}
  .side-title h2{font-size:13.5px;color:var(--dim);font-weight:600}
  .big{font-size:42px;font-weight:800;line-height:1;letter-spacing:-1.5px}
  .big small{font-size:16px;font-weight:700;margin-left:6px;color:var(--dim)}
  .sub{margin-top:8px;font-size:13px;color:var(--dim)}
  .sub b{font-weight:700}
  .grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:11px;margin-top:18px}
  @media(max-width:560px){.grid4{grid-template-columns:repeat(2,1fr)}}
  .kpi{background:var(--glass-2);border:1px solid var(--glass-brd);border-radius:15px;padding:12px 13px;
    backdrop-filter:blur(14px)}
  .kpi .k{font-size:11px;color:var(--dim);letter-spacing:.2px}
  .kpi .v{margin-top:5px;font-size:16px;font-weight:700}
  .win-glow{box-shadow:0 0 0 2px rgba(48,199,96,.35),0 16px 50px rgba(48,199,96,.16)}

  .up{color:var(--ios-green)} .down{color:var(--ios-red)} .dim{color:var(--dim)}

  .chart-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
  .chart-head h3{font-size:14.5px;font-weight:700}
  .legend{display:flex;gap:16px;font-size:12px;color:var(--dim)}
  .legend i{display:inline-block;width:20px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
  svg{display:block;width:100%;height:220px}

  .posrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(94px,1fr));gap:11px;margin-top:8px}
  .posrow .kpi .v{font-size:14px}

  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th{text-align:left;color:var(--dim);font-weight:600;padding:9px 8px;border-bottom:1px solid var(--hair);
    font-size:10.5px;letter-spacing:.5px;text-transform:uppercase}
  td{padding:10px 8px;border-bottom:1px solid var(--hair);white-space:nowrap}
  tr:last-child td{border-bottom:0}
  .badge-s{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:7px}
  .s-long{background:rgba(48,199,96,.15);color:#1a9c48}
  .s-short{background:rgba(255,59,48,.13);color:#d92c22}
  .tier{font-size:10px;color:var(--dim);border:1px solid var(--hair);border-radius:5px;padding:1px 5px;margin-left:5px}
  .cfg{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
  .cfg span{font-size:11.5px;color:var(--ink-2);background:var(--glass-2);border:1px solid var(--glass-brd);
    padding:6px 11px;border-radius:9px;backdrop-filter:blur(14px)}
  .empty{color:var(--dim);text-align:center;padding:28px 0;font-size:13px}
  .sec-h{font-size:13px;color:var(--dim);margin-bottom:10px;font-weight:600;letter-spacing:.3px}
</style>
</head>
<body>
<div class="bg"><span class="blob b1"></span><span class="blob b2"></span><span class="blob b3"></span><span class="blob b4"></span></div>
<div class="bg-tint"></div>

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
      <div class="legend"><span><i style="background:var(--ios-cyan)"></i>TV 实盘</span><span><i style="background:var(--ios-blue)"></i>VPS 影子</span></div>
    </div>
    <svg id="chart" viewBox="0 0 1000 220" preserveAspectRatio="none"></svg>
  </div>

  <div class="card sec" id="pos-card" style="display:none">
    <div class="sec-h" style="font-size:14.5px;font-weight:700;color:var(--ink)">VPS 当前持仓（模拟）</div>
    <div class="posrow" id="pos"></div>
  </div>

  <div class="row two sec">
    <div class="card"><div class="sec-h">TV 实盘 · 最近平仓</div><div id="tv-tbl"></div></div>
    <div class="card"><div class="sec-h">VPS 影子 · 最近平仓</div><div id="vps-tbl"></div></div>
  </div>

  <div class="card sec">
    <div class="sec-h">策略参数</div>
    <div class="cfg" id="cfg"></div>
  </div>
</div>

<script>
const BOOT = __BOOT__;
const fmt = (n,d=2)=> (n==null||isNaN(n))?'--':Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const sign = (n,d=2) => (n>0?'+':'')+fmt(n,d);
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
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>`;
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

  const a=s.tv.equity_curve||[], b=s.shadow.equity_curve||[], all=a.concat(b);
  const svg=document.getElementById('chart');
  if(all.length<2){ svg.innerHTML=`<text x="500" y="115" fill="#8a8a8e" font-size="13" text-anchor="middle">等待成交数据…</text>`; }
  else{
    const W=1000,H=220;
    const ts=all.map(p=>p[0]), vs=all.map(p=>p[1]).concat([0]);
    let lo=Math.min(...vs), hi=Math.max(...vs); if(hi===lo){hi+=1;lo-=1;}
    const pad=(hi-lo)*0.14; lo-=pad; hi+=pad;
    const t0=Math.min(...ts), t1=Math.max(...ts);
    const zeroY = H-8-((0-lo)/(hi-lo))*(H-16);
    svg.innerHTML =
      `<line x1="0" y1="${zeroY.toFixed(1)}" x2="${W}" y2="${zeroY.toFixed(1)}" stroke="rgba(60,60,67,.18)" stroke-dasharray="4 5"/>`+
      curve(a,'#32ade6',W,H,lo,hi,t0,t1)+curve(b,'#007aff',W,H,lo,hi,t0,t1)+
      `<text x="6" y="14" fill="#8a8a8e" font-size="11">${fmt(hi,0)} U</text>`+
      `<text x="6" y="${H-6}" fill="#8a8a8e" font-size="11">${fmt(lo,0)} U</text>`;
  }

  const p=s.shadow.open, pc=document.getElementById('pos-card');
  if(p){
    pc.style.display='block';
    const u=(p.side==='LONG'?(s.last_price-p.entry):(p.entry-s.last_price))*p.qty_left;
    const items=[
      ['方向',`<span class="badge-s ${p.side==='LONG'?'s-long':'s-short'}">${p.side}</span>`],
      ['档位','tier'+p.tier+' (ADX '+fmt(p.adx,1)+')'],
      ['进场',fmt(p.entry)],['ATR',fmt(p.atr,2)],
      ['数量',fmt(p.qty,4)+' → '+fmt(p.qty_left,4)],
      ['TP1',fmt(p.tp1)+(p.tp1_done?' ✓':'')],['TP2',fmt(p.tp2)+(p.tp2_done?' ✓':'')],
      ['硬止损',fmt(p.hard_sl)],['雷达止损',p.cur_stop>0?fmt(p.cur_stop):'--'],
      ['峰值',fmt(p.best)],['浮动 U',`<span class="${cls(u)}">${sign(u)}</span>`],['持有',dur(p.open_ts)],
    ];
    document.getElementById('pos').innerHTML = items.map(([k,v])=>`<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
  } else pc.style.display='none';

  document.getElementById('tv-tbl').innerHTML  = tvTable(s.tv.closed);
  document.getElementById('vps-tbl').innerHTML = vpsTable(s.shadow.closed);

  const c=s.config;
  document.getElementById('cfg').innerHTML = [
    `周期 ${c.tf_min}m`, `唐奇安 ${c.donchian_n} 根`, `ADX 门控 ${c.adx_gate}/${c.adx_mid}/${c.adx_strong}`,
    `硬止损 ${c.hard_sl_atr_mult}×ATR`, `taker ${(c.taker_fee*100).toFixed(3)}% · 返佣 ${(c.rebate*100).toFixed(0)}%`,
    `模拟基准 ${fmt(c.shadow_equity,0)} U`,
  ].map(x=>`<span>${x}</span>`).join('');
}
function tvTable(rows){
  if(!rows||!rows.length) return `<div class="empty">竞赛开始后的 TV 实盘平仓单会显示在这里</div>`;
  const r=rows.slice().reverse().slice(0,15);
  return `<table><thead><tr><th>开仓</th><th>方向</th><th>进→出</th><th>净 U</th><th>回报</th><th>方式</th></tr></thead><tbody>`+
    r.map(t=>`<tr><td class="dim">${tstr(t.open_ts)}</td>
      <td><span class="badge-s ${t.side==='LONG'?'s-long':'s-short'}">${t.side||'--'}</span></td>
      <td class="dim">${fmt(t.entry)} → ${fmt(t.exit)}</td>
      <td class="${cls(t.net)}">${sign(t.net)}</td><td class="${cls(t.ret_pct)}">${sign(t.ret_pct)}%</td>
      <td class="dim">${t.reason||''}</td></tr>`).join('')+`</tbody></table>`;
}
function vpsTable(rows){
  if(!rows||!rows.length) return `<div class="empty">等第一次 150m 唐奇安突破 + ADX≥20</div>`;
  const r=rows.slice().reverse().slice(0,15);
  return `<table><thead><tr><th>开仓</th><th>方向</th><th>进场</th><th>净 U</th><th>回报</th><th>出场</th></tr></thead><tbody>`+
    r.map(t=>`<tr><td class="dim">${tstr(t.open_ts)}</td>
      <td><span class="badge-s ${t.side==='LONG'?'s-long':'s-short'}">${t.side}</span><span class="tier">t${t.tier}</span></td>
      <td class="dim">${fmt(t.entry)}</td>
      <td class="${cls(t.net)}">${sign(t.net)}</td><td class="${cls(t.ret_pct)}">${sign(t.ret_pct)}%</td>
      <td class="dim">${t.reason}</td></tr>`).join('')+`</tbody></table>`;
}
async function tick(){ try{ const r=await fetch('../contest',{cache:'no-store'}); if(r.ok) render(await r.json()); }catch(e){} }
render(BOOT);
setInterval(tick, 20000);
</script>
</body>
</html>"""
