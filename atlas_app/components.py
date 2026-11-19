"""Self-authored HTML components: animated settlement network, count-up tiles, hero banner, agent pipeline, gauge, ticker.

Each is one small HTML document rendered in an iframe. Data goes in as JSON; nothing is fetched by the component.
"""

from __future__ import annotations

import json

import streamlit as st
from atlas_app.theme import palette

FONT = "Inter,system-ui,-apple-system,Segoe UI,sans-serif"
MONO = "'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace"
HEAD = ("<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap' rel='stylesheet'>"
        "<style>body{margin:0;background:transparent;font-family:" + FONT + ";color:__INK__}"
        ".mono{font-family:" + MONO + "}@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}</style>")


def embed(html: str, height: int) -> None:
    p = palette()
    doc = HEAD.replace("__INK__", p["ink"]) + html
    for k, v in p.items():
        doc = doc.replace(f"__{k.upper()}__", v)
    if hasattr(st, "iframe"):
        st.iframe(doc, height=height)
    else:  # older Streamlit
        import streamlit.components.v1 as components
        components.html(doc, height=height)


# ------------------------------------------------------------------ hero banner
def hero(eyebrow: str, big: str, unit: str, sub: str, height: int = 150) -> None:
    embed(f"""<div class="h"><div class="e mono">{eyebrow}</div><div class="b"><span id="n">{big}</span> <span class="u">{unit}</span></div><div class="s mono">{sub}</div></div>
<style>.h{{background:linear-gradient(120deg,__DEEP__ 0%,__PRIMARY__ 55%,__ACCENT2__ 130%);border-radius:18px;padding:22px 26px;color:#fff;position:relative;overflow:hidden;
animation:rise .5s ease-out both}}.h:after{{content:'';position:absolute;right:-60px;top:-60px;width:240px;height:240px;border-radius:50%;background:rgba(255,255,255,.07)}}
.e{{font-size:11px;letter-spacing:.16em;text-transform:uppercase;opacity:.8}}.b{{font-size:44px;font-weight:700;letter-spacing:-.02em;margin:4px 0 2px}}
.u{{font-size:20px;font-weight:500;opacity:.92}}.s{{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;opacity:.72}}
@keyframes rise{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}</style>""", height)


