"""Tokenizer registry and price list, both shipped as JSON in token_tax_index/data/."""
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

API_KINDS = {"anthropic", "gemini"}


@dataclass(frozen=True)
class TokenizerSpec:
    name: str
    kind: str
    id: str
    group: str = ""
    note: str = ""


def read_data(name, path=None):
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.loads(resources.files("token_tax_index.data").joinpath(name).read_text(encoding="utf-8"))


def load_tokenizers(path=None):
    return [TokenizerSpec(**t) for t in read_data("tokenizers.json", path)["tokenizers"]]


def load_prices(path=None):
    return read_data("prices.json", path)


def select(specs, filters=None, no_api=False):
    """Keep specs whose name contains any of the comma-separated, case-insensitive filters."""
    subs = [f.strip().lower() for f in (filters or "").split(",") if f.strip()]
    return [
        s for s in specs
        if (not subs or any(f in s.name.lower() for f in subs)) and not (no_api and s.kind in API_KINDS)
    ]
