"""Build the static interactive results explorer (site/index.html) from results/*.json.

Deployed by .github/workflows/pages.yml. All data shown is embedded from the result artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"


def load(name):
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else None


def slim_benchmark(b):
    if not b:
        return None
    return {"name": b["name"], "version": b["benchmark_version"], "config": {k: b["config"][k] for k in ("seeds", "stresses", "arms", "reference_arm")},
            "comparison": b["comparison"], "sensitivity": b.get("cost_sensitivity"),
            "manifest": {k: b["manifest"][k] for k in ("runs", "runtime_s", "python", "machine", "cpu_count", "all_replays_verified", "created_at")}}


def main() -> None:
    data = {
        "standard": slim_benchmark(load("benchmarks/standard.json")),
        "extended": slim_benchmark(load("benchmarks/extended.json")),
        "scaling": load("scaling.json"),
        "auction": {k: v for k, v in (load("auction.json") or {}).items() if k in ("system", "incentives", "seeds")},
        "safe_rl": {k: v for k, v in (load("safe_rl.json") or {}).items() if k in ("summary", "training", "train_stresses", "eval_stresses")},
        "forecasting": {k: v for k, v in (load("forecasting.json") or {}).items() if k in ("results", "target", "splits")},
        "netting": load("netting_optimality.json"),
        "game": {k: v for k, v in (load("game.json") or {}).items() if k in ("profiles", "deviations", "seeds", "socially_best_profile")},
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    out = ROOT / "site"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(html)
    print(f"wrote {out / 'index.html'} ({len(html) / 1e6:.2f} MB)")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ATLAS-Σ Results Explorer</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.27.0/plotly.min.js"></script>
<style>
:root{--bg:#fcfcfb;--panel:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--line:#e4e3df;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--neutral:#a8a7a2;--bad:#e34948}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){--bg:#141413;--panel:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--line:#33322f;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--neutral:#6b6a64;--bad:#e66767}}
:root[data-theme="dark"]{--bg:#141413;--panel:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--line:#33322f;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--neutral:#6b6a64;--bad:#e66767}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:28px 20px 10px;max-width:1180px;margin:auto}h1{margin:0;font-size:26px}header p{color:var(--ink2);margin:6px 0 0;max-width:820px}
nav{display:flex;gap:6px;flex-wrap:wrap;max-width:1180px;margin:14px auto 0;padding:0 20px}nav button{border:1px solid var(--line);background:var(--panel);color:var(--ink2);padding:7px 12px;border-radius:999px;cursor:pointer;font:inherit;font-size:13px}
nav button.on{color:var(--ink);border-color:var(--s1);box-shadow:inset 0 0 0 1px var(--s1)}
main{max-width:1180px;margin:auto;padding:16px 20px 60px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:16px}.kpi .v{font-size:28px;font-weight:650;font-variant-numeric:tabular-nums}.kpi .l{color:var(--ink2);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.kpi .s{color:var(--ink2);font-size:13px}label{font-size:12px;color:var(--ink2);margin-right:10px}select{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:5px 8px;font:inherit;font-size:13px}
.note{color:var(--ink2);font-size:13px}table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}th:first-child,td:first-child{text-align:left}th{color:var(--ink2);font-weight:500}
.tab{display:none}.tab.on{display:block}.chart{width:100%;min-height:380px}.badge{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:1px 9px;font-size:12px;color:var(--ink2)}
.toggle{float:right;border:1px solid var(--line);background:var(--panel);color:var(--ink2);border-radius:999px;padding:4px 10px;cursor:pointer}
</style></head><body>
<header><button class="toggle" id="theme">Theme</button><h1>ATLAS-Σ Results Explorer</h1>
<p>Interactive view of every published experiment from the ATLAS-Σ multi-rail settlement digital twin. All numbers are read from the repository's result artifacts. <b>All data is synthetic</b>; no real bank or payment-system data is used.</p></header>
<nav id="nav"></nav><main id="main"></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const $ = (h) => { const t = document.createElement('template'); t.innerHTML = h.trim(); return t.content.firstChild; };
const M = v => '$' + (v / 1e8).toFixed(2) + 'M';
const layout = (extra = {}) => Object.assign({paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: {color: css('--ink2'), size: 12},
  margin: {l: 170, r: 30, t: 20, b: 50}, xaxis: {gridcolor: css('--line'), zerolinecolor: css('--ink2')}, yaxis: {gridcolor: css('--line'), automargin: true},
  legend: {orientation: 'h', y: -0.2}, hoverlabel: {bgcolor: css('--panel'), font: {color: css('--ink')}}}, extra);
const cfg = {displayModeBar: false, responsive: true};
const tabs = [];
function tab(id, title, render) { tabs.push({id, title, render}); }
const NAMES = {priority:'Priority queue (ref)', fifo:'FIFO', fifo_strict:'Strict FIFO', bilateral:'Bilateral offset', multilateral:'Multilateral heuristic',
  multilateral_milp:'Exact MILP netting', auction_pay_as_bid:'Auction: pay-as-bid', auction_uniform:'Auction: uniform price', rule_rebalancer:'Rule-based treasury',
  mpc:'MPC rebalancing', mpc_queue_milp:'MPC + queue MILP', mpc_plus_auction:'MPC + auction'};
// [label, formatter, lower-is-better, display scale, axis tickformat]
const METRICS = {total_cost_minor:['Total modeled cost', M, true, 0.01, '$.3s'], lv_settlement_rate_value:['Large-value value settled', v => (v*100).toFixed(2)+'%', false, 100, '.2f'],
  lv_value_weighted_delay_s:['Value-weighted delay (min)', v => (v/60).toFixed(1)+' min', true, 1/60, '.1f'], instant_rejected:['Instant payments rejected', v => v.toFixed(1), true, 1, '.0f'],
  timed_deadline_misses:['Timed-obligation deadline misses', v => v.toFixed(1), true, 1, '.1f'], peak_credit_minor:['Peak intraday credit', M, true, 0.01, '$.3s']};

tab('bench', 'Policy benchmark', el => {
  const sets = ['standard', 'extended'].filter(k => D[k]);
  el.append($(`<div class="panel"><label>Benchmark <select id="bs">${sets.map(s=>`<option>${s}</option>`).join('')}</select></label>
   <label>Stress <select id="bst"></select></label><label>Metric <select id="bm">${Object.entries(METRICS).map(([k,v])=>`<option value="${k}">${v[0]}</option>`).join('')}</select></label>
   <div class="chart" id="bc"></div><p class="note" id="bn"></p></div>`));
  el.append($(`<div class="panel"><h3 style="margin-top:0">Is the ranking robust to the cost weights?</h3><p class="note">Share of 27 alternative cost models (delay, unsettled and liquidity weights each ×0.25 / ×1 / ×4) under which each arm has the lowest mean cost.</p><div class="chart" id="sens"></div></div>`));
  const draw = () => {
    const B = D[el.querySelector('#bs').value]; const st = el.querySelector('#bst'); const m = el.querySelector('#bm').value;
    if (!st.options.length || st.dataset.b !== B.name) { st.innerHTML = B.config.stresses.map(s=>`<option>${s}</option>`).join(''); st.dataset.b = B.name; }
    const rows = B.comparison.filter(c => c.stress === st.value && c.metric === m).sort((a,b) => (METRICS[m][2] ? b.mean - a.mean : a.mean - b.mean));
    const ref = B.config.reference_arm, f = METRICS[m][1], lower = METRICS[m][2];
    const col = c => c.arm === ref ? css('--neutral') : !c.significant ? css('--neutral') : ((lower ? c.mean_diff < 0 : c.mean_diff > 0) ? css('--s1') : css('--s2'));
    const k = METRICS[m][3];
    Plotly.react('bc', [{type:'bar', orientation:'h', y: rows.map(r=>NAMES[r.arm]||r.arm), x: rows.map(r=>r.mean*k), marker:{color: rows.map(col)},
      error_x:{type:'data', symmetric:false, array: rows.map(r=> r.arm===ref?0: (r.ci95_diff[1]-r.mean_diff)*k), arrayminus: rows.map(r=> r.arm===ref?0: (r.mean_diff-r.ci95_diff[0])*k), color: css('--ink'), thickness:1.2},
      customdata: rows.map(r=>[f(r.mean), r.arm===ref?'reference':f(r.ci95_diff[0])+' to '+f(r.ci95_diff[1]), r.win_rate==null?'—':Math.round(r.win_rate*100)+'%', r.n]),
      hovertemplate:'<b>%{y}</b><br>mean %{customdata[0]}<br>95% CI of paired diff: %{customdata[1]}<br>wins vs ref: %{customdata[2]} of %{customdata[3]} seeds<extra></extra>'}],
      layout({height: 60 + 34*rows.length, xaxis:{gridcolor: css('--line'), title: METRICS[m][0], tickformat: METRICS[m][4]}}), cfg);
    el.querySelector('#bn').textContent = `${B.manifest.runs} runs, all ledger replays verified: ${B.manifest.all_replays_verified}. Blue = significantly better than ${NAMES[ref]}, orange = significantly worse, gray = CI includes zero. ${B.config.seeds.length} paired seeds; ${B.manifest.cpu_count} CPUs, Python ${B.manifest.python}.`;
    const S = B.sensitivity && B.sensitivity.by_stress[st.value];
    if (S) { const arms = Object.keys(S.win_share).filter(a => S.win_share[a] > 0).sort((a,b)=>S.win_share[b]-S.win_share[a]);
      Plotly.react('sens', [{type:'bar', orientation:'h', y: arms.map(a=>NAMES[a]||a), x: arms.map(a=>S.win_share[a]*100), marker:{color: css('--s1')},
        hovertemplate:'%{y}: best under %{x:.0f}% of cost models<extra></extra>'}], layout({height: 80 + 36*arms.length, xaxis:{gridcolor: css('--line'), range:[0,100], title:'% of cost models where it is cheapest'}}), cfg); }
  };
  el.querySelectorAll('select').forEach(s => s.onchange = draw); draw();
});

tab('scale', 'Scaling', el => {
  const R = D.scaling.rows;
  el.append($(`<div class="row">${[['Largest day simulated', R[R.length-1].payments.toLocaleString()+' payments', R[R.length-1].institutions+' banks, '+R[R.length-1].events.toLocaleString()+' events'],
    ['Wall time', R[R.length-1].simulate_s.toFixed(0)+' s', 'one CPU core, pure Python'], ['Replay', R.every(r=>r.replay_verified)?'All verified':'FAILED', 'ledger re-folded from the hash-chained log']]
    .map(([l,v,s])=>`<div class="panel kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join('')}</div>`));
  el.append($('<div class="panel"><div class="chart" id="sc"></div></div>'));
  Plotly.react('sc', [{x:R.map(r=>r.payments), y:R.map(r=>r.simulate_s), name:'Simulate', mode:'lines+markers', line:{color:css('--s1'), width:2}, marker:{size:9},
    text:R.map(r=>`${r.institutions} banks · ${Math.round(r.events_per_s).toLocaleString()} events/s · ${Math.round(r.peak_rss_mb)} MB`), hovertemplate:'%{x:,} payments<br>%{y:.1f}s<br>%{text}<extra>Simulate</extra>'},
    {x:R.map(r=>r.payments), y:R.map(r=>r.replay_s), name:'Replay + verify', mode:'lines+markers', line:{color:css('--s3'), width:2}, marker:{size:9}, hovertemplate:'%{x:,} payments<br>%{y:.1f}s<extra>Replay</extra>'}],
    layout({margin:{l:60,r:20,t:20,b:50}, xaxis:{type:'log', title:'payments per simulated day', gridcolor:css('--line')}, yaxis:{type:'log', title:'seconds', gridcolor:css('--line')}}), cfg);
});

tab('auction', 'Liquidity auction', el => {
  const A = D.auction; if (!A.system) { el.append($('<p class="note">No auction artifact.</p>')); return; }
  el.append($(`<div class="panel"><h3 style="margin-top:0">System effect</h3><table><thead><tr><th>Stress</th><th>Mechanism</th><th>Value settled</th><th>Δ vs no auction (95% CI)</th><th>Avg rate</th><th>Lent / day</th></tr></thead><tbody>${
    A.system.map(r=>`<tr><td>${r.stress}</td><td>${r.mechanism}</td><td>${(r.settled_mean*100).toFixed(2)}%</td><td>${r.mechanism==='none'?'—':(r.settled_diff_ci[0]*100).toFixed(2)+'pp ['+(r.settled_diff_ci[1]*100).toFixed(2)+', '+(r.settled_diff_ci[2]*100).toFixed(2)+']'}</td><td>${r.avg_rate_cbp==null?'—':(r.avg_rate_cbp/100).toFixed(3)+' bp'}</td><td>${r.principal_mean_minor==null?'—':M(r.principal_mean_minor)}</td></tr>`).join('')}</tbody></table></div>`));
  el.append($('<div class="panel"><h3 style="margin-top:0">Incentives: does inflating your ask pay?</h3><label>Stress <select id="as"><option>baseline</option><option>combined</option></select></label><div class="chart" id="ac"></div><p class="note">Change in a focal lender\'s own auction profit when it alone inflates its ask (paired seeds). Above zero = profitable manipulation; band = 95% CI.</p></div>'));
  const draw = () => { const st = el.querySelector('#as').value;
    Plotly.react('ac', ['pay_as_bid','uniform'].map((m,k)=>{ const r = A.incentives.filter(i=>i.mechanism===m && i.stress===st).sort((a,b)=>a.shade_bp-b.shade_bp);
      return {x:r.map(i=>i.shade_bp/100), y:r.map(i=>i.mean_gain_minor/100), name:m==='uniform'?'Uniform price':'Pay-as-bid', mode:'lines+markers', line:{color:css(k?'--s2':'--s1'), width:2}, marker:{size:9},
        error_y:{type:'data', symmetric:false, array:r.map(i=>(i.ci95[1]-i.mean_gain_minor)/100), arrayminus:r.map(i=>(i.mean_gain_minor-i.ci95[0])/100), color:css(k?'--s2':'--s1')},
        customdata:r.map(i=>[Math.round(i.share_profitable*100)]), hovertemplate:'inflate ask %{x}%<br>mean gain $%{y:,.0f}<br>profitable in %{customdata[0]}% of cases<extra></extra>'}; }),
      layout({margin:{l:70,r:20,t:20,b:50}, xaxis:{title:'ask inflated by (%)', gridcolor:css('--line')}, yaxis:{title:'change in own profit ($)', gridcolor:css('--line')}}), cfg); };
  el.querySelector('#as').onchange = draw; draw();
});

tab('rl', 'Safe RL vs MPC', el => {
  const R = D.safe_rl; if (!R.summary) { el.append($('<p class="note">No safe-RL artifact.</p>')); return; }
  el.append($('<div class="panel"><div class="chart" id="rc1"></div><p class="note">Safety rejections per control step during training. The Lagrangian multiplier penalises proposals the safety controller blocks; rejected proposals are never executed in either variant.</p></div>'));
  el.append($(`<div class="panel"><label>Held-out stress <select id="rs">${R.eval_stresses.map(s=>`<option>${s}</option>`).join('')}</select></label><div class="chart" id="rc2"></div><p class="note">Held-out seeds never used in training; 'combined' and 'liquidity_hoarding' were never seen during training (train stresses: ${R.train_stresses.join(', ')}).</p></div>`));
  Plotly.react('rc1', [['constrained','Constrained PPO','--s1'],['unconstrained','Plain PPO','--s2']].map(([k,n,c])=>({x:R.training[k].map(x=>x.iteration), y:R.training[k].map(x=>x.mean_rejections_per_step), name:n, mode:'lines', line:{color:css(c), width:2}})),
    layout({margin:{l:60,r:20,t:20,b:50}, xaxis:{title:'iteration', gridcolor:css('--line')}, yaxis:{title:'rejections / step', gridcolor:css('--line')}}), cfg);
  const draw = () => { const st = el.querySelector('#rs').value; const rows = R.summary.filter(s=>s.stress===st);
    Plotly.react('rc2', [{type:'bar', orientation:'h', y:rows.map(r=>r.arm), x:rows.map(r=>r.cost[0]/100), marker:{color:rows.map(r=>r.arm==='mpc'?css('--s1'):css('--neutral'))},
      error_x:{type:'data', symmetric:false, array:rows.map(r=>(r.cost[2]-r.cost[0])/100), arrayminus:rows.map(r=>(r.cost[0]-r.cost[1])/100), color:css('--ink')},
      customdata:rows.map(r=>[M(r.cost_diff_vs_mpc[0]), (r.safety_rejection_rate*100).toFixed(1), r.wins_vs_mpc]),
      hovertemplate:'<b>%{y}</b><br>cost %{x:$,.0f}<br>vs MPC %{customdata[0]}<br>proposals rejected %{customdata[1]}%<br>cheaper than MPC on %{customdata[2]}/10 days<extra></extra>'}],
      layout({height:300, xaxis:{title:'modeled cost per day (USD, 95% CI across held-out days)', tickformat:'$.3s', gridcolor:css('--line')}}), cfg); };
  el.querySelector('#rs').onchange = draw; draw();
});

tab('fc', 'Forecasting', el => {
  const F = D.forecasting; if (!F.results) return;
  el.append($('<div class="panel"><label>Horizon <select id="fh"><option>15m</option><option>30m</option><option selected>1h</option><option>4h</option></select></label><label>Test split <select id="fs"><option value="test_in_distribution">in-distribution</option><option value="test_out_of_distribution">shifted (OOD)</option></select></label><div class="chart" id="fcc"></div><table id="ft"></table><p class="note">Target: '+F.target+'. Whole simulated days are split train/validation/test. Static intervals: split conformal on validation days. Adaptive: causal online quantile tracking.</p></div>'));
  const draw = () => { const h = el.querySelector('#fh').value, s = el.querySelector('#fs').value; const rows = F.results.filter(r=>r.horizon===h && r.split===s).sort((a,b)=>a.mase-b.mase);
    Plotly.react('fcc', [{type:'bar', x:rows.map(r=>r.model), y:rows.map(r=>r.mase), marker:{color:rows.map(r=>r.mase<1?css('--s1'):css('--s2'))}, hovertemplate:'%{x}: MASE %{y:.3f}<extra></extra>'}],
      layout({margin:{l:60,r:20,t:20,b:80}, yaxis:{title:'MASE (below 1 beats naive)', gridcolor:css('--line')}, shapes:[{type:'line', xref:'paper', x0:0, x1:1, y0:1, y1:1, line:{color:css('--ink2'), dash:'dash', width:1}}]}), cfg);
    el.querySelector('#ft').innerHTML = '<thead><tr><th>Model</th><th>MAE</th><th>CRPS≈</th><th>90% PI coverage (static)</th><th>coverage (adaptive)</th></tr></thead><tbody>' +
      rows.map(r=>`<tr><td>${r.model}</td><td>$${(r.mae/1e6).toFixed(2)}M</td><td>$${(r.crps_approx/1e6).toFixed(2)}M</td><td>${(r.interval_coverage*100).toFixed(1)}%</td><td>${r.adaptive_interval_coverage==null?'—':(r.adaptive_interval_coverage*100).toFixed(1)+'%'}</td></tr>`).join('') + '</tbody>'; };
  el.querySelectorAll('select').forEach(x=>x.onchange = draw); draw();
});

tab('net', 'Netting optimality', el => {
  const N = D.netting; if (!N) return; const R = N.rows;
  el.append($('<div class="panel"><div class="chart" id="nc"></div><p class="note">Share of settleable value each algorithm leaves on the table versus the exact HiGHS MILP, on deliberately gridlocked random queues.</p></div>'));
  Plotly.react('nc', [['mean_gap','Gridlock heuristic','--s1','heuristic_ms_mean'],['lp_round_mean_gap','LP rounding + local search','--s2','lp_round_ms_mean'],['milp_50ms_mean_gap','MILP, 50 ms budget','--s3',null]].filter(x=>x[0] in R[0]).map(([k,n,c,t])=>({x:R.map(r=>r.obligations), y:R.map(r=>r[k]*100), name:n, mode:'lines+markers', line:{color:css(c), width:2}, marker:{size:9},
    text:R.map(r=>t?`${r[t].toFixed(1)} ms`:'≤ 50 ms'), hovertemplate:'%{x} obligations: %{y:.1f}% gap (%{text})<extra>'+n+'</extra>'})),
    layout({margin:{l:60,r:20,t:20,b:50}, xaxis:{title:'queued obligations', gridcolor:css('--line')}, yaxis:{title:'gap vs optimum (%)', gridcolor:css('--line')}}), cfg);
});

tab('game', 'Strategic behaviour', el => {
  const G = D.game; if (!G.profiles) return;
  el.append($(`<div class="panel"><p class="note">Empirical liquidity-timing game, ${G.seeds.length} paired seeds. Each symmetric profile is tested against unilateral deviations by the largest and median bank. Verdicts cover only these deviations; they are not proofs of Nash equilibrium.</p><table><thead><tr><th>Everyone plays</th><th>Verdict</th><th>System cost</th></tr></thead><tbody>${Object.entries(G.profiles).map(([k,v])=>`<tr><td>${k}${k===G.socially_best_profile?' ★':''}</td><td><span class="badge">${v.verdict}</span></td><td>${M(v.mean_system_cost_minor)}</td></tr>`).join('')}</tbody></table>
  <h3>Deviation gains (focal bank's own cost saved)</h3><table><thead><tr><th>Profile → deviation</th><th>Focal</th><th>Mean gain</th><th>95% CI</th></tr></thead><tbody>${G.deviations.map(d=>`<tr><td>${d.profile} → ${d.deviation}</td><td>${d.focal}</td><td>${M(d.mean_gain_minor)}</td><td>[${M(d.ci95[0])}, ${M(d.ci95[1])}]</td></tr>`).join('')}</tbody></table></div>`));
});

const nav = document.getElementById('nav'), main = document.getElementById('main');
tabs.forEach((t, i) => { const b = $(`<button>${t.title}</button>`); const sec = $(`<section class="tab" id="t-${t.id}"></section>`); main.append(sec); nav.append(b);
  b.onclick = () => { document.querySelectorAll('nav button').forEach(x=>x.classList.remove('on')); document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
    b.classList.add('on'); sec.classList.add('on'); if (!sec.dataset.done) { t.render(sec); sec.dataset.done = 1; } location.hash = t.id; }; });
const openHash = () => { const i = tabs.findIndex(t => '#' + t.id === location.hash); const b = nav.children[i >= 0 ? i : 0]; if (!b.classList.contains('on')) b.click(); };
window.addEventListener('hashchange', openHash); openHash();
document.getElementById('theme').onclick = () => { const r = document.documentElement; const dark = r.dataset.theme ? r.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  r.dataset.theme = dark ? 'light' : 'dark'; document.querySelectorAll('.tab').forEach(s => { s.innerHTML = ''; delete s.dataset.done; }); document.querySelector('nav button.on').click(); };
</script></body></html>
"""

if __name__ == "__main__":
    main()