# ------------------------------------------------------------------ count-up tiles
def tiles(items: list[dict], cols: int = 3, height: int | None = None) -> None:
    """items: {label, value, fmt: pct|min|usd|int|bp|bn|raw, edge: good|warn|bad|p|a, sub, base, low (lower is better)}"""
    rows = -(-len(items) // cols)
    data = json.dumps(items)
    html = """<div id="k"></div><style>
#k{display:grid;grid-template-columns:repeat(__COLS__,minmax(0,1fr));gap:12px;padding:2px}
@media(max-width:560px){#k{grid-template-columns:repeat(2,minmax(0,1fr))}}
.t{background:#fff;border:1px solid __LINE__;border-left:4px solid __PRIMARY__;border-radius:14px;padding:12px 14px;animation:rise .4s ease-out both;transition:transform .15s,box-shadow .15s}
.t:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(14,26,51,.08)}
.t.good{border-left-color:__GOOD__}.t.warn{border-left-color:__WARN__}.t.bad{border-left-color:__BAD__}.t.a{border-left-color:__ACCENT__}
.l{font-family:'JetBrains Mono',monospace;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:__MUTED__}
.v{font-size:30px;font-weight:650;color:__INK__;line-height:1.25;font-variant-numeric:tabular-nums;white-space:nowrap}
.d{font-size:12px;color:__INK2__;min-height:16px;font-variant-numeric:tabular-nums}.up{color:__GOOD__}.dn{color:__BAD__}
@media(max-width:560px){.v{font-size:22px}}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}</style>
<script>const T=__DATA__;const usd=v=>{const a=Math.abs(v);return (v<0?'−':'')+'$'+(a>=1e12?(a/1e12).toFixed(2)+'T':a>=1e9?(a/1e9).toFixed(2)+'B':a>=1e6?(a/1e6).toFixed(2)+'M':a>=1e3?(a/1e3).toFixed(1)+'k':a.toFixed(0))};
const F={pct:v=>v.toFixed(2)+'%',pct1:v=>v.toFixed(1)+'%',min:v=>v.toFixed(1)+' min',usd,int:v=>Math.round(v).toLocaleString(),bp:v=>v.toFixed(1)+' bp',rate:v=>v.toFixed(2)+'%',bn:v=>'$'+v.toLocaleString(undefined,{maximumFractionDigits:1})+'bn',raw:v=>String(v)};
const k=document.getElementById('k');T.forEach((t,i)=>{const e=document.createElement('div');e.className='t '+(t.edge||'');e.style.animationDelay=(i*50)+'ms';
let d=t.sub||'';const f=F[t.fmt||'raw'];
if(t.base!==undefined&&t.base!==null&&typeof t.value==='number'){const x=t.value-t.base;if(Math.abs(x)<1e-9)d='same as baseline';else{const g=t.low?x<0:x>0;d='<span class="'+(g?'up':'dn')+'">'+(x>0?'▲ ':'▼ ')+(t.fmt==='pct'?Math.abs(x).toFixed(2)+' pp':f(Math.abs(x)))+'</span> vs baseline'}}
e.innerHTML='<div class="l">'+t.label+'</div><div class="v">'+(typeof t.value==='number'?f(0):t.value)+'</div><div class="d">'+d+'</div>';k.appendChild(e);
if(typeof t.value!=='number')return;const el=e.querySelector('.v'),still=matchMedia('(prefers-reduced-motion: reduce)').matches,t0=performance.now(),dur=900;
const step=n=>{const q=still?1:Math.min(1,(n-t0)/dur),z=1-Math.pow(1-q,3);el.textContent=f(t.value*z);if(q<1)requestAnimationFrame(step)};requestAnimationFrame(step)});</script>"""
    embed(html.replace("__DATA__", data).replace("__COLS__", str(cols)), height or (rows * 104 + 8))


# ------------------------------------------------------------------ animated settlement network
def network(frames: dict, height: int = 560, meta: str = "") -> None:
    """Payments travel between banks as particles, half hour by half hour. Pause, replay, 1x/3x/10x, scrub, click a bank to pin it."""
    f = frames
    data = json.dumps({"banks": f["banks"], "tiers": f["tiers"], "sent": f["sent_minor"], "avail": f["available_minor"], "labels": f["labels"],
                       "net": f["net_minor"], "queued": f["queued_minor"], "flows": f["flows"], "qtot": f["queued_total_minor"], "settled": f["settled_cum_minor"]})
    html = """
<div class="wrap"><div class="bar">
 <button id="pp" class="pill on">Pause</button><button id="rp" class="pill">Replay</button>
 <span class="seg"><button class="sp on" data-s="1">1×</button><button class="sp" data-s="3">3×</button><button class="sp" data-s="10">10×</button></span>
 <input id="scrub" type="range" min="0" value="0" aria-label="Time of day"><span id="clock" class="mono clock">08:30 ET</span></div><div class="meta mono">__META__</div>
<div class="row"><svg id="g" viewBox="0 0 640 470" role="img" aria-label="Animated payment network"></svg>
<div class="side">
 <div class="c"><div class="l mono">Settled so far</div><div id="cs" class="n">$0</div></div>
 <div class="c warnc"><div class="l mono">Waiting to settle</div><div id="cq" class="n">$0</div><svg id="spark" viewBox="0 0 200 46" preserveAspectRatio="none"></svg></div>
 <div class="c pin" id="pin"><div class="l mono">Click a bank</div><div class="hint">to pin its position through the day</div></div>
 <div class="legend mono"><span><i style="background:__GOOD__"></i>flowing</span><span><i style="background:__WARN__"></i>strained</span><span><i style="background:__BAD__"></i>stuck</span></div>
</div></div></div>
<style>
.wrap{background:#fff;border:1px solid __LINE__;border-radius:18px;padding:12px 14px}
.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}
.pill,.sp{font:500 13px Inter,system-ui;border:1px solid __LINE__;background:#fff;color:__INK__;border-radius:999px;padding:6px 14px;cursor:pointer}
.pill.on{background:__PRIMARY__;color:#fff;border-color:__PRIMARY__}.seg{display:inline-flex;background:__SOFT__;border-radius:999px;padding:2px}
.sp{border:0;background:transparent;padding:5px 11px}.sp.on{background:__PRIMARY__;color:#fff}
#scrub{flex:1;min-width:120px;accent-color:__PRIMARY__}.clock{font-size:13px;color:__INK2__;min-width:76px;text-align:right}
.meta{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:__MUTED__;margin:-2px 0 4px}
.row{display:grid;grid-template-columns:minmax(0,1fr) 230px;gap:12px}@media(max-width:700px){.row{grid-template-columns:1fr}}
svg#g{width:100%;height:auto;display:block}
.c{border:1px solid __LINE__;border-left:4px solid __GOOD__;border-radius:12px;padding:10px 12px;margin-bottom:10px}.warnc{border-left-color:__ACCENT__}.pin{border-left-color:__PRIMARY__;min-height:92px}
.l{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:__MUTED__}.n{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}
.hint{font-size:12px;color:__INK2__}.kv{display:flex;justify-content:space-between;font-size:12.5px;color:__INK2__;margin-top:3px}.kv b{color:__INK__;font-variant-numeric:tabular-nums}
.legend{display:flex;gap:10px;font-size:10.5px;color:__MUTED__;text-transform:uppercase;letter-spacing:.06em}.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px}
.node{cursor:pointer;transition:fill .5s}.node:hover{stroke-width:3}.lab{font:600 10px Inter;fill:#fff;pointer-events:none}
.ring{fill:none;stroke:__LINE__;stroke-dasharray:3 5}
</style>
<script>
const D=__DATA__,NS='http://www.w3.org/2000/svg',g=document.getElementById('g'),n=D.banks.length,T=D.labels.length;
const usd=v=>{const a=Math.abs(v);return (v<0?'−':'')+'$'+(a>=1e9?(a/1e9).toFixed(2)+'B':a>=1e6?(a/1e6).toFixed(1)+'M':a>=1e3?(a/1e3).toFixed(0)+'k':a.toFixed(0))};
const el=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e};
const core=[],peri=[];D.tiers.forEach((t,i)=>(t==='core'?core:peri).push(i));const pos={},cx=320,cy=235;
g.appendChild(el('circle',{cx,cy,r:205,class:'ring'}));g.appendChild(el('circle',{cx,cy,r:88,class:'ring'}));
[[core,88,0.5],[peri,205,0]].forEach(([ring,r,o])=>ring.forEach((i,k)=>{const a=2*Math.PI*k/Math.max(1,ring.length)+o-Math.PI/2;pos[i]=[cx+r*Math.cos(a),cy+r*Math.sin(a)]}));
const idx={};D.banks.forEach((b,i)=>idx[b]=i);const topS=Math.max(...D.sent)||1;
const edgeL=el('g',{}),partL=el('g',{}),nodeL=el('g',{});g.append(edgeL,partL,nodeL);
const C={good:'__GOOD__',warn:'__WARN__',bad:'__BAD__',p:'__PRIMARY__',a:'__ACCENT__'};
const mix=(a,b,t)=>{const p=s=>[1,3,5].map(i=>parseInt(s.slice(i,i+2),16)),x=p(a),y=p(b);return 'rgb('+x.map((v,i)=>Math.round(v+(y[i]-v)*t)).join(',')+')'};
const col=s=>s<0.5?mix(C.good,C.warn,s/0.5):mix(C.warn,C.bad,Math.min(1,(s-0.5)/0.5));
const nodes=D.banks.map((b,i)=>{const r=11+20*Math.sqrt(D.sent[i]/topS),c=el('circle',{cx:pos[i][0],cy:pos[i][1],r,class:'node',fill:C.good,stroke:'#fff','stroke-width':2});
 c.addEventListener('click',()=>{pinned=i;showPin()});c.appendChild(el('title',{}));c.lastChild.textContent=b;nodeL.appendChild(c);
 const t=el('text',{x:pos[i][0],y:pos[i][1]+3.5,'text-anchor':'middle',class:'lab'});t.textContent=b.replace('bank-','');nodeL.appendChild(t);return c});
const maxF=Math.max(1,...D.flows.flat().map(f=>f.minor));let frame=0,speed=1,playing=!matchMedia('(prefers-reduced-motion: reduce)').matches,pinned=null,acc=0,last=performance.now(),parts=[];
const FR=1700;const scrub=document.getElementById('scrub');scrub.max=T-1;
function curve(a,b){const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2,dx=mx-cx,dy=my-cy,k=0.25;return [mx-dx*k,my-dy*k]}
function enter(t){frame=t;scrub.value=t;document.getElementById('clock').textContent=D.labels[t]+' ET';
 edgeL.innerHTML='';D.flows[t].forEach(f=>{const a=pos[idx[f.from]],b=pos[idx[f.to]],c=curve(a,b),w=0.6+5*f.minor/maxF;
  edgeL.appendChild(el('path',{d:`M${a[0]},${a[1]} Q${c[0]},${c[1]} ${b[0]},${b[1]}`,fill:'none',stroke:C.p,'stroke-opacity':0.12+0.25*f.minor/maxF,'stroke-width':w}));
  const k=2+Math.round(7*f.minor/maxF);for(let j=0;j<k;j++)parts.push({a,b,c,t0:-(j/k)*FR*0.8,big:f.minor/maxF})});
 nodes.forEach((c,i)=>c.setAttribute('fill',col(D.queued[t][i]/Math.max(1,D.avail[i]))));
 document.getElementById('cs').textContent=usd(D.settled[t]/100);document.getElementById('cq').textContent=usd(D.qtot[t]/100);spark(t);showPin()}
function spark(t){const s=document.getElementById('spark'),m=Math.max(1,...D.qtot);let d='';for(let i=0;i<=t;i++)d+=(i?'L':'M')+(i/(T-1)*200).toFixed(1)+','+(44-D.qtot[i]/m*40).toFixed(1);
 s.innerHTML=`<path d="${d}" fill="none" stroke="${C.a}" stroke-width="2"/>`}
function showPin(){if(pinned===null)return;const i=pinned,p=document.getElementById('pin'),q=D.queued[frame][i],net=D.net[frame][i];
 p.innerHTML=`<div class="l mono">Pinned · ${D.tiers[i]} bank</div><div class="n">${D.banks[i]}</div><div class="kv">waiting to send<b>${usd(q/100)}</b></div><div class="kv">net position<b>${usd(net/100)}</b></div><div class="kv">liquidity at open<b>${usd(D.avail[i]/100)}</b></div>`;
 nodes.forEach((c,j)=>c.setAttribute('stroke',j===i?C.p:'#fff'));nodes[i].setAttribute('stroke-width',4)}
function tick(now){const dt=now-last;last=now;if(playing){acc+=dt*speed;if(acc>=FR){acc=0;if(frame<T-1){parts=[];enter(frame+1)}else{playing=false;btn()}}}
 partL.innerHTML='';const life=FR*0.9;parts.forEach(p=>{const u=((acc-p.t0)%life)/life;if(acc<p.t0&&p.t0>0)return;const x=(1-u)*(1-u)*p.a[0]+2*(1-u)*u*p.c[0]+u*u*p.b[0],y=(1-u)*(1-u)*p.a[1]+2*(1-u)*u*p.c[1]+u*u*p.b[1];
 partL.appendChild(el('circle',{cx:x,cy:y,r:1.8+2.6*p.big,fill:p.big>0.6?C.a:C.p,'fill-opacity':0.85}))});requestAnimationFrame(tick)}
const pp=document.getElementById('pp');function btn(){pp.textContent=playing?'Pause':'Play';pp.classList.toggle('on',playing)}
pp.onclick=()=>{if(!playing&&frame>=T-1){parts=[];enter(0)}playing=!playing;btn()};
document.getElementById('rp').onclick=()=>{parts=[];acc=0;enter(0);playing=true;btn()};
document.querySelectorAll('.sp').forEach(b=>b.onclick=()=>{speed=+b.dataset.s;document.querySelectorAll('.sp').forEach(x=>x.classList.toggle('on',x===b))});
scrub.oninput=()=>{parts=[];acc=0;enter(+scrub.value)};
pinned=D.avail.map((a,i)=>Math.max(...D.queued.map(q=>q[i]))/Math.max(1,a)).reduce((m,v,i,arr)=>v>arr[m]?i:m,0);
enter(playing?0:T-1);btn();requestAnimationFrame(tick);
</script>"""
    import html as _h
    embed(html.replace("__DATA__", data).replace("__META__", _h.escape(meta)), height)


# ------------------------------------------------------------------ agent pipeline (animated)
def pipeline(steps: list[dict], height: int = 120) -> None:
    """steps: {k: small label, v: value, ok: bool|None}. Nodes appear one after another and connect."""
    html = """<div id="p"></div><style>
#p{display:flex;flex-wrap:wrap;align-items:center;gap:0;padding:8px 2px}
.s{border:2px solid __PRIMARY__;border-radius:12px;padding:8px 12px;background:#fff;opacity:0;transform:translateY(6px);transition:all .45s;max-width:210px}
.s.on{opacity:1;transform:none}.s.ok{border-color:__GOOD__}.s.no{border-color:__BAD__}.s.dim{border-style:dashed;border-color:__ACCENT3__}
.k{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:__MUTED__}
.v{font-weight:600;font-size:13.5px;color:__INK__;word-break:break-word}
.ln{height:3px;width:26px;background:__LINE__;position:relative;overflow:hidden}.ln i{position:absolute;inset:0;background:__PRIMARY__;transform:translateX(-100%);transition:transform .4s}.ln.on i{transform:none}
</style><script>
const S=__DATA__,p=document.getElementById('p');const nodes=[];S.forEach((s,i)=>{if(i){const l=document.createElement('div');l.className='ln';l.innerHTML='<i></i>';p.appendChild(l);nodes.push(l)}
const d=document.createElement('div');d.className='s'+(s.ok===true?' ok':s.ok===false?' no':'')+(s.dim?' dim':'');d.innerHTML='<div class="k">'+s.k+'</div><div class="v">'+s.v+'</div>';p.appendChild(d);nodes.push(d)});
nodes.forEach((n,i)=>setTimeout(()=>n.classList.add('on'),250+i*330));</script>"""
    embed(html.replace("__DATA__", json.dumps(steps)), height)


# ------------------------------------------------------------------ gauge
def gauge(score: float, regime: str, parts: dict, height: int = 250) -> None:
    data = json.dumps({"s": score, "r": regime, "parts": parts})
    html = """<div class="w"><svg viewBox="0 0 240 140" id="gg"></svg><div id="pp"></div></div><style>
.w{background:#fff;border:1px solid __LINE__;border-radius:16px;padding:10px 14px;display:grid;grid-template-columns:220px 1fr;gap:14px;align-items:center}
@media(max-width:560px){.w{grid-template-columns:1fr}}
.pr{margin:5px 0}.pr .t{display:flex;justify-content:space-between;font-size:12px;color:__INK2__}.pr .b{height:7px;background:__SOFT__;border-radius:4px;overflow:hidden}
.pr .b i{display:block;height:100%;background:__PRIMARY__;width:0;transition:width 1s ease-out;border-radius:4px}</style><script>
const D=__DATA__,NS='http://www.w3.org/2000/svg',g=document.getElementById('gg');
const arc=(a0,a1,r)=>{const p=a=>[120+r*Math.cos(a),125+r*Math.sin(a)];const [x0,y0]=p(a0),[x1,y1]=p(a1);return `M${x0},${y0} A${r},${r} 0 ${a1-a0>Math.PI?1:0} 1 ${x1},${y1}`};
const mk=(d,c,w)=>{const e=document.createElementNS(NS,'path');e.setAttribute('d',d);e.setAttribute('stroke',c);e.setAttribute('stroke-width',w);e.setAttribute('fill','none');e.setAttribute('stroke-linecap','round');g.appendChild(e);return e};
mk(arc(Math.PI,2*Math.PI,95),'__SOFT__',18);[[0,.35,'__GOOD__'],[.35,.65,'__WARN__'],[.65,1,'__BAD__']].forEach(([a,b,c])=>mk(arc(Math.PI*(1+a)+.02,Math.PI*(1+b)-.02,112),c,4));
const val=mk(arc(Math.PI,Math.PI*1.0001,95),'__PRIMARY__',18);const txt=document.createElementNS(NS,'text');txt.setAttribute('x',120);txt.setAttribute('y',112);txt.setAttribute('text-anchor','middle');
txt.setAttribute('style','font:700 34px Inter;fill:__INK__');g.appendChild(txt);const lab=document.createElementNS(NS,'text');lab.setAttribute('x',120);lab.setAttribute('y',134);lab.setAttribute('text-anchor','middle');
lab.setAttribute('style','font:600 11px JetBrains Mono,monospace;letter-spacing:.14em;fill:__MUTED__');lab.textContent=D.r.toUpperCase()+' · TIGHTNESS';g.appendChild(lab);
const t0=performance.now();const step=n=>{const q=Math.min(1,(n-t0)/1100),z=1-Math.pow(1-q,3),s=D.s*z;val.setAttribute('d',arc(Math.PI,Math.PI*(1+Math.max(.0001,s/100)),95));txt.textContent=Math.round(s);if(q<1)requestAnimationFrame(step)};requestAnimationFrame(step);
const pp=document.getElementById('pp');Object.entries(D.parts).forEach(([k,v])=>{const max={'SOFR above EFFR':40}[k]||20;const d=document.createElement('div');d.className='pr';
d.innerHTML='<div class="t"><span>'+k+'</span><b>'+v.toFixed(1)+' / '+max+'</b></div><div class="b"><i></i></div>';pp.appendChild(d);setTimeout(()=>d.querySelector('i').style.width=(v/max*100)+'%',80)});</script>"""
    embed(html.replace("__DATA__", data), height)


# ------------------------------------------------------------------ ticker
def ticker(items: list[tuple[str, str, str]], height: int = 46) -> None:
    """items: (label, value, tone good|bad|flat)."""
    cells = "".join(f'<span class="i"><span class="mono l">{a}</span> <b>{b}</b> <span class="{c}">●</span></span>' for a, b, c in items)
    embed(f"""<div class="tk"><div class="m">{cells}{cells}</div></div><style>
.tk{{overflow:hidden;background:#fff;border:1px solid __LINE__;border-radius:999px;white-space:nowrap}}.m{{display:inline-block;padding:9px 0;animation:mv 38s linear infinite}}
.tk:hover .m{{animation-play-state:paused}}.i{{margin:0 22px;font-size:14px}}.l{{font-size:11px;letter-spacing:.1em;color:__MUTED__}}b{{color:__INK__}}
.good{{color:__GOOD__}}.bad{{color:__BAD__}}.flat{{color:__ACCENT3__}}@keyframes mv{{from{{transform:translateX(0)}}to{{transform:translateX(-50%)}}}}</style>""", height)


# ------------------------------------------------------------------ real people on this deployment
def people(items: list[dict], height: int = 92) -> None:
    """items: {name, n, ago, last, live}. Avatars of the people who actually used this deployment."""
    verbs = {"joined": "joined", "ran_day": "ran a day", "ran_live_market": "ran today's market", "compared": "compared A/B", "uploaded": "uploaded payments",
             "asked": "asked the agent", "case_decision": "decided a case", "review": "left a review", "pinned": "pinned a baseline", "exported": "exported"}
    for x in items:
        x["verb"] = verbs.get(x["last"], x["last"])
    html = """<div class="row"><div class="lab mono">USED BY</div><div id="pp"></div></div><style>
.row{display:flex;align-items:center;gap:12px;overflow-x:auto;padding:4px 2px 8px}.lab{font-size:10.5px;letter-spacing:.14em;color:__MUTED__;white-space:nowrap}
#pp{display:flex;gap:10px}.p{display:flex;align-items:center;gap:9px;background:#fff;border:1px solid __LINE__;border-radius:999px;padding:5px 14px 5px 5px;white-space:nowrap;
animation:pop .45s cubic-bezier(.2,1.4,.4,1) both;transition:transform .15s,box-shadow .15s}.p:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(14,26,51,.1)}
.av{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;color:#fff;font:600 13px Inter;position:relative}
.live:after{content:'';position:absolute;right:-1px;bottom:-1px;width:10px;height:10px;border-radius:50%;background:__GOOD__;border:2px solid #fff;animation:pulse 1.6s infinite}
.nm{font:600 13px Inter;color:__INK__}.sb{font-size:11.5px;color:__INK2__}.empty{font-size:13px;color:__INK2__;background:#fff;border:1px dashed __LINE__;border-radius:999px;padding:9px 16px}
@keyframes pop{from{opacity:0;transform:scale(.8)}to{opacity:1;transform:none}}@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(19,128,79,.5)}50%{box-shadow:0 0 0 6px rgba(19,128,79,0)}}
</style><script>const P=__DATA__,el=document.getElementById('pp'),C=['__PRIMARY__','__ACCENT__','__ACCENT2__','__GOOD__','__DEEP__','__WARN__'];
if(!P.length){el.innerHTML='<div class="empty">No one yet. Add your name in the sidebar.</div>'}
P.forEach((x,i)=>{const h=[...x.name].reduce((a,c)=>a+c.charCodeAt(0),0),ini=x.name.split(/\s+/).map(w=>w[0]).join('').slice(0,2).toUpperCase();
const d=document.createElement('div');d.className='p';d.style.animationDelay=(i*70)+'ms';d.title=x.n+' actions';
d.innerHTML='<div class="av'+(x.live?' live':'')+'" style="background:'+C[h%C.length]+'">'+ini+'</div><div><div class="nm">'+x.name.replace(/</g,'&lt;')+'</div><div class="sb">'+x.verb+' · '+x.ago+'</div></div>';el.appendChild(d)});</script>"""
    embed(html.replace("__DATA__", json.dumps(items)), height)


# ------------------------------------------------------------------ reserve tightness, drag to explore
def tightness_lab(ind: dict, height: int = 300) -> None:
    """Gauge plus four sliders that start at today's real readings. Dragging recomputes the score, the opening
    liquidity and the stress scenario in the browser, with the same rule as atlas.live.to_simulation."""
    data = json.dumps({"spread": ind["spread_bp"], "tail": ind["sofr_tail_bp"], "tga": ind["tga_5d_change_bn"], "rrp": ind["rrp_20d_avg_bn"]})
    html = """<div class="w"><div><svg viewBox="0 0 240 140" id="gg"></svg><div class="out"><div><div class="k mono">Opening liquidity</div><div class="v" id="liq">–</div></div>
<div><div class="k mono">Scenario</div><div class="v sm" id="stress">–</div></div></div></div><div id="sl"></div></div><style>
.w{background:#fff;border:1px solid __LINE__;border-radius:16px;padding:12px 16px;display:grid;grid-template-columns:250px 1fr;gap:22px;align-items:center}
@media(max-width:620px){.w{grid-template-columns:1fr}}.out{display:flex;gap:18px;justify-content:center;margin-top:2px}
.k{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:__MUTED__}.v{font:650 22px Inter;color:__INK__;font-variant-numeric:tabular-nums}.sm{font-size:15px;padding-top:5px}
.s{margin:9px 0}.t{display:flex;justify-content:space-between;font-size:12.5px;color:__INK2__;margin-bottom:3px}.t b{color:__INK__;font-variant-numeric:tabular-nums}
.t i{font-style:normal;color:__MUTED__;font-size:11px;margin-left:6px}input[type=range]{width:100%;accent-color:__PRIMARY__;cursor:grab}
.bar{height:5px;background:__SOFT__;border-radius:3px;overflow:hidden;margin-top:2px}.bar i{display:block;height:100%;background:__ACCENT__;transition:width .25s}
.rs{font:500 12px Inter;border:1px solid __LINE__;background:#fff;border-radius:999px;padding:4px 12px;cursor:pointer;color:__INK2__;float:right}.rs:hover{border-color:__PRIMARY__;color:__PRIMARY__}
</style><script>
const T=__DATA__,NS='http://www.w3.org/2000/svg',g=document.getElementById('gg');
const S=[{k:'spread',n:'SOFR − EFFR',u:' bp',min:-10,max:25,st:0.5,w:40,f:v=>Math.min(Math.max(v,0),15)/15*40},
{k:'tail',n:'SOFR 99th − 1st pct',u:' bp',min:0,max:40,st:0.5,w:20,f:v=>Math.min(Math.max(v-8,0),12)/12*20},
{k:'tga',n:'TGA 5-day change',u:' $bn',min:-150,max:200,st:1,w:20,f:v=>Math.min(Math.max(v,0),100)/100*20},
{k:'rrp',n:'RRP 20-day average',u:' $bn',min:0,max:800,st:1,w:20,f:v=>20*(1-Math.min(v,500)/500)}];
const arc=(a0,a1,r)=>{const p=a=>[120+r*Math.cos(a),125+r*Math.sin(a)];const [x0,y0]=p(a0),[x1,y1]=p(a1);return `M${x0},${y0} A${r},${r} 0 ${a1-a0>Math.PI?1:0} 1 ${x1},${y1}`};
const mk=(d,c,w)=>{const e=document.createElementNS(NS,'path');e.setAttribute('d',d);e.setAttribute('stroke',c);e.setAttribute('stroke-width',w);e.setAttribute('fill','none');e.setAttribute('stroke-linecap','round');g.appendChild(e);return e};
mk(arc(Math.PI,2*Math.PI,95),'__SOFT__',18);[[0,.35,'__GOOD__'],[.35,.65,'__WARN__'],[.65,1,'__BAD__']].forEach(([a,b,c])=>mk(arc(Math.PI*(1+a)+.02,Math.PI*(1+b)-.02,112),c,4));
const val=mk(arc(Math.PI,Math.PI*1.0001,95),'__PRIMARY__',18);
const tx=(y,st)=>{const t=document.createElementNS(NS,'text');t.setAttribute('x',120);t.setAttribute('y',y);t.setAttribute('text-anchor','middle');t.setAttribute('style',st);g.appendChild(t);return t};
const num=tx(112,'font:700 34px Inter;fill:__INK__'),lab=tx(134,'font:600 11px JetBrains Mono,monospace;letter-spacing:.14em;fill:__MUTED__');
const box=document.getElementById('sl'),cur={...T};let shown=0;
const rs=document.createElement('button');rs.className='rs';rs.textContent='Reset to today';box.appendChild(rs);
S.forEach(s=>{const d=document.createElement('div');d.className='s';d.innerHTML=`<div class="t"><span>${s.n}<i>today ${T[s.k]}${s.u}</i></span><b id="v_${s.k}"></b></div><input type="range" id="r_${s.k}" min="${s.min}" max="${s.max}" step="${s.st}" value="${T[s.k]}"><div class="bar"><i id="b_${s.k}"></i></div>`;
box.appendChild(d);d.querySelector('input').oninput=e=>{cur[s.k]=+e.target.value;upd()}});
rs.onclick=()=>{S.forEach(s=>{cur[s.k]=T[s.k];document.getElementById('r_'+s.k).value=T[s.k]});upd()};
function upd(){let score=0;S.forEach(s=>{const p=s.f(cur[s.k]);score+=p;document.getElementById('v_'+s.k).textContent=cur[s.k]+s.u;document.getElementById('b_'+s.k).style.width=(p/s.w*100)+'%'});
 const reg=score<35?'calm':score<65?'firm':'tight',liq=Math.round(Math.max(6,Math.min(26,24-score*0.16)));
 document.getElementById('liq').textContent=liq+'%';document.getElementById('stress').textContent=reg==='tight'?'Banks hoard':reg==='firm'?'Funding strain':'Normal day';
 lab.textContent=reg.toUpperCase()+' · TIGHTNESS';const from=shown,t0=performance.now();
 const step=n=>{const q=Math.min(1,(n-t0)/400),z=from+(score-from)*(1-Math.pow(1-q,3));val.setAttribute('d',arc(Math.PI,Math.PI*(1+Math.max(.0001,z/100)),95));num.textContent=Math.round(z);shown=z;if(q<1)requestAnimationFrame(step)};requestAnimationFrame(step)}
upd();</script>"""
    embed(html.replace("__DATA__", data), height)


# ------------------------------------------------------------------ a person's visits, past and current
def journey(name: str, visits: list[dict], returning: bool, viewer: bool = True, height: int | None = None) -> None:
    """Visits as columns, actions as dots coloured by kind. The current visit is outlined; hover a dot for detail."""
    data = json.dumps({"name": name, "v": visits[-8:], "returning": returning, "viewer": viewer,
                       "n": sum(len(x["items"]) for x in visits), "visits": len(visits),
                       "cases": sum(1 for x in visits for i in x["items"] if i["kind"] == "case_decision")})
    html = """<div class="j"><div class="hd"><div><div class="k mono" id="ey"></div><div class="h" id="hi"></div></div><div class="st" id="st"></div></div><div class="tr" id="tr"></div></div><style>
.j{background:#fff;border:1px solid __LINE__;border-radius:16px;padding:14px 16px}.hd{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.k{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:__MUTED__}.h{font:650 20px Inter;color:__INK__;letter-spacing:-.01em}
.st{display:flex;gap:8px}.c{border:1px solid __LINE__;border-radius:10px;padding:5px 11px;text-align:center}.c b{display:block;font:650 17px Inter;color:__INK__}.c span{font-size:10.5px;color:__MUTED__;letter-spacing:.06em;text-transform:uppercase}
.tr{display:flex;gap:10px;overflow-x:auto;padding:2px 2px 4px}.v{min-width:150px;border:1px solid __LINE__;border-radius:12px;padding:9px 11px;animation:in .4s ease-out both;background:__SOFT__}
.v.cur{border:2px solid __PRIMARY__;background:#fff}.d{font:600 12px Inter;color:__INK__;display:flex;justify-content:space-between}.d i{font-style:normal;font-weight:500;color:__MUTED__}
.now{font:600 9.5px 'JetBrains Mono',monospace;letter-spacing:.12em;color:#fff;background:__PRIMARY__;border-radius:4px;padding:1px 5px}
.dots{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.dot{width:11px;height:11px;border-radius:3px;animation:pop .35s cubic-bezier(.2,1.4,.4,1) both;cursor:default;position:relative}
.dot:hover{transform:scale(1.35)}.lg{display:flex;gap:12px;margin-top:10px;font-size:11px;color:__INK2__;flex-wrap:wrap}.lg i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:-1px}
.tt{position:fixed;pointer-events:none;background:__INK__;color:#fff;font:500 11.5px Inter;padding:5px 8px;border-radius:6px;opacity:0;transition:opacity .1s;max-width:260px;z-index:9}
@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}@keyframes pop{from{opacity:0;transform:scale(.3)}to{opacity:1;transform:none}}
</style><div class="tt" id="tt"></div><script>
const D=__DATA__,G={run:'__PRIMARY__',case:'__ACCENT__',agent:'__ACCENT2__',review:'__GOOD__',data:'__WARN__',other:'__ACCENT3__'};
const grp=k=>({ran_day:'run',ran_live_market:'run',compared:'run',pinned:'run',case_decision:'case',asked:'agent',review:'review',uploaded:'data',exported:'data'}[k]||'other');
document.getElementById('ey').textContent=D.viewer?(D.returning?'Welcome back':'Welcome'):'Activity';
document.getElementById('hi').textContent=D.name+(D.viewer&&!D.returning?' · first visit':'');
document.getElementById('st').innerHTML=[[D.visits,'visits'],[D.n,'actions'],[D.cases,'cases']].map(([a,b])=>`<div class="c"><b>${a}</b><span>${b}</span></div>`).join('');
const tr=document.getElementById('tr'),tt=document.getElementById('tt');let k=0;
D.v.forEach((v,i)=>{const e=document.createElement('div');e.className='v'+(v.current?' cur':'');e.style.animationDelay=(i*80)+'ms';
 e.innerHTML=`<div class="d"><span>${v.day} <i>${v.from}–${v.to||v.from}</i></span>${v.current?'<span class="now">NOW</span>':''}</div><div class="dots"></div>`;
 const ds=e.querySelector('.dots');v.items.forEach(it=>{const d=document.createElement('div');d.className='dot';d.style.background=G[grp(it.kind)];d.style.animationDelay=(80*i+25*(k++))+'ms';
 d.onmouseenter=ev=>{tt.textContent=it.t+'  '+it.verb+(it.note?' · '+it.note:'');tt.style.opacity=1};d.onmousemove=ev=>{tt.style.left=(ev.clientX+12)+'px';tt.style.top=(ev.clientY-30)+'px'};d.onmouseleave=()=>tt.style.opacity=0;ds.appendChild(d)});
 tr.appendChild(e)});
if(!D.v.length)tr.innerHTML='<div style="color:__INK2__;font-size:13px">Run a day and your activity appears here.</div>';
const lg=document.createElement('div');lg.className='lg';lg.innerHTML=[['run','simulations'],['case','case decisions'],['agent','agent questions'],['review','reviews'],['data','files']].map(([g,t])=>`<span><i style="background:${G[g]}"></i>${t}</span>`).join('');
document.querySelector('.j').appendChild(lg);</script>"""
    embed(html.replace("__DATA__", data), height or 200)
