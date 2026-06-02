"""Markdown document ingestion pipeline for RAG embedding."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.config import get_settings
from app.ingestion.markdown_chunker import chunk_markdown_sections, parse_markdown_sections
from app.rag.chroma_store import ChromaKnowledgeStore

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".md", ".markdown"}


class DocumentIngestionPipeline:
    """Parse markdown by section, chunk without abrupt cuts, embed into ChromaDB."""

    def __init__(
        self,
        documents_dir: str | Path | None = None,
        store: ChromaKnowledgeStore | None = None,
    ):
        settings = get_settings()
        self.documents_dir = Path(documents_dir or settings.documents_dir)
        self.store = store or ChromaKnowledgeStore()

    def discover_documents(self) -> list[Path]:
        if not self.documents_dir.exists():
            self.documents_dir.mkdir(parents=True, exist_ok=True)
            return []

        files: list[Path] = []
        for path in sorted(self.documents_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                files.append(path)
        return files

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()

    def ingest_file(self, path: Path) -> int:
        logger.info("Processing markdown %s", path)
        content = path.read_text(encoding="utf-8")
        sections = parse_markdown_sections(content)
        chunk_texts = chunk_markdown_sections(sections)

        if not chunk_texts:
            logger.warning("No chunks produced for %s", path)
            return 0

        file_hash = self._file_hash(path)
        records: list[dict] = []
        for index, text in enumerate(chunk_texts):
            records.append(
                {
                    "id": f"{file_hash}:{index}",
                    "text": text,
                    "metadata": {
                        "source_file": path.name,
                        "source_path": str(path),
                        "file_hash": file_hash,
                        "chunk_index": index,
                        "format": "markdown",
                    },
                }
            )

        self.store.upsert_chunks(records, source_id=file_hash)
        logger.info("Ingested %s chunks from %s", len(records), path.name)
        return len(records)

    def ingest_all(self, *, force: bool = False) -> dict[str, int]:
        stats = {"files": 0, "chunks": 0, "skipped": 0, "errors": 0}
        for path in self.discover_documents():
            file_hash = self._file_hash(path)
            if not force and self.store.has_source(file_hash):
                stats["skipped"] += 1
                continue
            try:
                count = self.ingest_file(path)
                stats["files"] += 1
                stats["chunks"] += count
            except Exception:
                logger.exception("Failed to ingest %s", path)
                stats["errors"] += 1
        return stats
