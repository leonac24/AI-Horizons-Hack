"""Compile local source documents into a checked-in Laya evidence index.

Put text, Markdown, or PDF files under data/raw/laya/<source_id>/, where
source_id is declared in data/config/sources.yaml. Zoning text saved under
data/raw/zoning/ is included as pgh_zoning_code. Raw files stay gitignored;
the compact, source-linked classification index is committed to Git.

Laya classifies passages. It does not extract measurements, verify law, or
change the parcel index, assumptions, scoring, or reviewed zoning rules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]

RAW = ROOT / "data" / "raw"
OUTPUT = ROOT / "data" / "processed" / "laya_evidence.json"
SUPPORTED = {".txt", ".md", ".pdf"}
MAX_CHARS = 1400

QUESTIONS = {
    "topic": {
        "type": "choice",
        "instructions": "Which Lotline input does this passage most directly address? Choose other if none applies.",
        "criteria": {
            "zoning": "Land use, permitted housing, dimensions, or zoning approval",
            "transit_jobs": "Jobs reachable by transit or transit travel time",
            "carbon": "Building energy, embodied carbon, electricity, or travel emissions",
            "housing_need": "Housing affordability or income-specific housing need",
            "sewer": "Sewer overflow, sewer sheds, or available sewer capacity",
            "cost": "Construction, operating, financing, or subsidy costs",
            "site": "Parcel geometry, flood, slope, mine, or other site condition",
            "other": "None of these inputs",
        },
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sources() -> dict[str, dict]:
    doc = yaml.safe_load((ROOT / "data/config/sources.yaml").read_text(encoding="utf-8"))
    return doc["sources"]


def discover(raw: Path = RAW) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for path in sorted((raw / "zoning").glob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED:
            found.append(("pgh_zoning_code", path))
    base = raw / "laya"
    if base.exists():
        for path in sorted(base.glob("*/*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED:
                found.append((path.parent.name, path))
    return found


def read_pages(path: Path) -> list[str]:
    if path.suffix.lower() == ".pdf":
        try:
            text = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                capture_output=True, text=True, check=True,
            ).stdout
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise RuntimeError(f"Could not read {path}; install Poppler pdftotext") from exc
        return text.split("\f")
    return [path.read_text(encoding="utf-8")]


def chunks(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Bound Laya's short context while retaining every nonblank source word."""
    words = re.findall(r"\S+", text)
    out: list[str] = []
    current: list[str] = []
    size = 0
    for word in words:
        if current and size + 1 + len(word) > max_chars:
            out.append(" ".join(current))
            current, size = [], 0
        current.append(word)
        size += len(word) + (1 if size else 0)
    if current:
        out.append(" ".join(current))
    if len(out) >= 2 and len(out[-1]) < max_chars // 3:
        tail = (out[-2] + " " + out[-1]).split()
        candidates = [(" ".join(tail[:i]), " ".join(tail[i:])) for i in range(1, len(tail))]
        balanced = [(a, b) for a, b in candidates if len(a) <= max_chars and len(b) <= max_chars]
        if balanced:
            out[-2:] = min(balanced, key=lambda pair: abs(len(pair[0]) - len(pair[1])))
    return out


def _answer(result: dict) -> dict:
    answers = result.get("answers")
    if not isinstance(answers, dict):
        raise TypeError("Laya returned no answers")
    topic = answers.get("topic", {}).get("choice")
    if topic not in QUESTIONS["topic"]["criteria"]:
        raise ValueError(f"Laya returned an unknown topic: {topic!r}")
    return {
        "topic": topic,
    }


def source_url(path: Path, registered_url: str | None) -> str | None:
    """Permit a precise page link in text headers, restricted to the registered host."""
    if path.suffix.lower() not in {".txt", ".md"} or not registered_url:
        return registered_url
    host = urlparse(registered_url).hostname
    for line in path.read_text(encoding="utf-8").splitlines()[:10]:
        if line.startswith("URL: "):
            candidate = line.removeprefix("URL: ").strip()
            parsed = urlparse(candidate)
            if parsed.scheme == "https" and parsed.hostname == host:
                return candidate
    return registered_url


def compile_index(
    documents: list[tuple[str, Path]],
    predict: Callable[[str, dict], dict],
    registry: dict[str, dict],
    checkpoint: str,
    laya_version: str,
    root: Path = ROOT,
) -> dict:
    if not documents:
        raise ValueError("No source documents found in data/raw/zoning or data/raw/laya/<source_id>")
    index: dict = {
        "schema_version": 1,
        "model": {"library": "laya", "version": laya_version, "checkpoint": checkpoint},
        "question_sha256": sha256(json.dumps(QUESTIONS, sort_keys=True).encode()),
        "documents": [],
        "passages": [],
    }
    for source_id, path in documents:
        if source_id not in registry:
            raise ValueError(f"Unknown source id {source_id!r} for {path}")
        raw = path.read_bytes()
        rel = path.relative_to(root).as_posix()
        pages = read_pages(path)
        document_url = source_url(path, registry[source_id].get("url"))
        doc_count = 0
        for page_no, page in enumerate(pages, 1):
            for passage in chunks(page):
                result = _answer(predict(passage, QUESTIONS))
                words = passage.split()
                index["passages"].append({
                    "id": sha256(f"{rel}:{page_no}:{doc_count}:{passage}".encode())[:20],
                    "source_id": source_id,
                    "source_name": registry[source_id].get("name", source_id),
                    "source_url": document_url,
                    "document": rel,
                    "page": page_no if path.suffix.lower() == ".pdf" else None,
                    "part": doc_count + 1,
                    "input_sha256": sha256(passage.encode()),
                    "excerpt": " ".join(words[:24]),
                    **result,
                })
                doc_count += 1
        index["documents"].append({
            "source_id": source_id,
            "path": rel,
            "source_url": document_url,
            "sha256": sha256(raw),
            "passage_count": doc_count,
        })
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", choices=("english", "multilingual", "typed-decisions"),
                        default="typed-decisions")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    documents = discover()
    if not documents:
        parser.error("No text or PDF inputs found; add files under data/raw/laya/<source_id>/ or data/raw/zoning/")
    try:
        import laya
    except ImportError as exc:
        raise SystemExit("Install Laya locally: python -m pip install 'laya==0.3.20'") from exc
    router = laya.Router(max_loaded=1)

    def predict(text: str, questions: dict) -> dict:
        return router.predict(text, questions, model=args.checkpoint)

    index = compile_index(documents, predict, sources(), args.checkpoint, laya.__version__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(index['passages'])} passages from {len(index['documents'])} sources to {args.output}")


if __name__ == "__main__":
    main()
