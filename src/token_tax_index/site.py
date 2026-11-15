"""Render the static Token Tax Index site (site/index.html + site/data.json) from results/*.json."""
import html
import json
import shutil
import statistics
from pathlib import Path

from . import __version__
from .corpus import BASE
from .registry import read_data

REPO = "https://github.com/ltchurik/token-tax-index"
SITE = "https://ltchurik.github.io/token-tax-index/"
AUTHOR = "Ľubomír Tchurik"
AUTHOR_URL = "https://lubomirtchurik.sk/"
FIRST_PUBLISHED = "2026-11-14"  # first deploy of the leaderboard
CONCEPT_DOI = "10.5281/zenodo.24253588"  # Zenodo, resolves to the latest release

# Column order on the page. Unknown groups go after these, "Reference" always last.
GROUP_ORDER = ["OpenAI", "Anthropic", "Google", "Meta", "Mistral", "China", "European", "Other", "Regional"]
# Vendors whose current tokenizers make up the headline "major models" median.
MAJOR_GROUPS = {"OpenAI", "Anthropic", "Google", "Meta", "Mistral", "China"}
NOT_HEADLINE = ("legacy", "cl100k", "Llama 2", "mT5")
# Default language for the "your language" picker, by browser language.
BROWSER_LANG = {
    "sk": "slk_Latn", "cs": "ces_Latn", "pl": "pol_Latn", "hu": "hun_Latn", "de": "deu_Latn", "fr": "fra_Latn",
    "es": "spa_Latn", "it": "ita_Latn", "pt": "por_Latn", "nl": "nld_Latn", "uk": "ukr_Cyrl", "ru": "rus_Cyrl",
    "ja": "jpn_Jpan", "ko": "kor_Hang", "zh": "zho_Hans", "ar": "arb_Arab", "hi": "hin_Deva", "tr": "tur_Latn",
    "el": "ell_Grek", "he": "heb_Hebr", "ro": "ron_Latn", "bg": "bul_Cyrl", "hr": "hrv_Latn", "sl": "slv_Latn",
    "sv": "swe_Latn", "da": "dan_Latn", "fi": "fin_Latn", "vi": "vie_Latn", "th": "tha_Thai", "id": "ind_Latn",
}


