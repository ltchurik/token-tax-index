import io
import json
import tarfile
from pathlib import Path

import pytest

from token_tax_index import backends, cli, corpus, measure, registry, site

DATA = Path(__file__).parent / "data"
SAMPLE = DATA / "sample.jsonl"


def ws(texts):
    return [len(t.split()) for t in texts]


# --- corpus -----------------------------------------------------------------------------

def test_load_corpus_baseline_last():
    rows, langs = corpus.load_corpus(SAMPLE)
    assert len(rows) == 5
    assert langs[-1] == "eng_Latn"
    assert set(langs) == {"eng_Latn", "slk_Latn", "deu_Latn"}


def test_load_corpus_filters_and_rejects_unknown():
    _, langs = corpus.load_corpus(SAMPLE, ["slk_Latn"])
    assert langs == ["slk_Latn", "eng_Latn"]
    with pytest.raises(ValueError, match="xxx_Latn"):
        corpus.load_corpus(SAMPLE, ["xxx_Latn"])


def _fake_flores(path, langs):
    with tarfile.open(path, "w:gz") as tar:
        def add(name, text):
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        add("./flores200_dataset/metadata_devtest.tsv", "URL\tdomain\ttopic\nu1\twikinews\tt\nu2\twikivoyage\tt\n")
        for code, lines in langs.items():
            add(f"./flores200_dataset/devtest/{code}.devtest", "\n".join(lines) + "\n")
            add(f"./flores200_dataset/dev/{code}.dev", "ignored\n")


def test_parse_flores_tarball(tmp_path):
    tb = tmp_path / "f.tar.gz"
    _fake_flores(tb, {"eng_Latn": ["Hello world.", "Bye."], "slk_Latn": ["Ahoj svet.", "Zbohom."], "fra_Latn": ["a", "b"]})
    rows, langs = corpus.parse_flores_tarball(tb, ["slk_Latn"])
    assert langs == ["slk_Latn", "eng_Latn"]
    assert rows[0] == {"id": 0, "domain": "wikinews", "slk_Latn": "Ahoj svet.", "eng_Latn": "Hello world."}
    rows, langs = corpus.parse_flores_tarball(tb, ["all"])
    assert sorted(langs) == ["eng_Latn", "fra_Latn", "slk_Latn"]
    with pytest.raises(ValueError, match="unknown"):
        corpus.parse_flores_tarball(tb, ["deu_Latn"])


# --- measure ----------------------------------------------------------------------------

def test_measure_whitespace_exact():
    rows, langs = corpus.load_corpus(SAMPLE)
    stats = measure.measure(ws, rows, langs, n_boot=0)
    en = sum(len(r["eng_Latn"].split()) for r in rows)
    sk = sum(len(r["slk_Latn"].split()) for r in rows)
    assert stats["eng_Latn"]["ratio_vs_en"] == 1.0
    assert "ci95" not in stats["eng_Latn"]
    assert stats["slk_Latn"]["tokens"] == sk
    assert stats["slk_Latn"]["ratio_vs_en"] == round(sk / en, 3)
    assert stats["slk_Latn"]["ci95"] == [round(sk / en, 3)] * 2


def test_bootstrap_ci_brackets_point_estimate():
    num, den = [3, 5, 4, 6, 2, 7, 5], [2, 3, 3, 4, 2, 4, 3]
    lo, hi = measure.ratio_ci(num, den, n_boot=500)
    point = sum(num) / sum(den)
    assert lo <= point <= hi
    assert measure.ratio_ci(num, den, n_boot=500) == (lo, hi)  # seeded, reproducible


def test_cost_table():
    prices = registry.load_prices(DATA / "prices.json")
    stats = {"eng_Latn": {"ratio_vs_en": 1.0, "chars_per_token": 5.0}, "slk_Latn": {"ratio_vs_en": 1.5, "chars_per_token": 4.0}}
    (row,) = measure.cost_table("Whitespace (test)", stats, prices)
    assert row["model"] == "ws-model"
    assert row["langs"]["slk_Latn"]["usd_same_content_per_m_en_tokens"] == 3.0
    assert row["langs"]["slk_Latn"]["usd_per_m_chars"] == 0.5
    assert measure.cost_table("unpriced", stats, prices) == []


# --- backends & registry ----------------------------------------------------------------

def test_builtin_backends():
    assert backends.load("whitespace", "")(["a b c", "d"]) == [3, 1]
    assert backends.load("utf8-bytes", "")(["ľ", "a"]) == [2, 1]
    with pytest.raises(ValueError):
        backends.load("nope", "")


def test_api_backend_skips_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    counter = backends.load("anthropic", "some-model", api_cache=backends.ApiCache.load(tmp_path / "c.json"))
    with pytest.raises(backends.Skip):
        counter(["hello"])


def test_api_backend_uses_cache_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    cache = backends.ApiCache.load(tmp_path / "c.json")
    cache.put("m", "hello", 7)
    assert backends.load("gemini", "m", api_cache=cache)(["hello"]) == [7]


def test_bundled_registry_and_prices_consistent():
    specs = registry.load_tokenizers()
    names = [s.name for s in specs]
    assert len(names) == len(set(names))
    known = {"tiktoken", "hf", "hf-bpe", "tiktoken-hf", "spm", "anthropic", "gemini", "utf8-bytes", "whitespace"}
    assert {s.kind for s in specs} <= known
    for m in registry.load_prices()["models"]:
        assert m["tokenizer"] in names, m


def test_select():
    specs = registry.load_tokenizers()
    assert all("gpt" in s.name.lower() for s in registry.select(specs, "gpt"))
    assert not any(s.kind in registry.API_KINDS for s in registry.select(specs, None, no_api=True))


# --- site & cli -------------------------------------------------------------------------

def test_site_empty_says_no_data(tmp_path):
    index, n = site.build(tmp_path / "missing", tmp_path / "site")
    assert n == 0
    assert "No data yet" in index.read_text(encoding="utf-8")


def test_cli_end_to_end(tmp_path):
    out = tmp_path / "results"
    cli.main(["run", "--corpus", str(SAMPLE), "--registry", str(DATA / "registry.json"),
              "--prices", str(DATA / "prices.json"), "--bootstrap", "100", "--out", str(out),
              "--api-cache", str(tmp_path / "cache.json")])
    files = sorted(p.name for p in out.glob("*.json"))
    assert files == ["utf-8-bytes-reference.json", "whitespace-test.json"]
    r = json.loads((out / "whitespace-test.json").read_text(encoding="utf-8"))
    assert r["n_sentences"] == 5 and r["corpus"] == "sample"
    assert r["costs"][0]["model"] == "ws-model"
    # UTF-8 bytes: Slovak diacritics take 2 bytes, so bytes-per-char > 1
    b = json.loads((out / "utf-8-bytes-reference.json").read_text(encoding="utf-8"))
    assert b["langs"]["slk_Latn"]["chars_per_token"] < 1

    cli.main(["site", "--results", str(out), "--out", str(tmp_path / "site")])
    html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "Slovak" in html and "slk_Latn" in html and "Whitespace (test)" in html
    assert "No data yet" not in html
    data = json.loads((tmp_path / "site" / "data.json").read_text(encoding="utf-8"))
    assert len(data) == 2


def test_cli_run_fails_when_nothing_matches(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["run", "--corpus", str(SAMPLE), "--registry", str(DATA / "registry.json"),
                  "--tokenizers", "does-not-exist", "--out", str(tmp_path)])
