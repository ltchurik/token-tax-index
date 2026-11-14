"""Token counts, ratios vs English with bootstrap CIs, and API cost per language."""
import numpy as np

from .corpus import BASE


def ratio_ci(num, den, n_boot=2000, seed=0):
    """95 % percentile bootstrap CI of sum(num)/sum(den), resampling sentences."""
    num, den = np.asarray(num, dtype=np.int64), np.asarray(den, dtype=np.int64)
    if n_boot <= 0 or len(num) < 2:
        r = round(float(num.sum() / den.sum()), 3)
        return r, r
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(num), size=(n_boot, len(num)))
    ratios = num[idx].sum(axis=1) / den[idx].sum(axis=1)
    lo, hi = np.percentile(ratios, [2.5, 97.5])
    return round(float(lo), 3), round(float(hi), 3)


def measure(counter, rows, langs, n_boot=2000):
    """Run one tokenizer over a corpus. Returns {lang: stats}; the baseline has ratio 1."""
    counts = {lg: counter([r[lg] for r in rows]) for lg in langs}
    base_tokens = sum(counts[BASE])
    out = {}
    for lg in langs:
        tokens = sum(counts[lg])
        chars = sum(len(r[lg]) for r in rows)
        stats = {
            "tokens": tokens,
            "chars": chars,
            "chars_per_token": round(chars / tokens, 3) if tokens else None,
            "ratio_vs_en": round(tokens / base_tokens, 3),
        }
        if lg != BASE:
            stats["ci95"] = list(ratio_ci(counts[lg], counts[BASE], n_boot))
        out[lg] = stats
    return out


def prices_for(tokenizer_name, prices):
    return [m for m in prices.get("models", []) if m.get("tokenizer") == tokenizer_name]


def cost_table(tokenizer_name, lang_stats, prices):
    """Input cost of the same content per model, in USD per 1M English-equivalent tokens.

    If English content costs `p` per 1M tokens, the same content in language L costs
    p * ratio_vs_en(L). Also reported: USD per 1M characters of text in L (p / chars_per_token).
    """
    rows = []
    for m in prices_for(tokenizer_name, prices):
        p = m["input"]
        rows.append({
            "vendor": m.get("vendor"),
            "model": m["model"],
            "input_usd_per_mtok": p,
            "langs": {
                lg: {
                    "usd_same_content_per_m_en_tokens": round(p * s["ratio_vs_en"], 4),
                    "usd_per_m_chars": round(p / s["chars_per_token"], 4) if s["chars_per_token"] else None,
                }
                for lg, s in lang_stats.items()
            },
        })
    return rows
