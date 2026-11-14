# Token Tax Index

**How much more does each language cost in LLM tokens?** An open, regularly refreshed index of the "token tax": how many more tokens the same content needs in 200 languages than in English, across the tokenizers of current LLMs, translated into what it means for your API bill and context window.

[![ci](https://github.com/ltchurik/token-tax-index/actions/workflows/ci.yml/badge.svg)](https://github.com/ltchurik/token-tax-index/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

> **Status: 🚧 Early development — no published results yet.** The measurement pipeline and the leaderboard generator work (see [Quickstart](#quickstart)); the first full run over all languages and tokenizers has not been published. Numbers will appear on the leaderboard site, not in this README, once they are reproducible end to end.

## Why it matters

Every LLM API bills per token, and context windows are measured in tokens. Tokenizers are trained mostly on English, so the same sentence in Slovak, Amharic, Burmese or Tamil is split into more pieces. Speakers of those languages pay more for the same answer, get less text into the same context window and wait longer for the same output.

This is well known from research snapshots, but the numbers go stale every time a vendor ships a new tokenizer. The goal of this project is a **living** index: re-measured when models change, with prices attached, so developers, product teams and researchers can look up the current cost of their language instead of citing a 2023 table.

## Method (planned for v1)

- **Corpus:** [FLORES-200](https://github.com/facebookresearch/flores) `devtest`, 1012 professionally translated sentences, aligned across 204 language variants. The same meaning in every language makes token counts directly comparable. The corpus is downloaded by `tti fetch-corpus` and not redistributed here (CC BY-SA 4.0).
- **Tokenizers:** 38 open and closed tokenizers out of the box (OpenAI tiktoken, Llama, Mistral, Gemma, Qwen, DeepSeek, GLM, Kimi, Phi, EuroLLM and more), plus Claude and Gemini via the vendors' token-counting APIs. The registry is a plain JSON file: [`tokenizers.json`](src/token_tax_index/data/tokenizers.json).
- **Metric:** `ratio_vs_en` = total tokens in language L ÷ total tokens in English on the same sentences, with a 95 % bootstrap confidence interval (resampling sentences). Also reported: characters per token.
- **Counting rules:** no special tokens (BOS/EOS), no chat template. API tokenizers subtract the fixed per-request overhead, measured once per model.
- **Cost:** with list input prices from [`prices.json`](src/token_tax_index/data/prices.json): the cost of the same content in L = English price × ratio, and USD per 1M characters.
- **Reference row:** UTF-8 bytes, to separate "the tokenizer is bad at this language" from "this script simply needs more bytes".

## Quickstart

```bash
pip install "token-tax-index[local] @ git+https://github.com/ltchurik/token-tax-index"

tti fetch-corpus --langs slk_Latn,deu_Latn,amh_Ethi   # or --langs all (eng_Latn is always added)
tti list                                              # registered tokenizers
tti run --tokenizers o200k,gemma,qwen --no-api        # writes results/*.json
tti site                                              # renders site/index.html from results/
```

Claude and Gemini rows need `pip install "token-tax-index[api]"` and `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`. API counts are cached in `cache/api_counts.json`, so a committed cache reproduces them without a key.

## Prior art

This project builds on, and tries to complement, earlier work:

- **Petrov et al., 2023**, *Language Model Tokenizers Introduce Unfairness Between Languages* (NeurIPS), with an [interactive page](https://aleksandarpetrov.github.io/tokenization-fairness/). The foundational study on FLORES-200, a snapshot of 2023 tokenizers without prices.
- **[tokentax](https://pypi.org/project/tokentax/)**, a Python package measuring 8 tokenizers on FLORES languages. No site or cost figures, and inactive since its first release.
- **[Arabic Token-Tax Index](https://github.com/Bayanat-Labs/arabic-token-tax-index)** by Bayanat Labs. A careful single-language index (Arabic vs English, 12 tokenizers, with prices).
- **[sk-tokenizer-bench](https://github.com/ltchurik/sk-tokenizer-bench)**, the same author's Slovak benchmark (30+ tokenizers, Slovak vs English, Czech, Polish, Hungarian, German). This project generalizes its code and method to all languages.

What's new here: all FLORES-200 languages × current tokenizers × prices in one place, kept up to date.

## Roadmap

- [x] Measurement pipeline: FLORES-200 download, tokenizer registry, bootstrap CIs, cost table
- [x] Static leaderboard generator (`tti site`) and GitHub Pages deployment
- [ ] First full run: 204 languages × all open tokenizers, results committed to `results/`
- [ ] Claude and Gemini rows via the token-count APIs (cached)
- [ ] Per-language pages: "what does my language cost on each model?"
- [ ] Scheduled refresh when new tokenizers or prices appear
- [ ] Language names for all 204 FLORES codes (134 so far, [PRs welcome](src/token_tax_index/data/language_names.json))
- [ ] Output-side cost (generation), not only input
- [ ] Embeddable badge: "My language pays 1.6× on model X"

Contributions are welcome, especially new tokenizers in `tokenizers.json`, price updates with a source link, and language names.

## Citing

A `CITATION.cff` with a DOI will be added with the first published results. Until then, please cite the repository URL.

## License

Code: MIT. FLORES-200 is © Meta Platforms, Inc., CC BY-SA 4.0. It is downloaded at run time and not included in this repository.

Made by [Ľubomír Tchurik](https://lubomirtchurik.sk).
