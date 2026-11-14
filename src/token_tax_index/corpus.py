"""FLORES-200 devtest download and parallel-corpus loading.

The corpus is fetched, never committed: FLORES-200 is © Meta Platforms, Inc., CC BY-SA 4.0.
A corpus file is JSONL, one aligned sentence per line: {"id": ..., "domain": ..., <code>: text, ...}.
Language codes are FLORES-200 codes (e.g. slk_Latn); the baseline is eng_Latn.
"""
import json
import tarfile
import urllib.request
from pathlib import Path

FLORES_URL = "https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz"
BASE = "eng_Latn"
META_KEYS = {"id", "domain"}
DEFAULT_CORPUS = Path("data") / "flores200_devtest.jsonl"


def download(url, dest):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    return dest


def parse_flores_tarball(path, langs=None, split="devtest"):
    """Return (rows, langs) from a FLORES-200 tarball. langs=None or ['all'] means every language."""
    texts, domains = {}, None
    with tarfile.open(path, "r:*") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            name = m.name.split("/")
            if name[-1] == f"metadata_{split}.tsv":
                lines = tar.extractfile(m).read().decode("utf-8").splitlines()
                header = lines[0].split("\t")
                col = header.index("domain")
                domains = [ln.split("\t")[col] for ln in lines[1:]]
            elif len(name) >= 2 and name[-2] == split and name[-1].endswith("." + split):
                code = name[-1][: -len(split) - 1]
                texts[code] = tar.extractfile(m).read().decode("utf-8").splitlines()
    if not texts:
        raise ValueError(f"{path}: no {split} files found; is this the FLORES-200 tarball?")
    wanted = sorted(texts) if not langs or langs == ["all"] else list(dict.fromkeys(langs))
    if BASE not in wanted:
        wanted.append(BASE)
    unknown = [lg for lg in wanted if lg not in texts]
    if unknown:
        raise ValueError(f"unknown FLORES-200 codes: {', '.join(unknown)}")
    n = len(texts[BASE])
    bad = [lg for lg in wanted if len(texts[lg]) != n]
    if bad:
        raise ValueError(f"misaligned line counts for {bad}")
    rows = []
    for i in range(n):
        row = {"id": i, "domain": domains[i] if domains and i < len(domains) else "all"}
        row.update({lg: texts[lg][i].strip() for lg in wanted})
        rows.append(row)
    return rows, wanted


def write_jsonl(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def load_corpus(path, langs=None):
    """Load a JSONL parallel corpus. Returns (rows, langs) with the baseline last."""
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    if not rows:
        raise ValueError(f"{path}: empty corpus")
    available = [k for k in rows[0] if k not in META_KEYS]
    if BASE not in available:
        raise ValueError(f"{path}: baseline language {BASE!r} not in corpus")
    if langs:
        unknown = [lg for lg in langs if lg not in available]
        if unknown:
            raise ValueError(f"{path}: languages not in corpus: {', '.join(unknown)}")
        available = [lg for lg in available if lg in langs or lg == BASE]
    for r in rows:
        missing = [lg for lg in available if not r.get(lg)]
        if missing:
            raise ValueError(f"{path}: row {r.get('id')} missing {missing}")
    return rows, [lg for lg in available if lg != BASE] + [BASE]
