"""CLI entry point for document ingestion."""

import argparse
import logging
import sys

from app.ingestion.pipeline import DocumentIngestionPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Furnisteel knowledge base markdown documents"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest files even if already indexed",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Ingest a single file instead of scanning the documents directory",
    )
    args = parser.parse_args()

    pipeline = DocumentIngestionPipeline()
    if args.file:
        from pathlib import Path

        count = pipeline.ingest_file(Path(args.file))
        print(f"Ingested {count} chunks from {args.file}")
        return 0

    stats = pipeline.ingest_all(force=args.force)
    print(
        f"Done: {stats['files']} files, {stats['chunks']} chunks, "
        f"{stats['skipped']} skipped, {stats['errors']} errors"
    )
    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
