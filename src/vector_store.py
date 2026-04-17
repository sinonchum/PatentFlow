from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import chromadb
from chromadb.api.types import EmbeddingFunction

try:
    from docx import Document  # python-docx
except Exception:  # pragma: no cover
    Document = None


class _FastEmbedEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name: str) -> None:
        try:
            from fastembed import TextEmbedding
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "fastembed is required for local embeddings. Install it with: pip install fastembed"
            ) from e

        self._model_name = model_name
        self._embedder = TextEmbedding(model_name=model_name)

    def __call__(self, input: List[str]) -> List[List[float]]:
        vectors = self._embedder.embed(input)
        out: List[List[float]] = []
        for v in vectors:
            try:
                out.append(v.tolist())
            except AttributeError:
                out.append(list(v))
        return out


def _stable_id(source: str, chunk_index: int) -> str:
    h = hashlib.sha256(f"{source}::{chunk_index}".encode("utf-8")).hexdigest()[:24]
    return f"tpl_{h}"


def _normalize(text: str) -> str:
    text = (text or "").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_paragraphs(paragraphs: Sequence[str], *, max_chars: int = 1200, overlap: int = 150) -> List[str]:
    cleaned = [p.strip() for p in paragraphs if p and p.strip()]
    chunks: List[str] = []
    buf = ""

    for p in cleaned:
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

    return [_normalize(c) for c in chunks if _normalize(c)]


def _read_txt(path: Path) -> List[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = _normalize(text)
    if not text:
        return []
    return [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]


def _extract_examiner_from_text(text: str) -> str:
    # Template metadata convention: a leading line like "#Examiner: Lastname, Firstname"
    m = re.search(r"^\s*#\s*Examiner\s*:\s*(.+)\s*$", text or "", flags=re.IGNORECASE | re.MULTILINE)
    if m:
        return _normalize(m.group(1)).splitlines()[0].strip()
    return ""


def _read_docx(path: Path) -> List[str]:
    if Document is None:
        raise RuntimeError("python-docx is required to read .docx files. Install it with: pip install python-docx")

    doc = Document(str(path))
    paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return paras


@dataclass
class SearchResult:
    text: str
    metadata: Dict[str, str]
    distance: float


class PatentVectorStore:
    def __init__(
        self,
        *,
        persist_path: str = "data/vector_db",
        collection_name: str = "telecom_responses",
        embedding_model: str = "BAAI/bge-small-en-v1.5",
    ) -> None:
        self.persist_path = str(Path(persist_path))
        Path(self.persist_path).mkdir(parents=True, exist_ok=True)

        embed_fn = _FastEmbedEmbeddingFunction(model_name=embedding_model)

        self._client = chromadb.PersistentClient(path=self.persist_path)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=embed_fn,
        )

    def add_response_templates(self, folder_path: str) -> Dict[str, int]:
        root = Path(folder_path)
        if not root.exists():
            raise RuntimeError(f"Folder does not exist: {folder_path}")

        supported = {".txt", ".docx"}
        files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in supported]

        added_chunks = 0
        skipped_files = 0

        for f in sorted(files):
            try:
                if f.suffix.lower() == ".txt":
                    raw_text = f.read_text(encoding="utf-8", errors="ignore")
                    examiner = _extract_examiner_from_text(raw_text)
                    paras = [p.strip() for p in re.split(r"\n\s*\n+", _normalize(raw_text)) if p.strip()]
                else:
                    paras = _read_docx(f)
                    examiner = ""

                chunks = _chunk_paragraphs(paras)
                if not chunks:
                    skipped_files += 1
                    continue

                ids: List[str] = []
                docs: List[str] = []
                metas: List[Dict[str, str]] = []

                source_name = f.name
                source_path = f.as_posix()

                for idx, ch in enumerate(chunks):
                    ids.append(_stable_id(source_path, idx))
                    docs.append(ch)
                    meta = {"source": source_name, "source_path": source_path, "chunk": str(idx)}
                    if examiner:
                        meta["examiner"] = examiner
                    metas.append(meta)

                self._collection.upsert(ids=ids, documents=docs, metadatas=metas)
                added_chunks += len(chunks)

            except Exception:
                skipped_files += 1

        return {
            "files_total": len(files),
            "files_skipped": skipped_files,
            "chunks_added": added_chunks,
        }

    def query_similar_logic(
        self,
        query_text: str,
        n_results: int = 2,
        *,
        examiner_name: str = "",
    ) -> List[SearchResult]:
        query_text = _normalize(query_text)
        if not query_text:
            return []

        examiner_name = (examiner_name or "").strip()
        if examiner_name:
            # Lightweight "weighting": inject examiner signal into the query text.
            # This allows building per-examiner style preferences in the template library
            # without requiring custom ANN scoring.
            query_text = _normalize(f"Examiner: {examiner_name}\n\n{query_text}")

        res = self._collection.query(query_texts=[query_text], n_results=int(n_results))

        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]

        out: List[SearchResult] = []
        ex = (examiner_name or "").strip().lower()
        for doc, meta, dist in zip(docs, metas, dists):
            md = meta or {}
            d = float(dist)
            if ex and isinstance(md, dict):
                md_ex = str(md.get("examiner") or "").strip().lower()
                if md_ex and md_ex == ex:
                    d = d * 0.8
            out.append(SearchResult(text=doc, metadata=md, distance=d))

        out.sort(key=lambda r: r.distance)
        return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--kb", default="private_knowledge_base")
    parser.add_argument("--persist", default="data/vector_db")
    parser.add_argument("--collection", default="telecom_responses")
    parser.add_argument("--embedding-model", default="BAAI/bge-small-en-v1.5")
    args = parser.parse_args()

    store = PatentVectorStore(
        persist_path=args.persist,
        collection_name=args.collection,
        embedding_model=args.embedding_model,
    )

    stats = store.add_response_templates(args.kb)
    print(stats)


if __name__ == "__main__":
    main()
