# CLAUDE.md

Working notes for AI agents. Keep this current when behaviour changes. User-facing
setup/ops docs live in `README.md` — don't duplicate them here.

## What this is

A WhatsApp customer-support bot for Furnisteel Systems. FastAPI + pywa webhook takes
inbound WhatsApp text/images, runs a multi-step RAG pipeline over Markdown docs
(ChromaDB + OpenAI embeddings + Cohere rerank), and replies via OpenAI chat/vision.
Full chat history in PostgreSQL. Side pieces: a React admin viewer (`ui/`) and a
standalone daily-email service (`notifier/`).

## Run / iterate

```bash
docker compose up -d --build            # full stack (postgres, chromadb, app, nginx, chat-ui)
docker compose logs -f app
docker compose --profile ingest run --rm ingest     # (re)index data/documents/
docker compose run --rm app python -m app.ingestion.cli --force   # force re-ingest
```

Local (no Docker): start Postgres + Chroma yourself, then
`uvicorn app.main:app --reload --port 8080` with `DATABASE_URL` / `CHROMA_HOST` set.
UI: `cd ui && npm install && npm run dev` (port 3000).

### Tests

`tests/` holds plain-assert files (no pytest config, no fixtures). Run either way:

```bash
python -m pytest tests/ -q            # if pytest is installed
PYTHONPATH=. python tests/test_reply_parser.py   # each file also runs standalone
```

`test_reply_parser.py` is stdlib-only. `test_markdown_chunker.py` imports `app.config`
(needs `pydantic-settings`) and `tiktoken`. No linter/formatter is configured. If you
add non-trivial logic, leave one runnable `assert`-based check next to it.

## Request flow (text message)

`app/whatsapp/handlers.py::on_text` — offloads the blocking pipeline with
`asyncio.to_thread` (`_reply_in_thread`), so a slow completion doesn't stall other
inbound webhooks —
→ `ChatService.generate_reply` (`app/chat/service.py`) — this file is the whole brain:

1. `get_or_create_conversation`, then `_is_first_customer_message` is checked
   **before** the new message is stored (so "first" == zero prior rows).
2. Store the user message.
3. **First-message greeting**: if first message + `FIRST_MESSAGE_GREETING_ENABLED`,
   return the greeting and **skip RAG entirely**. The customer's first message is
   never actually answered — only greeted.
4. `_complete_conversation`:
   - `_split_compound_query` — OpenAI (`OPENAI_RETRIEVAL_QUERY_MODEL`) resolves
     context/pronouns and returns N atomic sub-queries (one per line).
   - For each sub-query: `_retrieve_with_confidence_loop` — vector search
     (`skip_rerank=True`), score via `_best_confidence` (rerank score if present,
     else `1 - distance/2`). Below `RAG_CONFIDENCE_THRESHOLD` → `_refine_retrieval_query`
     (OpenAI) and retry, up to `RAG_MAX_RETRIEVAL_ROUNDS`.
   - Pool all hits → `_dedupe_hits` (key: `source_file::chunk_index`, fallback
     normalized text) → `_rerank_merged_hits` (Cohere against the *original*
     customer message, capped to `RAG_FINAL_CONTEXT_PCT` of pool size; without
     `COHERE_API_KEY`, sort by vector distance).
   - `_query_wants_images` (keyword check, `app/rag/image_intent.py`) → optional
     `retriever.retrieve_images` — gallery chunks that carry `image_url` metadata;
     their URLs are prepended to the context as an "Available images" block.
   - Build messages: system prompt (`DEFAULT_SYSTEM_PROMPT`, or the file at
     `SYSTEM_PROMPT_PATH` if set — read once via `_system_prompt_override`, cached;
     formatted with `{company_name}` + `{max_outbound_images}`) + a system turn
     with the context + last `COMPLETION_HISTORY_MESSAGES` turns → OpenAI
     `OPENAI_MODEL`, temp 0.3.
5. `parse_assistant_reply` (`app/chat/reply_parser.py`) — pull `[[IMAGE:https://...]]`
   lines out of the text into `image_urls` (capped at `MAX_OUTBOUND_IMAGES`).
6. Persist assistant text + one `image` row per URL, `session.commit()` (the
   service commits, not the handler).
7. `deliver_assistant_reply` (`app/whatsapp/outbound.py`) — text first, split at
   4096 chars on newline boundaries, then each image via `message.reply_image`.

## Request flow (image message)

`handlers.py::on_image` → download bytes from Meta → `R2Storage.upload_image`
(`app/storage/r2.py`, run via `asyncio.to_thread`) → store message with
`media_url`/`media_key` → `ChatService.handle_image_message` (same RAG path, also
threaded; history images are sent to the model as vision `image_url` parts via
`_openai_user_message`, detail = `OPENAI_VISION_DETAIL`). If `r2.is_configured()`
is false (needs 5 `R2_*` vars + public bucket), the user gets a fallback text
reply and nothing is stored.

## Ingestion

