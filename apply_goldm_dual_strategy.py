
from pathlib import Path
import sys

ROOT = Path.cwd()
scanner_path = ROOT / "app" / "commodities" / "goldm_scanner.py"
html_path = ROOT / "dashboard" / "goldm.html"

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}. Stopped without writing files.")
    return text.replace(old, new, 1)

if not scanner_path.exists() or not html_path.exists():
    sys.exit("Run from the repository root. Expected app/commodities/goldm_scanner.py and dashboard/goldm.html.")
if not (ROOT / "app/commodities/goldm_strategy_comparison.py").exists():
    sys.exit("Missing app/commodities/goldm_strategy_comparison.py. Extract the whole ZIP into the repository root.")

scanner = scanner_path.read_text(encoding="utf-8")
scanner = replace_once(scanner,
    "from app.commodities.goldm_engine import GoldMShadowEngine\n",
    "from app.commodities.goldm_engine import GoldMShadowEngine\nfrom app.commodities.goldm_strategy_comparison import compare_strategies\n",
    "scanner import")
scanner = replace_once(scanner,
    '"message": "GOLDM scanner initializing", "scoring_status": "SHADOW MODE: experimental scores only; not calibrated",\n',
    '"message": "GOLDM scanner initializing", "scoring_status": "SHADOW MODE: experimental scores only; not calibrated",\n'
    '            "strategy_comparison": {"status": "NO_TRADE", "best_candidate": None, "strategies": {}},\n',
    "initial scanner state")
scanner = replace_once(scanner,
    '        with self.lock:\n            payload = dict(self.state)\n            if message:\n                payload["message"] = message\n        publish_goldm(payload)\n',
    '        with self.lock:\n'
    '            comparison = compare_strategies(list(self.engine.future_history), self._option_rows(), time.time())\n'
    '            self.state["strategy_comparison"] = comparison\n'
    '            payload = dict(self.state)\n'
    '            if message:\n'
    '                payload["message"] = message\n'
    '        publish_goldm(payload)\n',
    "publish comparison")
scanner = replace_once(scanner,
    '                    "volume": tick.get("volume_traded", tick.get("volume")),\n',
    '                    "volume": tick.get("volume_traded", tick.get("volume")),\n'
    '                    "best_bid": (tick.get("depth", {}).get("buy") or [{}])[0].get("price"),\n'
    '                    "best_ask": (tick.get("depth", {}).get("sell") or [{}])[0].get("price"),\n',
    "capture depth")
scanner = replace_once(scanner,
    '                "ltp": tick.get("last_price"),\n                "oi": tick.get("oi"),\n',
    '                "ltp": tick.get("last_price"),\n'
    '                "best_bid": tick.get("best_bid"),\n'
    '                "best_ask": tick.get("best_ask"),\n'
    '                "spread_percent": (\n'
    '                    (float(tick["best_ask"]) - float(tick["best_bid"]))\n'
    '                    / ((float(tick["best_ask"]) + float(tick["best_bid"])) / 2.0) * 100.0\n'
    '                    if tick.get("best_bid") and tick.get("best_ask")\n'
    '                    and float(tick["best_bid"]) > 0 and float(tick["best_ask"]) >= float(tick["best_bid"])\n'
    '                    else None\n'
    '                ),\n'
    '                "oi": tick.get("oi"),\n',
    "option quote output")
