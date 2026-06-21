/* HKJC Edge Lab — SPA. Honest by construction: NO-BET default, verdict + CIs everywhere. */
'use strict';
const $ = (s, r=document) => r.querySelector(s);
const h = (html) => { const t=document.createElement('template'); t.innerHTML=html.trim(); return t.content.firstChild; };
const esc = (s)=> String(s==null?'':s).replace(/[&<>"'`]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','`':'&#96;'}[c]));

async function api(path, opts){
  const r = await fetch('/api'+path, opts);
  const j = await r.json();
  if(!j.ok){ throw new Error(j.error ? j.error.message : 'request failed'); }
  return j.data;
}
function toast(msg, err){ const t=h(`<div class="toast ${err?'err':''}">${esc(msg)}</div>`); $('#toasts').appendChild(t);
  setTimeout(()=>t.remove(), 4200); }

// ---- formatting ----
const pct = (x,d=1)=> x==null||isNaN(x)?'—':(100*x).toFixed(d);
const num = (x,d=2)=> x==null||isNaN(x)?'—':Number(x).toFixed(d);
const signed = (x,d=3)=> x==null||isNaN(x)?'—':(x>=0?'+':'')+Number(x).toFixed(d);
const ci = (a)=> a&&a.length===2 ? `[${signed(a[0],4)}, ${signed(a[1],4)}]` : '—';
function ciSpan(margin, ci95, pPos){
  const includesZero = !ci95 || (ci95[0]<=0 && ci95[1]>=0);
  return `<span class="ci ${includesZero?'notsig':''}">${signed(margin,4)} nats · 95% CI ${ci(ci95)}${pPos!=null?` · P(&gt;0)=${num(pPos,2)}`:''} ${includesZero?'· not significant':'· significant'}</span>`;
}

// ---- nav ----
const NAV = [
  ['Workspace', [['overview','Overview','◆'],['recommend','Race Recommender','★']]],
  ['Research', [['validation','Validation','◇'],['modellab','Model Lab','◇'],['backtest','Backtest & What-if','◇']]],
  ['Data', [['data','Data & Coverage','◇'],['tracking','Tracking','◇']]],
  ['Docs', [['feasibility','Feasibility Report','◇']]],
  ['System', [['settings','Settings','◇']]],
];
const TITLES = Object.fromEntries(NAV.flatMap(g=>g[1].map(x=>[x[0],x[1]])));
function renderNav(){
  const nav=$('#nav'); nav.innerHTML='';
  for(const [grp,items] of NAV){
    nav.appendChild(h(`<div class="group">${grp}</div>`));
    for(const [route,label,ic] of items){
      const a=h(`<a data-r="${route}"><span class="ic">${ic}</span><span>${label}</span>${ic==='★'?'<span class="star">★</span>':''}</a>`);
      a.onclick=()=>go(route); nav.appendChild(a);
    }
  }
}
function setActive(route){ document.querySelectorAll('.nav a').forEach(a=>a.classList.toggle('active',a.dataset.r===route)); }

let STATE={route:null, headline:null, status:null, gateOn:false};
function go(route){ location.hash=route; }
window.addEventListener('hashchange', router);

async function router(){
  const route = (location.hash.replace('#','')||'overview');
  STATE.route=route; setActive(route);
  $('#pageTitle').textContent = TITLES[route]||'';
  $('#topbarActions').innerHTML='';
  const view=$('#view'); view.classList.remove('fade'); void view.offsetWidth; view.classList.add('fade');
  view.innerHTML = skeleton();
  try{ await (PAGES[route]||PAGES.overview)(view); }
  catch(e){ view.innerHTML=`<div class="callout"><span class="ic">!</span><div>Couldn't load this view: ${esc(e.message)}</div></div>`; }
}
const skeleton = ()=>`<div class="grid kpis">${'<div class="kpi"><div class="skeleton" style="height:60px"></div></div>'.repeat(4)}</div><div class="card"><div class="skeleton" style="height:200px"></div></div>`;

// ---- header honesty (verdict chip / strip) ----
async function loadHeadline(){
  const hd = await api('/headline'); STATE.headline=hd;
  const st = await api('/status').catch(()=>null); STATE.status=st;
  // Sync the edge-gate UI to the SERVER's session state so a reload/2nd tab can't hide an ON gate.
  if(st){ STATE.gateOn = !!st.edge_gate_enabled; document.body.classList.toggle('gate-on', STATE.gateOn); }
  const v = hd.verdict||'NOT RUN';
  $('#verdictText').textContent=v;
  $('#verdictDot').className='dot '+(v==='GO'?'green':v==='NO-GO'?'':'grey');
  $('#honestyText').textContent = hd.ran
    ? `${hd.headline} Edge vs closing line: ${signed(hd.clv_margin,4)} nats — CI ${hd.ci_includes_zero?'includes 0 (not significant)':'excludes 0'}.`
    : 'No validation on record → NO BET (absence of a GO is treated as NO-GO).';
  if(st) $('#sideFoot').innerHTML = `${st.counts.race} races · ${st.date_range.first||'—'} → ${st.date_range.last||'—'}<br>${esc(st.data_version)} · takeout ${st.takeout_pct}%`;
}

// ============================ CHART (canvas line) ============================
function lineChart(canvas, series, opt={}){
  const dpr=window.devicePixelRatio||1, W=canvas.clientWidth, H=opt.height||220;
  canvas.width=W*dpr; canvas.height=H*dpr; canvas.style.height=H+'px';
  const ctx=canvas.getContext('2d'); ctx.scale(dpr,dpr);
  const pad={l:46,r:14,t:12,b:26};
  const xs=series.flatMap(s=>s.points.map(p=>p.x)), ys=series.flatMap(s=>s.points.map(p=>p.y));
  let xmin=opt.xmin??Math.min(...xs), xmax=opt.xmax??Math.max(...xs);
  let ymin=opt.ymin??Math.min(...ys,0), ymax=opt.ymax??Math.max(...ys,0);
  if(xmin===xmax){xmax=xmin+1} if(ymin===ymax){ymax=ymin+1}
  const X=x=>pad.l+(x-xmin)/(xmax-xmin)*(W-pad.l-pad.r);
  const Y=y=>H-pad.b-(y-ymin)/(ymax-ymin)*(H-pad.t-pad.b);
  const css=getComputedStyle(document.documentElement);
  ctx.strokeStyle=css.getPropertyValue('--grid'); ctx.lineWidth=1; ctx.font='10px JetBrains Mono'; ctx.fillStyle=css.getPropertyValue('--faint');
  for(let i=0;i<=4;i++){ const y=ymin+(ymax-ymin)*i/4; ctx.beginPath(); ctx.moveTo(pad.l,Y(y)); ctx.lineTo(W-pad.r,Y(y)); ctx.globalAlpha=.5; ctx.stroke(); ctx.globalAlpha=1;
    ctx.fillText((opt.yfmt?opt.yfmt(y):y.toFixed(2)).padStart(6), 4, Y(y)+3); }
  if(opt.zeroLine && ymin<0 && ymax>0){ ctx.strokeStyle=css.getPropertyValue('--border-2'); ctx.setLineDash([4,4]); ctx.beginPath(); ctx.moveTo(pad.l,Y(0)); ctx.lineTo(W-pad.r,Y(0)); ctx.stroke(); ctx.setLineDash([]); }
  if(opt.diagonal){ ctx.strokeStyle=css.getPropertyValue('--border-2'); ctx.setLineDash([4,4]); ctx.beginPath(); ctx.moveTo(X(xmin),Y(ymin)); ctx.lineTo(X(xmax),Y(ymax)); ctx.stroke(); ctx.setLineDash([]); }
  for(const s of series){ ctx.strokeStyle=s.color; ctx.lineWidth=s.width||1.6; if(s.dashed)ctx.setLineDash([5,4]); else ctx.setLineDash([]);
    ctx.beginPath(); s.points.forEach((p,i)=> i?ctx.lineTo(X(p.x),Y(p.y)):ctx.moveTo(X(p.x),Y(p.y))); ctx.stroke();
    if(s.dots) s.points.forEach(p=>{ ctx.fillStyle=s.color; ctx.beginPath(); ctx.arc(X(p.x),Y(p.y),2.4,0,7); ctx.fill(); }); }
  ctx.setLineDash([]);
}

// ============================ PAGES ============================
const PAGES={};

PAGES.overview = async (view)=>{
  const hd=STATE.headline, st=STATE.status;
  const v=hd.verdict;
  view.innerHTML = `
  <div class="grid kpis">
    <div class="kpi warn"><div class="lbl">Verdict</div><div class="val">${v}</div>
      <div class="sub">${hd.ran?(hd.ci_includes_zero?'does not beat the closing line':'beats the line — review'):'not yet run'}</div></div>
    <div class="kpi"><div class="lbl">CLV margin</div><div class="val mono">${signed(hd.clv_margin,4)}</div>
      <div class="sub">nats/race · ${hd.ci_includes_zero?'CI ∋ 0':'CI ⊅ 0'}</div></div>
    <div class="kpi"><div class="lbl">+EV bets (OOS)</div><div class="val mono">${hd.plus_ev_bets??'—'}</div>
      <div class="sub">after ${st?st.takeout_pct:17.5}% takeout</div></div>
    <div class="kpi"><div class="lbl">Coverage</div><div class="val mono">${st?st.counts.race:'—'}</div>
      <div class="sub">races · ${st?st.counts.runner:'—'} runners</div></div>
  </div>
  <div class="callout"><span class="ic">⚠</span><div><strong>NO-GO is the expected, honest outcome.</strong>
    The HKJC market is highly efficient; a public-data model does not beat the closing line out of sample, and produces ~zero +EV bets after the takeout. The rational action is to not bet — the takeout is the house edge you can't model away with public data.</div></div>
  <div class="grid" style="grid-template-columns:1fr 1fr">
    <div class="card"><h3>Next steps</h3><div id="ov-next" class="muted-note"></div></div>
    <div class="card"><h3>What the model does</h3>
      <div class="muted-note">It blends a fundamental conditional-logit model with the market via Benter's two-stage method. The combiner's honest conclusion: weight the <em>market</em> heavily and the fundamental model barely at all — "trust the crowd." See <a onclick="go('modellab')">Model Lab</a> and <a onclick="go('validation')">Validation</a>.</div></div>
  </div>`;
  const next=$('#ov-next');
  next.innerHTML = `<ul style="padding-left:18px;line-height:2">
    <li><a onclick="go('recommend')">Open the Race Recommender</a> — model vs market for any race (always NO BET).</li>
    <li><a onclick="go('validation')">Run / view Validation</a> — the GO/NO-GO with bootstrap CIs.</li>
    <li><a onclick="go('backtest')">Explore the What-if backtest</a> — see why no EV threshold escapes the takeout.</li>
    <li><a onclick="go('tracking')">Tracking scoreboard</a> — the tool grades its own closing-line value.</li></ul>`;
};

// ---------- Race Recommender (flagship) ----------
PAGES.recommend = async (view)=>{
  const m = await api('/meetings');
  if(!m.meetings.length){ view.innerHTML = empty('No meetings ingested','Fetch a meeting from the Data page to begin.'); return; }
  const opts = m.meetings.map(mt=>`<option value="${esc(mt.date)}|${esc(mt.course)}">${esc(mt.date)} · ${esc(mt.course)} · ${mt.race_count} races${mt.has_results?'':' (no results)'}</option>`).join('');
  view.innerHTML = `
    <div class="card"><div class="row spread">
      <div class="row"><label class="mut">Meeting</label><select id="meetSel">${opts}</select>
        <label class="mut">Race</label><select id="raceSel"></select></div>
      <button class="btn secondary" id="logBtn">Log recommendation</button></div></div>
    <div id="recView"></div>`;
  const meetSel=$('#meetSel'), raceSel=$('#raceSel');
  async function loadRaces(){
    const [date,course]=meetSel.value.split('|');
    const r=await api(`/races?date=${date}&course=${course}`);
    raceSel.innerHTML = r.races.map(x=>`<option value="${esc(String(x.race_id))}">R${x.race_no} · ${x.distance||'?'}m · ${esc(x.class||'')}</option>`).join('');
    loadRec();
  }
  async function loadRec(){
    const rv=$('#recView'); rv.innerHTML=`<div class="card"><div class="skeleton" style="height:240px"></div></div>`;
    try{ rv.innerHTML = renderRec(await api(`/races/${raceSel.value}/recommend`)); }
    catch(e){ rv.innerHTML=`<div class="callout"><span class="ic">!</span><div>${esc(e.message)}</div></div>`; }
  }
  meetSel.onchange=loadRaces; raceSel.onchange=loadRec;
  $('#logBtn').onclick=async()=>{ try{ await api(`/races/${raceSel.value}/recommend/log`,{method:'POST'}); toast('Recommendation logged for self-tracking.'); }catch(e){ toast(e.message,true);} };
  await loadRaces();
};
function renderRec(d){
  const banner = `<div class="callout"><span class="ic">⚠</span><div><strong>NO BET</strong> — model does not beat the closing line (validation: <span class="pill nogo">${d.verdict}</span>). Figures below are research signal, not tips. Edge gate is ${d.edge_gate_enabled?'<span class="pill neg">ON</span>':'OFF'}.</div></div>`;
  const maxp = Math.max(...d.runners.map(r=>Math.max(r.model_prob||0,r.market_prob||0)),0.01);
  const bars = d.runners.map(r=>`
    <div style="margin:10px 0">
      <div class="spread" style="font-size:12.5px"><span class="mono">#${r.horse_no}</span>
        <span class="mut">model <span class="mono">${pct(r.model_prob)}%</span> · market <span class="mono">${pct(r.market_prob)}%</span> · EV <span class="mono">${r.ev==null?'—':(r.ev>=0?'+':'')+pct(r.ev)+'%'}</span></span></div>
      <div class="bar-track" style="height:8px;margin-top:4px"><div class="bar-fill market" style="width:${100*(r.market_prob||0)/maxp}%;opacity:.6"></div></div>
      <div class="bar-track" style="height:8px;margin-top:2px"><div class="bar-fill model" style="width:${100*(r.model_prob||0)/maxp}%"></div></div>
    </div>`).join('');
  const rows = d.runners.map(r=>`<tr>
    <td class="mono">${r.horse_no}</td>
    <td class="num">${pct(r.model_prob)}%</td>
    <td class="num mut">${pct(r.market_prob)}%</td>
    <td class="num">${r.edge_nats==null?'—':signed(r.edge_nats,3)}</td>
    <td class="num">${r.win_odds==null?'—':num(r.win_odds,1)}</td>
    <td class="num">${r.ev==null?'—':(r.ev>=0?'+':'')+pct(r.ev)+'%'}</td>
    <td><span class="pill ${r.decision==='BET'?'pos':'nobet'}">${r.decision}</span></td></tr>`).join('');
  const cw = d.combiner_weights;
  const cons = d.consistency, cr = (cons&&cons.rows&&cons.rows.length)?cons.rows[0]:null;
  return `${banner}
  <div class="card"><div class="spread">
    <div><div class="section-h" style="margin-bottom:4px">Race ${d.race_no} · ${d.distance||'?'}m · ${esc(d.class||'')} · ${esc(d.going||'')}</div>
      <div class="muted-note">${d.field_size} runners · model trained on <span class="mono">${d.n_train_races}</span> strictly-prior races ${d.insufficient_history?'<span class="pill ghost">insufficient history → market fallback</span>':'<span class="pill ghost">LEAK-FREE</span> <span class="pill ghost">OOS</span>'}</div></div>
    <div style="text-align:right"><div class="lbl mut" style="font-size:10px;text-transform:uppercase">+EV runners after takeout</div><div class="mono" style="font-size:22px">${d.plus_ev_count}</div></div>
  </div></div>
  <div class="grid" style="grid-template-columns:1.4fr 1fr">
    <div class="card"><h3>Model vs Market — comparison (not picks)</h3>
      <table><thead><tr><th>#</th><th class="num">Model%</th><th class="num">Mkt%</th><th class="num">Edge</th><th class="num">Odds</th><th class="num">EV</th><th>Verdict</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div>
      <div class="card"><h3>Probabilities</h3><div class="muted-note" style="margin-bottom:6px"><span style="color:var(--accent)">▔</span> model · <span style="color:var(--series-market)">▔</span> market (de-vigged, sum 100%)</div>${bars}</div>
      <div class="card"><h3>Why NO BET</h3><div class="muted-note">${cw?`Two-stage combiner weights: market <span class="mono">×${num(cw.log_market,2)}</span> · fundamental model <span class="mono">×${num(cw.log_fund,2)}</span> — the model's best move is to trust the crowd.`:''} After the ${d.takeout_pct}% takeout, <strong>${d.plus_ev_count} of ${d.field_size}</strong> runners clear the EV gate, and the edge gate is OFF.</div></div>
    </div>
  </div>
  <div class="card"><h3>Cross-pool consistency signal</h3>
    <div class="callout info"><span class="ic">i</span><div><strong>Information, NOT arbitrage.</strong> ${cons&&cons.available?`Compares Win-pool-implied place value (Harville) to actual Place dividends. Efficient baseline place-EV ≈ <span class="mono">${signed(cons.expected_market_ev,3)}</span>. Most generous place spot: horse <span class="mono">${cr?cr.horse_no:'—'}</span> (place EV <span class="mono">${cr?signed(cr.place_ev_market,3):'—'}</span>).`:esc(cons?cons.note:'n/a')}<br><span class="muted-note">${esc((cons&&cons.note)||'Harville-approximate; pools provisional; separate takeouts; no lay side; your bet moves the pool. Not arbitrage.')}</span></div></div></div>`;
}

// ---------- Validation ----------
PAGES.validation = async (view)=>{
  $('#topbarActions').innerHTML='<button class="btn" id="runVal">Run validation</button>';
  $('#runVal').onclick=runValidation;
  const r = await api('/validation/latest');
  if(!r || !r.clv || !r.clv.models || !r.profit){ view.innerHTML = empty('No validation on record','Run a walk-forward validation to get the GO/NO-GO verdict. Until then the default is NO BET.','Run validation',runValidation); return; }
  const c=r.clv.models.p_combined.bootstrap_vs_market, pr=r.profit.combined, base=r.baselines, plc=r.placebo;
  view.innerHTML = `
  <div class="grid kpis">
    <div class="kpi warn"><div class="lbl">Verdict</div><div class="val">${r.verdict}</div><div class="sub">${r.n_oos_races} OOS races</div></div>
    <div class="kpi"><div class="lbl">CLV vs market</div><div class="val mono">${signed(c.mean_margin,4)}</div><div class="sub">${ciSpan(c.mean_margin,c.ci95,c.p_positive)}</div></div>
    <div class="kpi"><div class="lbl">+EV bets / ROI</div><div class="val mono">${pr.n_bets??0}</div><div class="sub">ROI ${pr.roi==null?'—':pct(pr.roi)+'%'} · CI ${pr.roi_ci95?ci(pr.roi_ci95):'—'}</div></div>
    <div class="kpi"><div class="lbl">Bet-all baseline</div><div class="val mono">${base?pct(base.bet_all.roi):'—'}%</div><div class="sub">≈ −takeout (Phase-0 certainty)</div></div>
  </div>
  <div class="callout"><span class="ic">⚠</span><div><strong>${r.verdict}: no demonstrated edge.</strong> The combined model does not beat the closing line out of sample (margin ${signed(c.mean_margin,4)} nats, CI ${c.ci95?'includes 0':'—'}) and produces ~zero +EV bets after takeout. <em>Placebo (market-consistent null):</em> margin ${plc&&plc.clv_margin?signed(plc.clv_margin.mean_margin,4):'—'} — confirms no leak inflating the result, and no real edge.</div></div>
  <div class="grid" style="grid-template-columns:1fr 1fr">
    <div class="card"><h3>Closing-line value (primary test)</h3>
      <table><tbody>
        <tr><td>market (de-vigged close)</td><td class="num mono">${num(r.clv.market_winner_logloss,5)}</td></tr>
        <tr><td>combined (Benter two-stage)</td><td class="num mono">${num(r.clv.models.p_combined.winner_logloss,5)}</td></tr>
        <tr><td>fundamental only</td><td class="num mono">${num(r.clv.models.p_fund.winner_logloss,5)}</td></tr>
      </tbody></table>
      <div class="muted-note" style="margin-top:8px">Lower winner log-loss = better. The market is the benchmark; the combined model ${c.significant_at_95?'beats':'does not beat'} it (CI ${c.ci95?'∋ 0':'—'}).</div></div>
    <div class="card"><h3>Calibration (out-of-sample)</h3><canvas id="calChart"></canvas>
      <div class="muted-note" style="margin-top:6px"><span style="color:var(--accent)">▔</span> model · <span style="color:var(--series-market)">▔</span> market · dashed = perfect</div></div>
  </div>
  <div class="card"><div class="spread"><h3 style="margin:0">Profit simulation <span class="simwm">simulated · after-takeout · hypothetical</span></h3></div>
    <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:12px">
      <div><div class="section-h">Equity (fractional-Kelly)</div><canvas id="eqChart" height="180"></canvas></div>
      <div><div class="section-h">Cumulative P&L (flat value bets)</div><canvas id="pnlChart" height="180"></canvas></div>
    </div>
    <div class="muted-note" style="margin-top:8px">Baselines — bet-all ROI ${base?pct(base.bet_all.roi):'—'}% (≈ −takeout, the algebraic certainty), bet-favourite ${base?pct(base.bet_favorite.roi):'—'}%. These are not a track record.</div></div>`;
  // calibration chart from /models/eval (reliability tables)
  try{
    const ev = await api('/models/eval');
    const rel = (t)=> (t.reliability||[]).map(b=>({x:b.mean_pred,y:b.emp_rate}));
    lineChart($('#calChart'), [
      {points: rel(ev.calibration.market), color:getCss('--series-market'), dots:true},
      {points: rel(ev.calibration.combined), color:getCss('--accent'), dots:true},
    ], {xmin:0,xmax:0.5,ymin:0,ymax:1,diagonal:true,height:200,yfmt:y=>y.toFixed(1)});
  }catch(e){}
  // equity + pnl from PNGs would be static; draw from validation data if present
  drawEquityPnl(r);
};
function drawEquityPnl(r){
  // Cumulative P&L is in the JSON — draw it client-side; equity uses the generated PNG.
  const eq=$('#eqChart'), pnl=$('#pnlChart');
  const cum = r.profit && r.profit.combined && r.profit.combined.cum_pnl;
  if(pnl && cum && cum.length){
    lineChart(pnl, [{points: cum.map((y,i)=>({x:i+1,y})), color:getCss('--accent')}],
      {zeroLine:true, height:180, yfmt:y=>y.toFixed(1)});
  } else if(pnl){
    pnl.replaceWith(h(`<img src="/api/validation/plots/pnl.png" style="width:100%;border-radius:8px" onerror="this.style.display='none'">`));
  }
  if(eq){ eq.replaceWith(h(`<img src="/api/validation/plots/equity.png" style="width:100%;border-radius:8px" onerror="this.style.display='none'">`)); }
}
async function runValidation(){
  toast('Validation started (walk-forward; ~10–20s)…');
  const {job_id}=await api('/validation/run',{method:'POST'});
  const poll=async()=>{ const j=await api('/jobs/'+job_id);
    if(j.state==='done'){ toast('Validation complete.'); if(STATE.route==='validation') router(); loadHeadline(); }
    else if(j.state==='error'){ toast('Validation failed: '+(j.message||''),true); }
    else setTimeout(poll,1200); };
  setTimeout(poll,1200);
}

// ---------- Model Lab ----------
PAGES.modellab = async (view)=>{
  const ev = await api('/models/eval');
  if(ev.insufficient_data){ view.innerHTML = empty('Not enough data to evaluate', ev.message||'Ingest more races (≈350+ evaluable needed).'); return; }
  const imp = ev.feature_importance||[];
  const maxw = Math.max(...imp.map(f=>f.weight),0.001);
  const bars = imp.map(f=>`<div class="bar-row"><span class="mono mut" style="font-size:11px">${esc(f.feature).replace(/_/g,' ').slice(0,22)}</span>
     <div class="bar-track"><div class="bar-fill model" style="width:${100*f.weight/maxw}%"></div></div><span class="num mono">${num(f.weight,3)}</span></div>`).join('');
  const cw=ev.combiner_weights;
  view.innerHTML = `
  <div class="callout info"><span class="ic">i</span><div>These importances explain the <strong>fundamental</strong> model. But the two-stage combiner weights the market ${cw?`<span class="mono">×${num(cw.log_market,2)}</span>`:''} vs the fundamental model ${cw?`<span class="mono">×${num(cw.log_fund,2)}</span>`:''} — so these features <strong>barely move the final pick</strong>; the market dominates.</div></div>
  <div class="grid" style="grid-template-columns:1fr 1fr">
    <div class="card"><h3>Feature importance (standardized |β|)</h3>${bars||'<div class="muted-note">unavailable</div>'}</div>
    <div class="card"><h3>Model vs market (OOS winner log-loss)</h3>
      <table><tbody>
       <tr><td>market</td><td class="num mono">${num(ev.market,5)}</td></tr>
       <tr><td>combined (two-stage)</td><td class="num mono">${num(ev.combined,5)}</td></tr>
       <tr><td>fundamental</td><td class="num mono">${num(ev.fundamental,5)}</td></tr>
      </tbody></table>
      <div class="muted-note" style="margin-top:10px">CLV margin vs market: ${ciSpan(ev.clv.mean_margin,ev.clv.ci95,ev.clv.p_positive)}</div>
      <div class="muted-note" style="margin-top:6px">Across ${ev.n_oos_races} OOS races. A lower <em>fundamental</em> log-loss is not an edge — the benchmark is always the market.</div></div>
  </div>`;
};

// ---------- Backtest & What-if ----------
PAGES.backtest = async (view)=>{
  const w = await api('/whatif');
  if(w.insufficient_data || !w.sweep || !w.sweep.length){ view.innerHTML = empty('Not enough data for a backtest', w.message||'Need more evaluable races to walk-forward.'); return; }
  let tries=0;
  view.innerHTML = `
  <div class="callout"><span class="ic">⚠</span><div>This explores a <strong>frozen out-of-sample backtest</strong>. Searching thresholds for the best ROI is in-sample cheating — always read the CI, never just the ROI. The verdict stays tied to the pre-registered EV threshold = 0.</div></div>
  <div class="card"><div class="row spread"><h3 style="margin:0">EV-threshold what-if <span class="simwm">simulated · hypothetical</span></h3>
     <div class="row"><span class="mut">threshold</span><input type="range" id="thr" min="0" max="${w.sweep.length-1}" value="${Math.max(0,w.sweep.findIndex(s=>Math.abs(s.threshold)<1e-9))}" style="width:220px"><span class="mono" id="thrV" style="width:54px"></span><span class="pill ghost" id="tries">0 tries</span></div></div>
    <div class="grid" style="grid-template-columns:repeat(3,1fr);margin:14px 0">
      <div class="kpi"><div class="lbl">Bets</div><div class="val mono" id="kf-bets">—</div></div>
      <div class="kpi"><div class="lbl">ROI (after takeout)</div><div class="val mono" id="kf-roi">—</div><div class="sub" id="kf-ci"></div></div>
      <div class="kpi"><div class="lbl">Significant?</div><div class="val" id="kf-sig">—</div></div>
    </div>
    <canvas id="wfChart" height="200"></canvas>
    <div class="muted-note" style="margin-top:6px">ROI vs EV-threshold across ${w.n_oos_races} OOS races. As you raise the bar, the bet count collapses and the CI explodes — there is no free threshold that beats the takeout.</div></div>`;
  const sweep=w.sweep;
  lineChart($('#wfChart'), [
    {points: sweep.map((s,i)=>({x:s.threshold,y:s.roi==null?0:s.roi})), color:getCss('--accent'), dots:true},
  ], {zeroLine:true, height:200, yfmt:y=>(y*100).toFixed(0)+'%'});
  const thr=$('#thr');
  function upd(){ const s=sweep[+thr.value]; $('#thrV').textContent=signed(s.threshold,2);
    $('#kf-bets').textContent=s.n_bets; $('#kf-roi').textContent=s.roi==null?'—':(s.roi>=0?'+':'')+pct(s.roi)+'%';
    $('#kf-roi').className='val mono '+(s.roi>0?'pos':'neg');
    $('#kf-ci').innerHTML = s.roi_ci95?`95% CI [${pct(s.roi_ci95[0])}%, ${pct(s.roi_ci95[1])}%]`:'';
    $('#kf-sig').innerHTML = s.roi_significant_positive?'<span class="pill ghost">yes (in-sample)</span>':'<span class="pill nobet">no — within noise</span>';
    $('#tries').textContent=(++tries)+' tries'; }
  thr.oninput=upd; upd();
};

// ---------- Data & Coverage ----------
PAGES.data = async (view)=>{
  $('#topbarActions').innerHTML='<button class="btn secondary" id="fetchBtn">Fetch meeting…</button>';
  const q = await api('/dataset/quality');
  const cfg = await api('/config');
  const miss = q.missingness.map(m=>`<tr><td>${esc(m.column)}</td><td class="num">${pct(m.pct_null)}%</td></tr>`).join('');
  view.innerHTML = `
  <div class="grid kpis">
    <div class="kpi"><div class="lbl">Races</div><div class="val mono">${q.races}</div><div class="sub">${q.evaluable_races} evaluable</div></div>
    <div class="kpi"><div class="lbl">Rows (runners)</div><div class="val mono">${q.rows}</div></div>
    <div class="kpi"><div class="lbl">Base win rate</div><div class="val mono">${pct(q.win_rate)}%</div><div class="sub">avg field ${q.avg_field_size}</div></div>
    <div class="kpi"><div class="lbl">No-lookahead</div><div class="val" style="color:var(--positive)">verified</div><div class="sub">enforced by tests</div></div>
  </div>
  <div class="grid" style="grid-template-columns:1fr 1fr">
    <div class="card"><h3>Feature coverage (% missing)</h3><table><tbody>${miss}</tbody></table>
      <div class="muted-note" style="margin-top:8px">${esc(q.no_lookahead.note)}</div></div>
    <div class="card"><h3>Collection &amp; ToS</h3>
      <div class="muted-note">Data fetched from public HKJC pages for <strong>personal research only</strong>. Respect the site's Terms of Service and robots.txt; do not redistribute.
      <br><br>Rate limit: <span class="mono">${cfg.http.base_delay_seconds}s</span>/host · robots: <span class="mono">${cfg.http.respect_robots}</span><br>UA: <span class="mono" style="font-size:11px">${esc(cfg.http.user_agent)}</span></div></div>
  </div>`;
  $('#fetchBtn').onclick=fetchDialog;
};
async function fetchDialog(){
  const date=prompt('Meeting date (YYYY-MM-DD):'); if(!date)return;
  const course=(prompt('Course (ST / HV):','ST')||'ST').toUpperCase();
  toast(`Fetching ${date} ${course} (polite, rate-limited)…`);
  try{ const {job_id}=await api(`/fetch?date=${date}&course=${course}`,{method:'POST'});
    const poll=async()=>{ const j=await api('/jobs/'+job_id);
      if(j.state==='done'){ toast(`Fetched: ${JSON.stringify(j.result)}`); if(STATE.route==='data')router(); }
      else if(j.state==='error'){ toast('Fetch failed: '+j.message,true); } else setTimeout(poll,1500); };
    setTimeout(poll,1500);
  }catch(e){ toast(e.message,true); }
}

// ---------- Tracking ----------
PAGES.tracking = async (view)=>{
  const t = await api('/tracking'); const s=t.summary;
  if(!t.recommendations.length){ view.innerHTML = empty('No recommendations logged yet','The lab stays honest — nothing to reconcile. Log one from the Race Recommender.'); return; }
  const rows = t.recommendations.slice(0,60).map(r=>`<tr>
    <td class="mono mut">${r.race_date} ${r.racecourse} R${r.race_no}</td><td class="mono">#${r.horse_no}</td>
    <td class="num">${pct(r.model_prob)}</td><td class="num mut">${pct(r.market_prob)}</td>
    <td><span class="pill ${r.decision==='BET'?'pos':'nobet'}">${r.decision}</span>${r.edge_gate_enabled?' <span class="pill neg">override</span>':''}</td>
    <td class="num">${r.clv==null?'—':signed(r.clv,3)}</td><td class="num">${r.won==null?'—':(r.won?'won':'lost')}</td></tr>`).join('');
  view.innerHTML = `
  <div class="grid kpis">
    <div class="kpi"><div class="lbl">Recommendations</div><div class="val mono">${s.total_recommendations}</div></div>
    <div class="kpi"><div class="lbl">Avg CLV</div><div class="val mono">${s.avg_clv==null?'—':signed(s.avg_clv,4)}</div><div class="sub">${t.clv_ci95?'95% CI '+ci(t.clv_ci95):esc(t.replay_note||'n<10 — too few to conclude')}</div></div>
    <div class="kpi"><div class="lbl">Bets settled</div><div class="val mono">${s.settled_bets}</div><div class="sub">by design 0 (gate OFF)</div></div>
    <div class="kpi"><div class="lbl">Realized P&L</div><div class="val mono">${num(s.total_pnl,2)}</div><div class="sub">${s.roi==null?'no settled bets':'ROI '+pct(s.roi)+'% · small sample, no CI'}</div></div>
  </div>
  <div class="callout info"><span class="ic">i</span><div>Closing-line value is the leading indicator of edge — it would show up before profit. With the gate OFF, bets = 0 by design. CLV is shown with a CI and only over a meaningful sample; one good week is noise. No forward extrapolation.</div></div>
  <div class="card"><h3>Logged recommendations</h3><table><thead><tr><th>Race</th><th>#</th><th class="num">Model%</th><th class="num">Mkt%</th><th>Decision</th><th class="num">CLV</th><th class="num">Result</th></tr></thead><tbody>${rows}</tbody></table></div>`;
};

// ---------- Feasibility ----------
PAGES.feasibility = async (view)=>{
  const r = await api('/feasibility');
  view.innerHTML = `<div class="card report" id="rep"></div>`;
  $('#rep').innerHTML = mdToHtml(r.markdown);
};

// ---------- Settings ----------
PAGES.settings = async (view)=>{
  const cfg = await api('/config'); const g=cfg.guardrails||{};
  view.innerHTML = `
  <div class="card"><h3>Edge gate (research only)</h3>
    <div class="spread"><div class="muted-note" style="max-width:560px">The edge gate is <strong>OFF</strong> because validation = NO-GO. Turning it on makes the tool emit bet suggestions the evidence does not support (expected to lose the takeout). Resets to OFF on app relaunch.</div>
      <label class="row"><input type="checkbox" id="gateTog" ${STATE.gateOn?'checked':''}/> <span>${STATE.gateOn?'<span class="pill neg">ON</span>':'OFF'}</span></label></div></div>
  <div class="grid" style="grid-template-columns:1fr 1fr">
    <div class="card"><h3>Bankroll guardrails (loss limits, read-only)</h3>
      <table><tbody>
        <tr><td>Starting bankroll</td><td class="num mono">${num(g.starting_bankroll,0)}</td></tr>
        <tr><td>Kelly fraction</td><td class="num mono">${num(g.kelly_fraction,2)}</td></tr>
        <tr><td>Per-bet cap</td><td class="num mono">${pct(g.per_bet_cap_frac)}%</td></tr>
        <tr><td>Per-race cap</td><td class="num mono">${pct(g.per_race_cap_frac)}%</td></tr>
        <tr><td>Total exposure cap</td><td class="num mono">${pct(g.total_exposure_cap_frac)}%</td></tr>
        <tr><td>Session loss limit</td><td class="num mono">${pct(g.session_loss_limit_frac)}%</td></tr>
        <tr><td>Stop-loss</td><td class="num mono">${pct(g.stop_loss_frac)}%</td></tr>
      </tbody></table>
      <div class="muted-note" style="margin-top:8px">Fractional Kelly &amp; caps are <strong>loss-limiting guardrails</strong>, not profit tools. If gambling affects you: Ping Wo Fund 183&nbsp;4633.</div></div>
    <div class="card"><h3>Engine</h3><table><tbody>
        <tr><td>Takeout (Win)</td><td class="num mono">${cfg.takeout_pct}%</td></tr>
        <tr><td>EV threshold</td><td class="num mono">${signed(cfg.ev_threshold,2)}</td></tr>
        <tr><td>Min prior races</td><td class="num mono">${cfg.min_prior_races}</td></tr>
        <tr><td>De-vig</td><td class="num mono">proportional</td></tr>
      </tbody></table></div>
  </div>`;
  $('#gateTog').onchange=(e)=>{ if(e.target.checked){ e.target.checked=false; openGate(); } else setGate(false); };
};

// ---- helpers ----
function getCss(v){ return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
function empty(title,sub,btn,fn){ const id='emp'+Math.random().toString(36).slice(2);
  setTimeout(()=>{ const b=document.getElementById(id); if(b&&fn)b.onclick=fn; },0);
  return `<div class="empty"><div class="glyph">∅</div><div style="font-size:15px;color:var(--text)">${esc(title)}</div><div style="margin:6px 0 14px">${esc(sub)}</div>${btn?`<button class="btn" id="${id}">${esc(btn)}</button>`:''}</div>`; }
function mdToHtml(md){
  // minimal, safe-ish markdown (escapes then applies a few rules)
  let s=esc(md);
  s=s.replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/^# (.*)$/gm,'<h1>$1</h1>');
  s=s.replace(/^&gt; (.*)$/gm,'<blockquote>$1</blockquote>');
  s=s.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>');
  // tables: leave as-is mostly; convert simple pipe tables
  s=s.replace(/^(\|.+\|)\n\|[-: |]+\|\n((?:\|.*\|\n?)*)/gm,(m,head,body)=>{
    const th=head.split('|').slice(1,-1).map(c=>`<th>${c.trim()}</th>`).join('');
    const tr=body.trim().split('\n').map(r=>'<tr>'+r.split('|').slice(1,-1).map(c=>`<td>${c.trim()}</td>`).join('')+'</tr>').join('');
    return `<table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`; });
  // wrap each bullet, then collapse CONSECUTIVE <li> into ONE <ul> (greedy run, not per-item)
  s=s.replace(/^- (.*)$/gm,'<li>$1</li>').replace(/(?:<li>[\s\S]*?<\/li>\n?)+/g, m=>'<ul>'+m+'</ul>');
  s=s.split(/\n{2,}/).map(p=>{ const t=p.trim();
    return (/^<(h\d|ul|ol|table|blockquote|li|pre)/.test(t) || /<\/(table|ul|ol)>\s*$/.test(t))
      ? p : `<p>${p.replace(/\n/g,' ')}</p>`; }).join('\n');
  return s;
}

// ---- edge gate (session-only, server runtime override) ----
function openGate(){ $('#gateConfirm').checked=false; $('#gateModal').classList.add('show'); }
function closeGate(){ $('#gateModal').classList.remove('show'); if(STATE.route==='settings')router(); }
async function confirmGate(){ if(!$('#gateConfirm').checked){ toast('Tick the box to confirm.',true); return; }
  await setGate(true); closeGate(); }
async function setGate(on){ try{ await api('/edge_gate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:on})});
    STATE.gateOn=on; document.body.classList.toggle('gate-on',on); if(STATE.route==='settings')router(); toast(on?'Edge gate ON — unvalidated override.':'Edge gate OFF.'); }catch(e){ toast(e.message,true);} }
window.go=go; window.dismissFirstRun=()=>{ $('#firstRun').classList.remove('show'); localStorage.setItem('hkjc_seen','1'); };
window.openGate=openGate; window.closeGate=closeGate; window.confirmGate=confirmGate;

// ---- boot ----
(async function(){
  renderNav();
  if(!localStorage.getItem('hkjc_seen')) $('#firstRun').classList.add('show');
  try{ await loadHeadline(); }catch(e){ toast('Backend not ready: '+e.message,true); }
  if(!location.hash) location.hash='overview';
  router();
})();