`app/ingestion/pipeline.py`: discover `*.md`/`*.markdown` under `DOCUMENTS_DIR` →
`parse_markdown_sections` (ATX headings) → chunk.
- **Normal docs**: `chunk_markdown_sections` accumulates whole sections until
  `CHUNK_MAX_TOKENS` (tiktoken, `CHUNK_TOKENIZER_MODEL`); oversized sections split
  on blank lines only.
- **Gallery docs** (filename contains `gallery`, or any section body has
  `**Image URL:**`): one chunk per `##` section, no token limit. `image_url` /
  `image_title` regex-extracted into metadata (`app/ingestion/image_metadata.py`).
- Chunk id = `{sha256(file)}:{index}`; `file_hash` in metadata is the dedupe key
  for `upsert_chunks` (delete-by-`file_hash` then add). `ingest_all` skips files
  whose hash is already indexed unless `force=True`.
- Non-image retrieval filters out `source_file == GALLERY_SOURCE_FILE`
  (`settings.gallery_source_file`, default `furnisteel_project_gallery.md`).

## Data model (`app/db/models.py`)

- `conversations`: one row per `whatsapp_user_id` (unique).
- `chat_messages`: `role` (user/assistant/system), `message_type` (text/image),
  `content`, `media_url`/`media_key`/`media_mime_type`, `whatsapp_message_id`.
- History queries order by `created_at DESC, role_priority DESC` then reverse —
  `role_priority` is a deliberate tiebreak (user before assistant) for equal
  timestamps (commit `bfda26c`). Message `id` is a UUID, not orderable.

## Admin API / UI

- All `/admin/*` except `/admin/auth/token` require `Authorization: Bearer <JWT>`.
  Get one by POSTing `{"api_key": ADMIN_API_KEY}` to `/admin/auth/token`.
  JWT is HS256 with `JWT_SECRET`, `sub: "admin"`.
- `/admin/conversations/{id}/messages` uses cursor pagination: `before` XOR `after`
  ISO timestamp, `limit` 1–200.
- `ui/` is Vite/React/Tailwind, built to a static nginx site. `VITE_API_BASE` is
  baked in at **build time** (docker build arg) — rebuild `chat-ui` to change it.
  UI polls `/admin/*` every 10s; unread counts are localStorage-only.

## Shared singletons (all `@lru_cache`, one per process)

| Accessor | Module | Notes |
|----------|--------|-------|
| `get_settings()` | `app/config.py` | env changes need a process restart |
| `get_openai_client()` | `app/openai_client.py` | reused by embeddings, retrieval, completion |
| `get_knowledge_store()` | `app/rag/chroma_store.py` | ChromaDB HTTP client + embedding fn; used by `/health`, `ChatService`, ingestion |
| `get_engine()` / `get_session_factory()` | `app/db/session.py` | one connection pool for the whole process |
| `get_r2_storage()` | `app/storage/r2.py` | boto3 client created lazily on first upload |

Prefer these over constructing clients directly. The blocking pipeline runs in
worker threads (`asyncio.to_thread`); the OpenAI and httpx-based Chroma clients are
safe to share across them.

## Gotchas / landmines

- `chromadb` Python client (`requirements.txt`) and server image
  (`docker-compose.yml`) are both pinned to `0.5.23` and **must match** — mismatch
  shows as `KeyError('_type')`; fix by resetting the `chroma_data` volume.
- Embeddings are always computed client-side (`chroma_store` passes
  `embeddings=`/`query_embeddings=`, never `query_texts`). Chroma never needs an
  OpenAI key; the app always does.
- `_system_prompt_override` is `@lru_cache`d on the path — editing the prompt file
  needs a restart. A custom prompt must escape literal braces as `{{ }}` (it goes
  through `str.format`).
- `asyncio.to_thread` uses the default thread pool (`min(32, cpu+4)` workers) — it
  bounds, not eliminates, concurrent pipeline runs. A real queue is the next step
  if inbound volume ever needs it.
- **No Alembic migrations** despite the dep. `init_db()` (`app/db/session.py`) does
  `create_all` + hand-rolled `ALTER TABLE chat_messages ADD COLUMN ...` on startup.
- `.env.example` sets `MAX_OUTBOUND_IMAGES=3`; the code default is 5.
- `notifier/` is fully standalone — its own `Dockerfile`, `requirements.txt`, and a
  duplicated `Conversation` model. Changes to the real model don't propagate.
- First customer message is only greeted, never answered (see step 3 above).

## Conventions

- `from __future__ import annotations` everywhere; `str | None` unions; f-strings.
- Sub-package `__init__.py` files are **empty** — always import from the concrete
  module (`from app.rag.retrieval import KnowledgeRetriever`), never the package.
- Settings via `pydantic-settings`; read through `get_settings()`, never `os.environ`
  in `app/` (the notifier is the exception — it uses `os.getenv`). Add a new knob
  as a `Settings` field with a default, not an inline literal.
- All DB access goes through `ChatRepository`; don't write queries in routes/service.
- Logging is `logging.getLogger(__name__)` with heavy `logger.info` breadcrumbs on
  the RAG path — match that style, prefix with `RAG ` for pipeline steps.