def load_results(results_dir):
    out = []
    for p in sorted(Path(results_dir).glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "tokenizer" in data and "langs" in data:
            out.append(data)
    return out


def ordered(results):
    """Results in display order: by vendor group, then name; the byte reference last."""
    def key(r):
        g = r.get("group", "")
        rank = len(GROUP_ORDER) + 1 if g == "Reference" else (GROUP_ORDER.index(g) if g in GROUP_ORDER else len(GROUP_ORDER))
        return (rank, r["tokenizer"])
    return sorted(results, key=key)


def headline(results):
    """Tokenizers behind the headline median: current major-vendor tokenizers, duplicates removed.

    Several models share one vocabulary (e.g. Phi-4-mini uses o200k), which would otherwise
    count twice. Falls back to every non-reference tokenizer when no major vendor is present.
    """
    picked, seen = [], set()
    for r in ordered(results):
        if r.get("group") not in MAJOR_GROUPS or any(s in r["tokenizer"] for s in NOT_HEADLINE):
            continue
        sig = tuple(sorted((lg, v["tokens"]) for lg, v in r["langs"].items()))
        if sig in seen:
            continue
        seen.add(sig)
        picked.append(r)
    return picked or [r for r in results if r.get("group") != "Reference"] or list(results)


def leaderboard(results):
    """Rows of (lang, headline median ratio, {tokenizer: ratio}) sorted by median, highest tax first."""
    head = {r["tokenizer"] for r in headline(results)}
    langs = sorted({lg for r in results for lg in r["langs"] if lg != BASE})
    rows = []
    for lg in langs:
        cells = {r["tokenizer"]: r["langs"][lg]["ratio_vs_en"] for r in results if lg in r["langs"]}
        core = [v for t, v in cells.items() if t in head] or list(cells.values())
        rows.append((lg, round(statistics.median(core), 3), cells))
    rows.sort(key=lambda x: (-x[1], x[0]))
    return rows


def findings(results, rows, names):
    """A few headline numbers computed from the data (never hard-coded)."""
    head = headline(results)
    n = len(rows)
    double = sum(1 for _, m, _ in rows if m >= 2)
    worst_lg, worst_m, _ = rows[0]
    per_tok = sorted(
        (statistics.median(v["ratio_vs_en"] for lg, v in r["langs"].items() if lg != BASE), r["tokenizer"]) for r in head
    )
    out = [
        (f"{double} of {n}", "languages need at least <b>twice as many tokens</b> as English on major models (median)."),
        (f"{worst_m:.1f}×", f"<b>{html.escape(names.get(worst_lg, worst_lg))}</b> is the most expensive language: "
                            f"the same text costs {worst_m:.1f}× the English price."),
    ]
    if len(per_tok) >= 2:
        (best_m, best_t), (worst_tm, worst_t) = per_tok[0], per_tok[-1]
        out.append((
            f"{best_m:.2f}× vs {worst_tm:.2f}×",
            f"The fairest major tokenizer is <b>{html.escape(best_t)}</b>; the least fair is "
            f"<b>{html.escape(worst_t)}</b> (median language).",
        ))
    base = _baselines(head)
    if base:
        ref_t, ref_n = _reference(head)
        hi_t, hi_n = max(base, key=lambda x: x[1])
        if hi_n >= 1.2 * ref_n:
            out.append((
                f"{hi_n / ref_n:.2f}×",
                f"<b>{html.escape(hi_t)}</b> needs {hi_n / ref_n:.2f}× as many tokens as <b>{html.escape(ref_t)}</b> "
                "for the same <i>English</i> text, so its lower ratios do not mean lower absolute cost.",
            ))
    return out


def _baselines(results):
    """(tokenizer, English token count), cheapest first; the absolute scale behind every ratio."""
    return sorted(((r["tokenizer"], r["langs"][BASE]["tokens"]) for r in results if BASE in r["langs"]),
                  key=lambda x: x[1])


def _reference(head):
    """The first headline tokenizer in display order (GPT-4o's o200k_base when present) as the absolute yardstick."""
    r = next(r for r in head if BASE in r["langs"])
    return r["tokenizer"], r["langs"][BASE]["tokens"]


def _absolute(results, names):
    head = headline(results)
    base = _baselines(head)
    if not base:
        return ""
    ref_t, ref_n = _reference(head)
    picks = [lg for lg in ("slk_Latn", "deu_Latn", "hin_Deva", "jpn_Jpan") if all(lg in r["langs"] for r in head)]
    by = {r["tokenizer"]: r for r in head}
    hdr = ("<tr><th>Tokenizer</th><th>English tokens</th><th>vs " + html.escape(ref_t) + "</th>" +
           "".join(f"<th>{html.escape(names.get(lg, lg))}<small>tokens · ratio</small></th>" for lg in picks) + "</tr>")
    trs = []
    for t, n in base:
        cells = "".join(
            f"<td data-v={by[t]['langs'][lg]['tokens']}>{by[t]['langs'][lg]['tokens']:,} · "
            f"{by[t]['langs'][lg]['ratio_vs_en']:.2f}×</td>" for lg in picks)
        trs.append(f"<tr><td>{html.escape(t)}</td><td data-v={n}>{n:,}</td><td data-v={n / ref_n:.3f}>{n / ref_n:.2f}×</td>{cells}</tr>")
    return (
        "<h2>Ratios vs absolute tokens</h2>"
        "<p class=note>Each ratio compares a language with English <i>on the same tokenizer</i>. Tokenizers differ in how many "
        "tokens they spend on English itself, so a lower ratio does not always mean fewer tokens. Token counts below are for "
        "the whole FLORES-200 devtest set; prices per token also differ by model (see data.json).</p>"
        f"<div class='card wrap'><table>{hdr}<tbody>{''.join(trs)}</tbody></table></div>"
    )


CSS = """
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#6b6560;--line:#e7e5e4;--card:#fff;--accent:#b45309;--bar:#f5b041;--en:#78716c;
--lt:#dcfce7;--eq:#f5f5f4;--r1:#fef9c3;--r2:#fde68a;--r3:#fdba74;--r4:#fb923c;--r5:#f87171}
@media (prefers-color-scheme:dark){:root{--bg:#0b1020;--fg:#e8ecf4;--muted:#9aa5c0;--line:#1f2a4a;--card:#111a33;--accent:#f5b041;
--bar:#f5b041;--en:#9aa5c0;--lt:#14532d;--eq:#1a2340;--r1:#3b3413;--r2:#5c3d0e;--r3:#7c2d12;--r4:#9a3412;--r5:#991b1b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:32px 16px 64px}a{color:var(--accent)}
h1{font-size:clamp(2rem,5vw,3rem);margin:0 0 8px;letter-spacing:-.02em}h2{font-size:1.35rem;margin:40px 0 8px}
.lead{font-size:1.15rem;color:var(--muted);margin:0 0 24px;max-width:780px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:24px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.kpi strong{display:block;font-size:1.7rem;color:var(--accent);font-variant-numeric:tabular-nums}
.kpi span{color:var(--muted);font-size:.95rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0}
select,input{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);max-width:100%}
.bars{margin-top:12px}.b{display:grid;grid-template-columns:minmax(120px,260px) 1fr 64px;gap:10px;align-items:center;margin:4px 0;font-size:.9rem}
.b .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.b .v{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.b .track{height:14px;background:var(--eq);border-radius:7px;position:relative;overflow:hidden}
.b .fill{display:block;height:100%;background:var(--bar);border-radius:7px}.b .en{position:absolute;top:0;bottom:0;width:2px;background:var(--en)}
.note{color:var(--muted);font-size:.85rem}
.wrap{overflow:auto;max-height:80vh}table{border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:.85rem}
th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{position:sticky;top:0;background:var(--card);cursor:pointer;font-weight:600;z-index:1;vertical-align:bottom}
th small{display:block;color:var(--muted);font-weight:400}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card)}th:first-child{z-index:2}
td.lt{background:var(--lt)}td.eq{background:var(--eq)}td.r1{background:var(--r1)}td.r2{background:var(--r2)}
td.r3{background:var(--r3)}td.r4{background:var(--r4)}td.r5{background:var(--r5)}
.code{color:var(--muted);font-size:.75rem}
.legend{display:flex;flex-wrap:wrap;gap:6px;font-size:.8rem;color:var(--fg);margin:8px 0}
.legend span{padding:2px 8px;border-radius:4px}
details{margin:8px 0}summary{cursor:pointer;font-weight:600}
footer{color:var(--muted);font-size:.9rem;margin-top:48px;border-top:1px solid var(--line);padding-top:16px}
@media (max-width:600px){.b{grid-template-columns:110px 1fr 52px}}
"""

JS = """
const D=JSON.parse(document.getElementById('d').textContent);
const sel=document.getElementById('lang'),bars=document.getElementById('bars'),sum=document.getElementById('sum');
const bl=(navigator.language||'').slice(0,2).toLowerCase();
sel.value=(D.browser[bl]&&D.ratios[D.browser[bl]])?D.browser[bl]:(D.ratios.deu_Latn?'deu_Latn':sel.options[0].value);
function draw(){const lg=sel.value,r=D.ratios[lg]||{};const items=D.toks.filter(t=>r[t]!=null).map(t=>[t,r[t]]).sort((a,b)=>a[1]-b[1]);
const max=Math.max(2,...items.map(x=>x[1]));bars.innerHTML='';
for(const [t,v] of items){const d=document.createElement('div');d.className='b';
d.innerHTML=`<span class=t title="${t}">${t}</span><span class=track><span class=fill style="width:${v/max*100}%"></span><span class=en style="left:${100/max}%"></span></span><span class=v>${v.toFixed(2)}×</span>`;bars.appendChild(d)}
const m=D.median[lg];sum.innerHTML=m==null?'':`On major models, <b>${D.names[lg]||lg}</b> needs a median of <b>${m.toFixed(2)}×</b> the tokens of the same English text: `+(m>=1?`you pay about <b>${Math.round((m-1)*100)} % more</b> and fit ${Math.round((1-1/m)*100)} % less text into the context window.`:`it is cheaper than English.`)}
sel.addEventListener('change',draw);draw();
const t=document.getElementById('lb');
document.getElementById('q').addEventListener('input',e=>{const q=e.target.value.toLowerCase();
for(const r of t.tBodies[0].rows)r.style.display=r.cells[0].textContent.toLowerCase().includes(q)?'':'none'});
t.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{const b=t.tBodies[0],rs=[...b.rows];
const dir=th.dataset.d=th.dataset.d==='1'?'-1':'1';rs.sort((a,c)=>{const x=a.cells[i].dataset.v??a.cells[i].textContent,
y=c.cells[i].dataset.v??c.cells[i].textContent;const nx=parseFloat(x),ny=parseFloat(y);
return (isNaN(nx)||isNaN(ny)?x.localeCompare(y):nx-ny)*dir});rs.forEach(r=>b.appendChild(r))}));
"""


def _shade(ratio):
    # below 0.95 -> cheaper than English; ~1.0 -> neutral; >= 2.6 -> strongest
    if ratio < 0.95:
        return "lt"
    return f"r{min(5, int((ratio - 1) / 0.4) + 1)}" if ratio > 1.05 else "eq"


def _head(has_og):
    e = html.escape
    title = "Token Tax Index: how much more every language costs in LLM tokens"
    desc = ("How many more tokens, and how much more money, the same text needs in 200 languages than in English, "
            "measured on the tokenizers of GPT, Claude, Gemini, Llama, Gemma, Mistral, Qwen and DeepSeek.")
    og = (f"<meta property=og:image content='{SITE}og.png'><meta property=og:image:width content=1280>"
          "<meta property=og:image:height content=640><meta name=twitter:card content=summary_large_image>"
          if has_og else "<meta name=twitter:card content=summary>")
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{e(title)}</title><meta name=description content='{e(desc)}'>"
        f"<meta name=author content='{AUTHOR}'><link rel=canonical href='{SITE}'>"
        f"<meta property=og:title content='{e(title)}'><meta property=og:description content='{e(desc)}'>"
        f"<meta property=og:type content=website><meta property=og:url content='{SITE}'>{og}"
        f"<style>{CSS}</style>"
    )


