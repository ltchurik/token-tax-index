"""Load a tokenizer and turn it into `count_all(texts) -> list[int]`.

Adapted from sk-tokenizer-bench (MIT, same author).

Local tokenizers count with add_special_tokens=False (no BOS/EOS, no chat template).
API tokenizers (Claude, Gemini) are counted through the vendors' token-count endpoints.
Each API call wraps the text in a one-message request, which adds a fixed overhead; it is
measured once per model as count(".") - 1 and subtracted. Counts are cached in
cache/api_counts.json (keyed by model and sha1 of the text) so API rows reproduce without a
key once the cache is committed.
"""
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_CACHE = Path("cache") / "api_counts.json"
_OVERHEAD_KEY = "__overhead__"

# Pre-tokenization patterns for tiktoken-format vocabularies on the HF Hub,
# copied verbatim from the model repo's tokenization_*.py.
TIKTOKEN_PATTERNS = {
    "kimi": "|".join(
        [
            r"""[\p{Han}]+""",
            r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]*[\p{Ll}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
            r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]+[\p{Ll}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
            r"""\p{N}{1,3}""",
            r""" ?[^\s\p{L}\p{N}]+[\r\n]*""",
            r"""\s*[\r\n]+""",
            r"""\s+(?!\S)""",
            r"""\s+""",
        ]
    ),
}


class Skip(Exception):
    """Tokenizer unavailable (gated, offline, missing optional dependency, no API key)."""


def _need(module, extra):
    raise Skip(f"missing {module}: pip install 'token-tax-index[{extra}]'")


def load(kind, ident, *, api_cache=None, api_workers=8):
    if kind == "utf8-bytes":
        return _local(lambda s: len(s.encode("utf-8")))

    if kind == "whitespace":
        return _local(lambda s: len(s.split()))

    if kind == "tiktoken":
        try:
            import tiktoken
        except ImportError:
            _need("tiktoken", "local")
        enc = tiktoken.get_encoding(ident)
        return _local(lambda s: len(enc.encode_ordinary(s)))

    if kind == "hf":
        try:
            from tokenizers import Tokenizer
        except ImportError:
            _need("tokenizers", "local")
        tok = Tokenizer.from_pretrained(ident)
        return _local(lambda s: len(tok.encode(s, add_special_tokens=False).ids))

    if kind == "hf-bpe":
        try:
            from huggingface_hub import hf_hub_download
            from tokenizers import ByteLevelBPETokenizer
        except ImportError:
            _need("tokenizers / huggingface_hub", "local")
        tok = ByteLevelBPETokenizer(hf_hub_download(ident, "vocab.json"), hf_hub_download(ident, "merges.txt"))
        return _local(lambda s: len(tok.encode(s).ids))

    if kind == "tiktoken-hf":
        try:
            import tiktoken
            from huggingface_hub import hf_hub_download
            from tiktoken.load import load_tiktoken_bpe
        except ImportError:
            _need("tiktoken / huggingface_hub", "local")
        repo, pattern = ident.split("::")
        ranks = load_tiktoken_bpe(hf_hub_download(repo, "tiktoken.model"))
        enc = tiktoken.Encoding(name=repo, pat_str=TIKTOKEN_PATTERNS[pattern], mergeable_ranks=ranks, special_tokens={})
        return _local(lambda s: len(enc.encode_ordinary(s)))

    if kind == "spm":
        try:
            import sentencepiece as spm
            from huggingface_hub import hf_hub_download
        except ImportError:
            _need("sentencepiece / huggingface_hub", "local")
        sp = spm.SentencePieceProcessor(model_file=hf_hub_download(ident, "tokenizer.model"))
        return _local(lambda s: len(sp.encode(s)))

    if kind in ("anthropic", "gemini"):
        cache = api_cache if api_cache is not None else ApiCache.load()
        return _ApiCounter(kind, ident, cache, api_workers)

    raise ValueError(f"unknown tokenizer kind {kind!r}")


def _local(fn):
    return lambda texts: [fn(t) for t in texts]


def _key(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class ApiCache:
    def __init__(self, data, path):
        self.data, self.path, self.lock = data, Path(path), threading.Lock()

    @classmethod
    def load(cls, path=DEFAULT_CACHE):
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return cls(data, path)

    def get(self, model, text):
        return self.data.get(model, {}).get(_key(text))

    def put(self, model, text, n):
        with self.lock:
            self.data.setdefault(model, {})[_key(text)] = n

    def save(self):
        if not self.data:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {m: dict(sorted(v.items())) for m, v in sorted(self.data.items())}
        self.path.write_text(json.dumps(data, indent=0, sort_keys=True) + "\n", encoding="utf-8")


class _ApiCounter:
    def __init__(self, kind, model, cache, workers):
        self.kind, self.model, self.cache, self.workers = kind, model, cache, workers
        self._raw = None

    def _client(self):
        if self._raw:
            return self._raw
        if self.kind == "anthropic":
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise Skip("ANTHROPIC_API_KEY not set and counts not cached")
            try:
                import anthropic
            except ImportError:
                _need("anthropic", "api")
            client = anthropic.Anthropic()

            def raw(text):
                return client.messages.count_tokens(
                    model=self.model, messages=[{"role": "user", "content": text}]
                ).input_tokens

        else:
            if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
                raise Skip("GEMINI_API_KEY not set and counts not cached")
            try:
                from google import genai
            except ImportError:
                _need("google-genai", "api")
            client = genai.Client()

            def raw(text):
                return client.models.count_tokens(model=self.model, contents=text).total_tokens

        self._raw = raw
        return raw

    def _overhead(self):
        cached = self.cache.data.get(self.model, {}).get(_OVERHEAD_KEY)
        if cached is None:
            cached = self._client()(".") - 1
            with self.cache.lock:
                self.cache.data.setdefault(self.model, {})[_OVERHEAD_KEY] = cached
        return cached

    def __call__(self, texts):
        missing = sorted({t for t in texts if self.cache.get(self.model, t) is None})
        if missing:
            try:
                raw = self._client()
                overhead = self._overhead()

                def one(t):
                    self.cache.put(self.model, t, raw(t) - overhead)

                with ThreadPoolExecutor(self.workers) as ex:
                    list(ex.map(one, missing))
            except Skip:
                raise
            except Exception as e:  # auth, rate limit, unknown model ...
                raise Skip(f"{type(e).__name__}: {str(e)[:120]}") from e
            finally:
                self.cache.save()
        return [self.cache.get(self.model, t) for t in texts]
