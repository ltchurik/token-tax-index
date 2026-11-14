"""Render a static leaderboard (site/index.html + site/data.json) from results/*.json."""
import html
import json
import statistics
from pathlib import Path

from . import __version__
from .corpus import BASE
from .registry import read_data

REPO = "https://github.com/ltchurik/token-tax-index"


def load_results(results_dir):
    out = []
    for p in sorted(Path(results_dir).glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "tokenizer" in data and "langs" in data:
            out.append(data)
    return out


def leaderboard(results):
    """Rows of (lang, median ratio, {tokenizer: ratio}) sorted by median ratio, highest tax first."""
    langs = sorted({lg for r in results for lg in r["langs"] if lg != BASE})
    rows = []
    for lg in langs:
        cells = {r["tokenizer"]: r["langs"][lg]["ratio_vs_en"] for r in results if lg in r["langs"]}
        rows.append((lg, round(statistics.median(cells.values()), 3), cells))
    rows.sort(key=lambda x: (-x[1], x[0]))
    return rows


def _shade(ratio):
    # 1.0 -> neutral, >= 3.0 -> strongest; below 1.0 -> "cheaper than English"
    if ratio < 1:
        return "lt"
    return f"r{min(5, int((ratio - 1) / 0.4) + 1)}" if ratio > 1.05 else "eq"


CSS = """
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--line:#e7e5e4;--card:#fff;--lt:#dcfce7;--eq:#f5f5f4;
--r1:#fef9c3;--r2:#fde68a;--r3:#fdba74;--r4:#fb923c;--r5:#f87171;--accent:#b45309}
@media (prefers-color-scheme:dark){:root{--bg:#0c0a09;--fg:#e7e5e4;--muted:#a8a29e;--line:#292524;--card:#1c1917;
--lt:#14532d;--eq:#292524;--r1:#422006;--r2:#713f12;--r3:#7c2d12;--r4:#9a3412;--r5:#991b1b;--accent:#f59e0b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.8rem;margin:0 0 4px}a{color:var(--accent)}
.lead{color:var(--muted);margin:0 0 20px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
.wrap{overflow-x:auto}table{border-collapse:collapse;font-variant-numeric:tabular-nums;width:100%}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{position:sticky;top:0;background:var(--card);cursor:pointer;font-weight:600;font-size:.85rem}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card)}
td.lt{background:var(--lt)}td.eq{background:var(--eq)}td.r1{background:var(--r1)}td.r2{background:var(--r2)}
td.r3{background:var(--r3)}td.r4{background:var(--r4)}td.r5{background:var(--r5)}
.code{color:var(--muted);font-size:.8rem}input{width:100%;max-width:320px;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
footer{color:var(--muted);font-size:.85rem;margin-top:32px}
"""

JS = """
const t=document.querySelector('#lb');if(t){
document.querySelector('#q').addEventListener('input',e=>{const q=e.target.value.toLowerCase();
for(const r of t.tBodies[0].rows)r.style.display=r.cells[0].textContent.toLowerCase().includes(q)?'':'none'});
t.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{const b=t.tBodies[0],rs=[...b.rows];
const dir=th.dataset.d=th.dataset.d==='1'?'-1':'1';rs.sort((a,c)=>{const x=a.cells[i].dataset.v??a.cells[i].textContent,
y=c.cells[i].dataset.v??c.cells[i].textContent;const nx=parseFloat(x),ny=parseFloat(y);
return (isNaN(nx)||isNaN(ny)?x.localeCompare(y):nx-ny)*dir});rs.forEach(r=>b.appendChild(r))}))}
"""


def render(results, names=None):
    names = names if names is not None else read_data("language_names.json")["names"]
    e = html.escape
    head = (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Token Tax Index</title>"
        "<meta name=description content='Token Tax Index: how much more each of 200 languages costs in LLM tokens than English, per tokenizer (GPT, Claude, Gemini, Llama, Qwen), with API prices.'>"
        "<meta name=author content='Ľubomír Tchurik'>"
        "<link rel=canonical href='https://ltchurik.github.io/token-tax-index/'>"
        "<meta property=og:title content='Token Tax Index: the LLM token cost of every language'>"
        "<meta property=og:description content='How much more each language costs in LLM tokens than English, per tokenizer, with API prices.'>"
        "<meta property=og:type content=website>"
        "<meta property=og:url content='https://ltchurik.github.io/token-tax-index/'>"
        "<meta name=twitter:card content=summary>"
        f"<style>{CSS}</style></head><body><main>"
        "<h1>Token Tax Index</h1>"
        "<p class=lead>How many more tokens does the same text need in each language than in English? "
        "1.00&nbsp;= same as English; 2.00&nbsp;= twice the tokens, twice the API price, half the context window.</p>"
    )
    if not results:
        body = (
            "<div class=card><strong>No data yet.</strong> The index is in early development; "
            f"the first results will appear here after the first benchmark run. "
            f"Follow or contribute on <a href='{REPO}'>GitHub</a>.</div>"
        )
    else:
        toks = sorted(results, key=lambda r: (r.get("group", ""), r["tokenizer"]))
        tnames = [r["tokenizer"] for r in toks]
        meta = toks[0]
        hdr = "<tr><th>Language</th><th>Median</th>" + "".join(f"<th>{e(n)}</th>" for n in tnames) + "</tr>"
        trs = []
        for lg, med, cells in leaderboard(results):
            label = f"{e(names.get(lg, lg))} <span class=code>{e(lg)}</span>"
            tds = "".join(
                f"<td class={_shade(cells[n])} data-v={cells[n]}>{cells[n]:.2f}</td>" if n in cells else "<td data-v=-1>–</td>"
                for n in tnames
            )
            trs.append(f"<tr><td data-v='{e(names.get(lg, lg))}'>{label}</td><td class={_shade(med)} data-v={med}><b>{med:.2f}</b></td>{tds}</tr>")
        body = (
            f"<p>Corpus: {e(str(meta.get('corpus', '')))} ({meta.get('n_sentences', '?')} parallel sentences), "
            f"{len(results)} tokenizers, {len(trs)} languages. Click a column to sort.</p>"
            "<input id=q placeholder='Filter languages…' aria-label='Filter languages'>"
            f"<div class='card wrap'><table id=lb><thead>{hdr}</thead><tbody>{''.join(trs)}</tbody></table></div>"
        )
    foot = (
        f"<footer>token-tax-index v{e(__version__)} · <a href='{REPO}'>source &amp; method</a> · "
        "FLORES-200 © Meta, CC BY-SA 4.0 · by <a href='https://lubomirtchurik.sk'>Ľubomír Tchurik</a></footer>"
        f"</main><script>{JS}</script></body></html>\n"
    )
    return head + body + foot


def build(results_dir, out_dir):
    results = load_results(results_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(render(results), encoding="utf-8")
    (out / "data.json").write_text(json.dumps(results, ensure_ascii=False) + "\n", encoding="utf-8")
    return out / "index.html", len(results)