html = html_path.read_text(encoding="utf-8")
html = replace_once(html,
    '<div class="card" style="margin-bottom:15px"><div class="title"><h2>GOLDM Options / Tracked Contracts</h2>',
    '<div class="strategy-grid">\n'
    '<div class="card strategy-card"><div class="title"><h2>Strategy A · Intraday Momentum</h2><span class="tag" id="momentumStatus">Warming up</span></div><div class="big" id="momentumScore">—</div><div class="label" id="momentumDirection">Direction: —</div><p class="muted" id="momentumReason">Collecting futures history…</p><div class="muted" id="momentumCandidate">Candidate: —</div></div>\n'
    '<div class="card strategy-card"><div class="title"><h2>Strategy B · Trend Following</h2><span class="tag" id="trendStatus">Warming up</span></div><div class="big" id="trendScore">—</div><div class="label" id="trendDirection">Direction: —</div><p class="muted" id="trendReason">Collecting futures history…</p><div class="muted" id="trendCandidate">Candidate: —</div></div>\n'
    '<div class="card strategy-card winner-card"><div class="title"><h2>Best Eligible Candidate</h2><span class="tag" id="winnerStatus">NO TRADE</span></div><div class="big" style="font-size:18px" id="winnerSymbol">NO TRADE</div><div class="label" id="winnerScore">Score: —</div><p class="muted" id="winnerReason">No eligible candidate yet. Monitoring only.</p></div>\n'
    '</div>\n'
    '<div class="card" style="margin-bottom:15px"><div class="title"><h2>GOLDM Options / Tracked Contracts</h2>',
    "strategy cards")
html = replace_once(html,
    '.top-score-row td{background:rgba(72,214,160,.13);',
    '.strategy-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px;margin-bottom:15px}.strategy-card{min-height:190px}.winner-card{border-color:rgba(72,214,160,.6)}\n.top-score-row td{background:rgba(72,214,160,.13);',
    "strategy css")
html = replace_once(html,
    '@media(max-width:900px){.layout{grid-template-columns:1fr}.grid{grid-template-columns:1fr}}',
    '@media(max-width:900px){.layout{grid-template-columns:1fr}.grid{grid-template-columns:1fr}.strategy-grid{grid-template-columns:1fr}}',
    "responsive css")
html = replace_once(html,
    "function render(p){const s=p.snapshot||{},g=s.goldm||{};$('ltp')",
    'function render(p){const s=p.snapshot||{},g=s.goldm||{};const c=g.strategy_comparison||{};const st=c.strategies||{};const m=st.momentum||{},t=st.trend||{};const winner=c.best_candidate;const putStrategy=(prefix,x)=>{$(prefix+"Score").textContent=x.score===null||x.score===undefined?"—":num(x.score)+"/100";$(prefix+"Status").textContent=x.candidate_status||x.status||"Warming up";$(prefix+"Direction").textContent="Direction: "+(x.direction||"—");$(prefix+"Reason").textContent=x.reason||"Waiting for confirmation";const candidate=x.candidate;$(prefix+"Candidate").textContent="Candidate: "+(candidate?candidate.tradingsymbol+" · "+candidate.option_type+" · "+num(candidate.score)+"/100":"None");};putStrategy("momentum",m);putStrategy("trend",t);$("winnerStatus").textContent=c.status||"NO_TRADE";$("winnerSymbol").textContent=winner?(winner.tradingsymbol+" · "+winner.option_type):"NO TRADE";$("winnerScore").textContent=winner?("Combined ranking score: "+num(winner.score)+"/100"):"No eligible candidate";$("winnerReason").textContent=winner?(winner.strategy+" · "+winner.direction+" · "+(winner.reason||"")):(c.message||"Wait for valid data and confirmed setup.");$("ltp")',
    "render strategy comparison")
html = replace_once(html,
    'const a=g.options||[];const eligible=a.filter(o=>o.score!==null&&o.score!==undefined&&o.score!==""&&Number.isFinite(Number(o.score))&&String(o.score_status||"").startsWith("SHADOW_ONLY_UNCALIBRATED"));const top=eligible.length?eligible.reduce((best,o)=>Number(o.score)>Number(best.score)?o:best,null):null;',
    'const a=g.options||[];const topSymbol=winner&&winner.tradingsymbol;',
    "candidate row selector")
html = replace_once(html,
    'const isTop=top&&o===top;',
    'const isTop=topSymbol&&o.tradingsymbol===topSymbol;',
    "candidate row highlight")
scanner_path.write_text(scanner, encoding="utf-8")
html_path.write_text(html, encoding="utf-8")
print("Applied GOLDM dual-strategy comparison integration.")
print("Review with: git diff -- app/commodities/goldm_scanner.py dashboard/goldm.html")
print("Test with: python -m unittest app.commodities.test_goldm_engine app.commodities.test_goldm_strategy_comparison")
