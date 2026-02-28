from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Tuple

import chromadb
from chromadb.utils import embedding_functions

from src.data_processor import PatentParser
from src.telecom_utils import redact_telecom_fingerprints


def _stable_id(path: Path, chunk_index: int) -> str:
    h = hashlib.sha256(f"{path.as_posix()}::{chunk_index}".encode("utf-8")).hexdigest()[:24]
    return f"kb_{h}"


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _extract_text(path: Path, parser: PatentParser) -> str:
    if path.suffix.lower() == ".pdf":
        return parser.extract_text(str(path))
    return _read_text_file(path)


def _chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 150) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    buf = ""

    for p in paras:
        if not buf:
            buf = p
            continue
        if len(buf) + 2 + len(p) <= max_chars:
            buf = buf + "\n\n" + p
        else:
            chunks.append(buf)
            if overlap > 0:
                tail = buf[-overlap:]
                buf = (tail + "\n\n" + p).strip()
            else:
                buf = p

    if buf:
        chunks.append(buf)

    return chunks


def ingest_private_telecom_responses(
    *,
    kb_dir: str = "private_knowledge_base",
    persist_dir: str = "private_knowledge_base/chroma_db",
    collection_name: str = "telecom_responses",
    embedding_model: str = "all-MiniLM-L6-v2",
) -> Dict[str, int]:
    kb_path = Path(kb_dir)
    if not kb_path.exists():
        raise RuntimeError(f"Missing knowledge base directory: {kb_dir}")

    client = chromadb.PersistentClient(path=str(Path(persist_dir)))
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=embedding_model)
    collection = client.get_or_create_collection(name=collection_name, embedding_function=embed_fn)

    parser = PatentParser()

    supported = {".txt", ".md", ".pdf"}
    files = [p for p in kb_path.rglob("*") if p.is_file() and p.suffix.lower() in supported]

    added = 0
    skipped = 0

    for path in sorted(files):
        raw_text = _extract_text(path, parser)
        redacted = redact_telecom_fingerprints(raw_text)
        chunks = _chunk_text(redacted)

        if not chunks:
            skipped += 1
            continue

        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, str]] = []

        for idx, ch in enumerate(chunks):
            ids.append(_stable_id(path, idx))
            docs.append(ch)
            metas.append(
                {
                    "source": path.as_posix(),
                    "chunk": str(idx),
                    "type": "response_to_rejection",
                }
            )

        collection.upsert(ids=ids, documents=docs, metadatas=metas)
        added += len(chunks)

    return {
        "files_total": len(files),
        "chunks_added": added,
        "files_skipped": skipped,
    }


def main() -> None:
    stats = ingest_private_telecom_responses()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