def _jsonld(results, n_langs):
    meta = results[0] if results else {}
    data = {
        "@context": "https://schema.org", "@type": "Dataset",
        "@id": f"{SITE}#dataset",
        "name": "Token Tax Index",
        "description": "Token count of the same text in each language relative to English, per LLM tokenizer, on FLORES-200.",
        "url": SITE, "sameAs": REPO, "license": "https://opensource.org/licenses/MIT",
        "creator": {"@type": "Person", "@id": f"{AUTHOR_URL}#person", "name": AUTHOR, "url": AUTHOR_URL},
        "keywords": ["LLM", "tokenizer", "token tax", "multilingual", "API pricing", "FLORES-200"],
        "identifier": f"https://doi.org/{CONCEPT_DOI}",
        "isBasedOn": "https://github.com/facebookresearch/flores",
        # Google's Dataset docs: articles to cite in addition to the dataset itself
        "citation": "NLLB Team et al. No Language Left Behind: Scaling Human-Centered Machine Translation. arXiv:2207.04672, 2022.",
        "datePublished": FIRST_PUBLISHED,
        "dateModified": meta.get("measured_at", ""),
        "version": meta.get("measured_at", ""),
        "variableMeasured": "tokens relative to English",
        "measurementTechnique": f"{len(results)} tokenizers × {n_langs} languages, parallel sentences",
        "distribution": {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": f"{SITE}data.json"},
    }
    return "<script type=application/ld+json>" + json.dumps(data, ensure_ascii=False) + "</script>"


def _foot():
    return (
        f"<footer>Created by <a href='{AUTHOR_URL}'>{AUTHOR}</a> · <a href='{REPO}'>source code &amp; data</a> (MIT) · "
        "FLORES-200 © Meta, CC BY-SA 4.0 · also: "
        "<a href='https://github.com/ltchurik/sk-tokenizer-bench'>sk-tokenizer-bench</a>, "
        "<a href='https://github.com/ltchurik/llm-locale-lint'>llm-locale-lint</a>, "
        "<a href='https://github.com/ltchurik/localebench'>localebench</a></footer>"
    )


INTRO = (
    "<h1>Token Tax Index</h1>"
    "<p class=lead>LLM APIs bill per token, and tokenizers are trained mostly on English. The same sentence in another "
    "language is split into more tokens, so it costs more and fills the context window faster. "
    "This index measures that <b>token tax</b> for every language and every major tokenizer.</p>"
)


def render(results, names=None, has_og=False):
    names = names if names is not None else read_data("language_names.json")["names"]
    e = html.escape
    if not results:
        body = (
            "<div class=card><strong>No data yet.</strong> The index is in early development; "
            "the first results will appear here after the first benchmark run. "
            f"Follow or contribute on <a href='{REPO}'>GitHub</a>.</div>"
        )
        return _head(has_og) + "</head><body><main>" + INTRO + body + _foot() + "</main></body></html>\n"

    toks = ordered(results)
    head_set = {r["tokenizer"] for r in headline(results)}
    rows = leaderboard(results)
    meta = toks[0]

    kpis = "".join(f"<div class=kpi><strong>{k}</strong><span>{v}</span></div>" for k, v in findings(results, rows, names))

    langs_sorted = sorted((lg for lg, _, _ in rows), key=lambda lg: names.get(lg, lg))
    opts = "".join(f"<option value={lg}>{e(names.get(lg, lg))}</option>" for lg in langs_sorted)
    picker = (
        "<h2>Your language</h2><div class=card>"
        f"<label>Language <select id=lang aria-label='Language'>{opts}</select></label>"
        "<p id=sum></p><div id=bars class=bars></div>"
        "<p class=note>Bars show tokens relative to the same English text (1.00× = English, marked by the grey line). "
        "Lower is cheaper.</p></div>"
    )

    def col(r):
        star = " ★" if r["tokenizer"] in head_set else ""
        return f"<th>{e(r['tokenizer'])}{star}<small>{e(r.get('group', ''))}</small></th>"

    hdr = "<tr><th>Language</th><th>Median ★<small>major models</small></th>" + "".join(col(r) for r in toks) + "</tr>"
    trs = []
    for lg, med, cells in rows:
        name = names.get(lg, lg)
        tds = "".join(
            f"<td class={_shade(cells[r['tokenizer']])} data-v={cells[r['tokenizer']]}>{cells[r['tokenizer']]:.2f}</td>"
            if r["tokenizer"] in cells else "<td data-v=-1>–</td>"
            for r in toks
        )
        trs.append(f"<tr><td data-v='{e(name)}'>{e(name)} <span class=code>{e(lg)}</span></td>"
                   f"<td class={_shade(med)} data-v={med}><b>{med:.2f}</b></td>{tds}</tr>")
    legend = ("<div class=legend><span style='background:var(--lt)'>cheaper than English</span>"
              "<span style='background:var(--eq)'>≈ English</span><span style='background:var(--r1)'>+5–40 %</span>"
              "<span style='background:var(--r2)'>+40–80 %</span><span style='background:var(--r3)'>+80–120 %</span>"
              "<span style='background:var(--r4)'>+120–160 %</span><span style='background:var(--r5)'>2.6× and more</span></div>")
    table = (
        f"<h2>All {len(rows)} languages × {len(toks)} tokenizers</h2>"
        "<p class=note>★ = included in the headline median (current tokenizers of major vendors; models that share a "
        "vocabulary are counted once). Click a column to sort.</p>"
        "<input id=q placeholder='Filter languages…' aria-label='Filter languages'>" + legend +
        f"<div class='card wrap'><table id=lb><thead>{hdr}</thead><tbody>{''.join(trs)}</tbody></table></div>"
    )
    method = (
        "<h2>Method</h2>"
        f"<p>Every tokenizer encodes the same {meta.get('n_sentences', '?')} professionally translated sentences of "
        f"<a href='https://github.com/facebookresearch/flores'>FLORES-200</a> ({e(str(meta.get('corpus', '')))}) in each language. "
        "The <b>token tax</b> of a language is its total token count divided by the token count of the English text. "
        "Confidence intervals (bootstrap over sentences) and API prices per model are in "
        f"<a href='data.json'>data.json</a> and the <a href='{REPO}'>repository</a>, where anyone can rerun the benchmark.</p>"
        "<details><summary>Why does this matter?</summary><p>You pay the token tax on input and output, it shrinks the usable "
        "context window, and it slows generation. A model that is cheap in English can be the expensive choice for your language.</p></details>"
        "<details><summary>Why are some languages cheaper than English?</summary><p>Tokenizers trained for a specific language "
        "(e.g. SlovakBERT for Slovak or CSMPT for Czech) encode that language more efficiently than English.</p></details>"
        f"<details><summary>A tokenizer or model is missing</summary><p>Open an issue or a pull request on <a href='{REPO}'>GitHub</a>; "
        "the tokenizer list is a single JSON file.</p></details>"
        f"<p class=note>Measured {e(str(meta.get('measured_at', '')))} with token-tax-index v{e(str(meta.get('tti_version', __version__)))}.</p>"
    )
    data = {
        "toks": [r["tokenizer"] for r in toks if r.get("group") != "Reference"],
        "ratios": {lg: {t: round(v, 3) for t, v in cells.items()} for lg, _, cells in rows},
        "median": {lg: med for lg, med, _ in rows},
        "names": {lg: names.get(lg, lg) for lg, _, _ in rows},
        "browser": BROWSER_LANG,
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return (
        _head(has_og) + _jsonld(results, len(rows)) + "</head><body><main>" + INTRO +
        f"<div class=kpis>{kpis}</div>" + picker + table + _absolute(results, names) + method + _foot() +
        f"</main><script type=application/json id=d>{blob}</script><script>{JS}</script></body></html>\n"
    )


def build(results_dir, out_dir, og_image=None):
    results = load_results(results_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    og = Path(og_image) if og_image else Path.cwd() / ".github" / "social-preview.png"
    has_og = og.is_file()
    if has_og:
        shutil.copyfile(og, out / "og.png")
    (out / "index.html").write_text(render(results, has_og=has_og), encoding="utf-8")
    (out / "data.json").write_text(json.dumps(results, ensure_ascii=False) + "\n", encoding="utf-8")
    return out / "index.html", len(results)
