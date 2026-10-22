"""Local, read-only Seven Horses dashboard. Run with uvicorn from repo root."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from .config import settings

app = FastAPI(title="Seven Horses Dashboard", docs_url=None, redoc_url=None)
SYMBOLS = tuple(settings.symbols)
DATA = settings.data_dir


def read_json(filename):
    try:
        return json.loads((DATA / filename).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def parse_time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    except (TypeError, ValueError):
        return None


def latest_ticks():
    """Read recent JSONL backwards, stopping when all seven latest records are found."""
    path = DATA / "live_ticks.jsonl"
    found = {}
    if not path.is_file():
        return found
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            end = f.tell()
            start = max(0, end - 8 * 1024 * 1024)
            f.seek(start)
            chunk = f.read()
        if start:
            i = chunk.find(b"\n")
            chunk = chunk[i + 1:] if i >= 0 else b""
        for line in reversed(chunk.splitlines()):
            try:
                row = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            symbol = row.get("symbol")
            if symbol in SYMBOLS and symbol not in found:
                found[symbol] = row
                if len(found) == len(SYMBOLS):
                    break
    except OSError:
        pass
    return found


@app.get("/api/state")
def state():
    now = datetime.now(timezone.utc)
    records = latest_ticks()
    ticks = {}
    ages = []
    for symbol in SYMBOLS:
        row = records.get(symbol, {})
        stamp = parse_time(row.get("received_at"))
        age = max(0, (now - stamp.astimezone(timezone.utc)).total_seconds()) if stamp else None
        if age is not None:
            ages.append(age)
        status = "NO DATA" if age is None else "LIVE" if age <= 20 else "DELAYED" if age <= 90 else "STALE"
        ticks[symbol] = {"symbol": symbol, "last_price": row.get("last_price"), "volume": row.get("volume"),
                         "average_price": row.get("average_price"), "ohlc": row.get("ohlc"),
                         "exchange_timestamp": row.get("exchange_timestamp"), "received_at": row.get("received_at"),
                         "age_seconds": round(age, 1) if age is not None else None, "status": status}
    feed = "NO DATA" if not ages else "LIVE" if max(ages) <= 20 else "DELAYED" if max(ages) <= 90 else "STALE"
    quality = read_json("data_quality_report.json")
    backtest_path = DATA / "backtest_summary.json"
    try:
        backtest = {"available": backtest_path.is_file(), "modified_at": datetime.fromtimestamp(backtest_path.stat().st_mtime, timezone.utc).astimezone().isoformat() if backtest_path.is_file() else None,
                    "size_bytes": backtest_path.stat().st_size if backtest_path.is_file() else 0}
    except OSError:
        backtest = {"available": False, "modified_at": None, "size_bytes": 0}
    return {"as_of": datetime.now().astimezone().isoformat(), "feed_status": feed,
            "tick_log_exists": (DATA / "live_ticks.jsonl").is_file(), "symbols": list(SYMBOLS), "ticks": ticks,
            "signals": read_json("latest_signals.json") or {}, "allocations": read_json("latest_allocations.json") or {},
            "data_quality": quality, "backtest": backtest, "signals_only": True, "order_placement_enabled": False}


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Seven Horses | Market Monitor</title>
<style>
:root{color-scheme:dark;--bg:#09111d;--panel:#111e2e;--line:#293b50;--text:#eef4ff;--muted:#91a4bc;--green:#55d6a0;--red:#ff8189;--amber:#f4c46e}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 10% 0%,#19314b 0,var(--bg) 48%);color:var(--text);font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif}main{max-width:1400px;margin:auto;padding:24px}header{display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap;margin-bottom:18px}.eyebrow{color:var(--green);font-size:11px;letter-spacing:.16em;font-weight:800}.brand{font-size:28px;font-weight:850;letter-spacing:-.04em}.sub,.muted,.note{color:var(--muted)}.pill,.badge{border:1px solid var(--line);border-radius:999px;padding:7px 10px;font-size:11px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--amber);margin-right:7px}.dot.live{background:var(--green)}.dot.stale{background:var(--red)}.grid{display:grid;gap:13px}.metrics{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:13px}.columns{grid-template-columns:minmax(0,1.5fr) minmax(300px,1fr)}.panel{min-width:0;background:linear-gradient(145deg,#142337,#101a29);border:1px solid var(--line);border-radius:15px;padding:16px;box-shadow:0 8px 24px #0002}.label{color:var(--muted);font-size:12px}.value{font-size:24px;font-weight:800;margin-top:4px}.note{font-size:11px;margin-top:4px}.title{font-size:15px;font-weight:800;margin:0 0 12px}.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap}th{text-align:left;color:var(--muted);font-size:10px;letter-spacing:.07em;padding:9px 7px;border-bottom:1px solid var(--line)}td{padding:11px 7px;border-bottom:1px solid #243449;font-variant-numeric:tabular-nums}tr:last-child td{border:0}.badge{display:inline-block;border:0;border-radius:5px;padding:4px 6px;font-weight:800;background:#29374b;color:#c8d3e2}.LIVE,.PASS,.HOLD{background:#153c33;color:var(--green)}.DELAYED,.BUY_WATCH{background:#40351f;color:var(--amber)}.STALE,.NO_DATA,.EXIT_WATCH{background:#40232a;color:var(--red)}.BUY_CONFIRMED{background:#203656;color:#b4d0ff}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.sig{border:1px solid var(--line);border-radius:11px;padding:12px;background:#0d1725}.sighead{display:flex;justify-content:space-between;align-items:center;gap:6px;font-weight:800}.price{font-size:19px;font-weight:800;margin:8px 0 2px}.ind{display:grid;grid-template-columns:1fr 1fr;gap:6px;color:var(--muted);font-size:11px;margin:10px 0}.ind b{color:var(--text)}.reason{font-size:11px;color:#b1bfd0}.kv{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid #243449}.kv:last-child{border:0}.kv span:first-child{color:var(--muted)}.race{display:grid;gap:9px}.lane{display:grid;grid-template-columns:82px 1fr 48px;gap:8px;align-items:center}.track{height:29px;border:1px solid #354a60;border-radius:6px;position:relative;overflow:hidden;background:repeating-linear-gradient(90deg,#17283b 0,#17283b 24%,#22364a 24%,#22364a 25%)}.track:after{content:"";position:absolute;left:50%;height:100%;border-left:1px dashed #8190a355}.horse{position:absolute;left:var(--pos);top:3px;transform:translateX(-50%);font-size:18px;transition:left 1s ease}.ret{text-align:right;font-size:11px}.foot{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:11px;margin:16px 2px}.warn{color:var(--amber);font-size:11px;margin-top:12px}@media(max-width:950px){.columns{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:600px){main{padding:12px}.cards{grid-template-columns:1fr}.panel{padding:12px}.brand{font-size:23px}.lane{grid-template-columns:72px 1fr 46px}}
</style></head><body><main>
<header><div><div class="eyebrow">READ-ONLY MARKET INTELLIGENCE</div><div class="brand">SEVEN HORSES <span style="color:var(--green)">/</span> AI</div><div class="sub">NSE swing monitor · Seven symbols · Manual review only</div></div><div class="pill"><span id="dot" class="dot"></span><b id="feed">CONNECTING</b> · <span id="asof">Waiting for data</span></div></header>
<div class="grid metrics"><div class="panel"><div class="label">Live feed</div><div class="value" id="mfeed">—</div><div class="note" id="mfeednote">Tick freshness</div></div><div class="panel"><div class="label">BUY WATCH / CONFIRMED</div><div class="value" id="mbuy">—</div><div class="note">Research states, not orders</div></div><div class="panel"><div class="label">Actual deployment</div><div class="value" id="mdeploy">—</div><div class="note" id="mdeploynote">Configured risk limits</div></div><div class="panel"><div class="label">Data-quality report</div><div class="value" id="mquality">—</div><div class="note">Last saved validation</div></div></div>
<div class="grid columns"><div class="grid"><section class="panel"><h2 class="title">Live market tape <span class="note">· existing JSONL stream</span></h2><div class="tablewrap"><table><thead><tr><th>Symbol</th><th>Last ₹</th><th>Day %*</th><th>Volume</th><th>Tick age</th><th>Status</th></tr></thead><tbody id="market"><tr><td colspan="6">Loading…</td></tr></tbody></table></div><div class="note">*Change versus the tick's OHLC close field; not previous-session change.</div></section>
<section class="panel"><h2 class="title">Momentum racetrack <span class="note">· 20-day return, not a forecast</span></h2><div class="race" id="race">Loading…</div></section>
<section class="panel"><h2 class="title">Signal cards <span class="note">· last completed daily candle</span></h2><div class="grid cards" id="cards">Loading…</div></section></div>
<div class="grid"><section class="panel"><h2 class="title">Portfolio guardrails</h2><div id="risk">Loading…</div><div class="warn">Order placement is disabled. Target weights are research outputs, not executed positions.</div></section><section class="panel"><h2 class="title">System health</h2><div id="health">Loading…</div><div id="err" class="warn"></div></section><section class="panel"><h2 class="title">Backtest report</h2><div id="backtest">Loading…</div><div class="note">A saved report does not establish future performance. Review costs, corporate actions and walk-forward results.</div></section></div></div>
<footer class="foot"><span>Local development · No order placement</span><span>Refreshes every 3 seconds · <span id="footTime">—</span></span></footer></main>
<script>
const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])), fmt=(v,d=2)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d}):'—', whole=v=>typeof v==='number'?v.toLocaleString('en-IN',{maximumFractionDigits:0}):'—', badge=s=>`<span class="badge ${esc(s)}">${esc(s||'UNKNOWN')}</span>`, age=v=>v==null?'—':v<60?Math.round(v)+'s':Math.floor(v/60)+'m '+Math.round(v%60)+'s';
function kv(rows){return rows.map(([k,v])=>`<div class="kv"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('')}
function render(d){const syms=d.symbols||[], sig=d.signals||{}, alloc=d.allocations||{}, ticks=d.ticks||{}, q=d.data_quality; $('feed').textContent=d.feed_status;$('dot').className='dot '+(d.feed_status==='LIVE'?'live':['STALE','NO DATA'].includes(d.feed_status)?'stale':'');$('asof').textContent='Updated '+new Date(d.as_of).toLocaleTimeString();$('footTime').textContent=new Date(d.as_of).toLocaleString();$('mfeed').textContent=d.feed_status;const live=Object.values(ticks).filter(t=>t.status==='LIVE').length;$('mfeednote').textContent=`${live}/${syms.length} symbols with ticks ≤20 seconds`;const buys=syms.filter(s=>['BUY_WATCH','BUY_CONFIRMED'].includes(sig[s]?.signal)).length;$('mbuy').textContent=buys;$('mdeploy').textContent=fmt(Number(alloc.actual_deployed_pct)||0,1)+'%';$('mdeploynote').textContent='Max deployment '+fmt(alloc.max_deployed_pct,1)+'%';let qualityText='Missing';if(q){const vals=Object.values(q).filter(x=>x&&typeof x==='object');const pass=vals.filter(x=>String(x.status||'').toUpperCase()==='PASS').length;qualityText=pass?`${pass} PASS`:'Available'}$('mquality').textContent=qualityText;
$('market').innerHTML=syms.map(s=>{const t=ticks[s]||{},o=t.ohlc||{},change=typeof t.last_price==='number'&&typeof o.close==='number'&&o.close?100*(t.last_price/o.close-1):null;return `<tr><td><b>${esc(s)}</b></td><td><b>${fmt(t.last_price)}</b></td><td style="color:${change==null?'var(--muted)':change>=0?'var(--green)':'var(--red)'}">${change==null?'—':(change>=0?'+':'')+fmt(change)+'%'}</td><td>${whole(t.volume)}</td><td>${age(t.age_seconds)}</td><td>${badge(t.status)}</td></tr>`}).join('');
$('cards').innerHTML=syms.map(s=>{const x=sig[s]||{},a=alloc.symbols?.[s]||{};return `<article class="sig"><div class="sighead"><span>${esc(s)}</span>${badge(x.signal||'NO SIGNAL')}</div><div class="price">₹${fmt(x.close)}</div><div class="note">Candle: ${esc(x.timestamp||'—')}</div><div class="ind"><span>EMA20 <b>${fmt(x.ema20)}</b></span><span>EMA50 <b>${fmt(x.ema50)}</b></span><span>RSI14 <b>${fmt(x.rsi14)}</b></span><span>ATR14 <b>${fmt(x.atr14)}</b></span><span>20d return <b>${x.return20_pct==null?'—':fmt(x.return20_pct)+'%'}</b></span><span>Rel. volume <b>${fmt(x.relative_volume)}</b></span></div><div class="reason">${esc(Array.isArray(x.reasons)?x.reasons.slice(0,2).join(' '):'No explanation available.')}</div><div class="kv" style="margin-top:8px"><span>Target weight</span><b>${fmt(Number(a.target_weight_pct)||0)}%</b></div></article>`}).join('');
const rs=syms.map(s=>({s,r:sig[s]?.return20_pct})).filter(x=>typeof x.r==='number'&&Number.isFinite(x.r));const mn=Math.min(0,...rs.map(x=>x.r)),mx=Math.max(0,...rs.map(x=>x.r)),span=Math.max(1,mx-mn);$('race').innerHTML=rs.map(x=>`<div class="lane"><b>${esc(x.s)}</b><div class="track"><span class="horse" style="--pos:${8+(x.r-mn)/span*84}%">♞</span></div><div class="ret" style="color:${x.r>=0?'var(--green)':'var(--red)'}">${x.r>=0?'+':''}${fmt(x.r)}%</div></div>`).join('')||'No valid 20-day returns.';
$('risk').innerHTML=kv([['Mode',alloc.mode||'—'],['Signals only',alloc.signals_only===true?'Enabled':'Check config'],['Order placement',d.order_placement_enabled?'Enabled':'Disabled'],['Actual deployed',fmt(Number(alloc.actual_deployed_pct)||0)+'%'],['Maximum deployment',fmt(alloc.max_deployed_pct)+'%'],['Maximum per symbol',fmt(alloc.max_symbol_weight_pct)+'%'],['Universe size',syms.length],['BUY WATCH / CONFIRMED',buys]]);$('health').innerHTML=kv([['Tick log',d.tick_log_exists?'Present':'Missing'],['Signals',Object.keys(sig).length?'Loaded':'Missing'],['Allocations',Object.keys(alloc).length?'Loaded':'Missing'],['Quality report',q?'Loaded':'Missing'],['Latest API refresh',new Date(d.as_of).toLocaleTimeString()]]);const b=d.backtest||{};$('backtest').innerHTML=kv([['Report',b.available?'Available':'Missing'],['Modified',b.modified_at?new Date(b.modified_at).toLocaleString():'—'],['Size',b.size_bytes?fmt(b.size_bytes/1024,1)+' KB':'—']]);$('err').textContent='';}
async function refresh(){try{const r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);render(await r.json())}catch(e){$('err').textContent='Dashboard API error: '+e.message;$('feed').textContent='API ERROR';$('dot').className='dot stale'}}refresh();setInterval(refresh,3000);
</script></body></html>'''
