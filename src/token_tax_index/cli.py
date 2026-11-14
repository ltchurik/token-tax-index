"""tti — Token Tax Index command line.

    tti fetch-corpus --langs slk_Latn,deu_Latn      # or --langs all (default: all 204)
    tti list                                        # registered tokenizers
    tti run --tokenizers o200k,gemma --langs slk_Latn,deu_Latn
    tti site                                        # results/*.json -> site/index.html
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from . import __version__, backends, corpus, measure, registry, site


def _csv(s):
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def cmd_fetch(args):
    tarball = Path(args.tarball) if args.tarball else Path(args.out).parent / "flores200_dataset.tar.gz"
    if not tarball.exists():
        print(f"downloading {args.url} -> {tarball}", file=sys.stderr)
        corpus.download(args.url, tarball)
    rows, langs = corpus.parse_flores_tarball(tarball, _csv(args.langs), split=args.split)
    corpus.write_jsonl(rows, args.out)
    print(f"wrote {args.out}: {len(rows)} sentences x {len(langs)} languages", file=sys.stderr)


def cmd_list(args):
    for s in registry.load_tokenizers(args.registry):
        print(f"{s.group:10} {s.kind:11} {s.name}")


def cmd_run(args):
    rows, langs = corpus.load_corpus(args.corpus, _csv(args.langs))
    specs = registry.select(registry.load_tokenizers(args.registry), args.tokenizers, args.no_api)
    if not specs:
        sys.exit("no tokenizers match --tokenizers")
    prices = registry.load_prices(args.prices)
    api_cache = backends.ApiCache.load(args.api_cache)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ok = 0
    for s in specs:
        try:
            counter = backends.load(s.kind, s.id, api_cache=api_cache)
            stats = measure.measure(counter, rows, langs, args.bootstrap)
        except Exception as e:  # gated / offline / missing extra / no key
            print(f"SKIP {s.name}: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
            continue
        result = {
            "schema": 1,
            "tokenizer": s.name,
            "kind": s.kind,
            "id": s.id,
            "group": s.group,
            "corpus": Path(args.corpus).stem,
            "n_sentences": len(rows),
            "measured_at": dt.date.today().isoformat(),
            "tti_version": __version__,
            "langs": stats,
            "costs": measure.cost_table(s.name, stats, prices),
        }
        path = out / f"{slug(s.name)}.json"
        path.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        worst = max((lg for lg in stats if lg != corpus.BASE), key=lambda lg: stats[lg]["ratio_vs_en"], default=None)
        extra = f", highest {worst}={stats[worst]['ratio_vs_en']}" if worst else ""
        print(f"OK   {s.name} -> {path}{extra}", file=sys.stderr)
        ok += 1
    if ok == 0:
        sys.exit("all tokenizers skipped")


def cmd_site(args):
    path, n = site.build(args.results, args.out)
    print(f"wrote {path} ({n} tokenizers)", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tti", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"tti {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch-corpus", help="download FLORES-200 and write a JSONL parallel corpus")
    f.add_argument("--langs", default="all", help="comma-separated FLORES-200 codes, or 'all' (eng_Latn is always added)")
    f.add_argument("--split", default="devtest", choices=["dev", "devtest"])
    f.add_argument("--url", default=corpus.FLORES_URL)
    f.add_argument("--tarball", help="use an already downloaded FLORES-200 tarball")
    f.add_argument("--out", default=str(corpus.DEFAULT_CORPUS))
    f.set_defaults(func=cmd_fetch)

    li = sub.add_parser("list", help="list registered tokenizers")
    li.add_argument("--registry", help="custom tokenizers.json")
    li.set_defaults(func=cmd_list)

    r = sub.add_parser("run", help="measure tokenizers on the corpus and write results/*.json")
    r.add_argument("--corpus", default=str(corpus.DEFAULT_CORPUS))
    r.add_argument("--tokenizers", help="comma-separated substrings of tokenizer names (default: all)")
    r.add_argument("--langs", help="comma-separated FLORES-200 codes (default: all in corpus)")
    r.add_argument("--no-api", action="store_true", help="skip Claude / Gemini API tokenizers")
    r.add_argument("--bootstrap", type=int, default=2000, help="bootstrap resamples for the 95%% CI (0 = off)")
    r.add_argument("--registry", help="custom tokenizers.json")
    r.add_argument("--prices", help="custom prices.json")
    r.add_argument("--api-cache", default=str(backends.DEFAULT_CACHE))
    r.add_argument("--out", default="results")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("site", help="render the static leaderboard from results/*.json")
    s.add_argument("--results", default="results")
    s.add_argument("--out", default="site")
    s.set_defaults(func=cmd_site)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
