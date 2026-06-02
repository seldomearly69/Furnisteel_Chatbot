# Furnisteel Systems WhatsApp Chatbot

Customer-facing WhatsApp Business chatbot for **Furnisteel Systems Pte Ltd**, with:

- **WhatsApp Cloud API** webhooks (via [pywa](https://pywa.readthedocs.io/))
- **PostgreSQL** for full chat history
- **ChromaDB** vector store for RAG retrieval
- **Markdown** document pipeline with section-aware chunking (`.md`)
- **Docker Compose** for one-command local deployment

## Architecture

```mermaid
flowchart TD
    Customer[WhatsApp Customer] --> Meta[Meta Cloud API]
    Meta --> App[FastAPI + pywa]
    App --> PG[(PostgreSQL)]
    Docs[Markdown files] --> Ingest[Section chunker]
    Ingest --> Chroma[(ChromaDB + OpenAI embeddings)]
    App -->|"Last 5 msgs"| QueryGen[OpenAI query generation]
    QueryGen --> Chroma
    Chroma -->|"Top candidates"| Rerank[Cohere rerank API]
    Rerank --> App
    App -->|"Last 10 msgs + chunks"| Chat[OpenAI chat completion]
    Chat --> App
    App --> Customer
```

1. Customer messages arrive on your WhatsApp Business number.
2. Meta forwards events to the pywa webhook; messages are stored in PostgreSQL.
3. **Retrieval query**: the last 5 messages are sent to OpenAI to produce a focused search query.
4. **Retrieve**: ChromaDB vector search uses **OpenAI embeddings** (`text-embedding-3-small` by default); top candidates are **reranked** via the **Cohere rerank API**.
5. **Reply**: the last 10 messages plus reranked chunks are sent to OpenAI for the final answer, then sent back on WhatsApp.

## Quick start

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with:

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Embeddings, query generation, and chat completion |
| `OPENAI_EMBEDDING_MODEL` | Embedding model for ChromaDB (default `text-embedding-3-small`) |
| `COHERE_API_KEY` | Reranks retrieved chunks before the final reply |
| `RAG_CANDIDATE_K` | Vector hits passed to Cohere (default 25) |
| `RAG_TOP_K` | Chunks kept after rerank (default 5) |
| `RETRIEVAL_HISTORY_MESSAGES` | Messages used for query generation (default 5) |
| `COMPLETION_HISTORY_MESSAGES` | Messages sent to final chat model (default 10) |
| `WHATSAPP_TOKEN` | Meta Graph API permanent token |
| `WHATSAPP_PHONE_ID` | Phone number ID from Meta dashboard |
| `WHATSAPP_VERIFY_TOKEN` | Webhook verification string you choose |
| `WHATSAPP_APP_SECRET` | App secret for signature validation |
| `WHATSAPP_CALLBACK_URL` | Public HTTPS URL (e.g. ngrok) |

### 2. Add knowledge documents

Place Markdown files in `data/documents/`:

```bash
cp /path/to/catalog.md data/documents/
```

### 3. Start the stack

```bash
docker compose up -d --build
```

### 4. Ingest documents into ChromaDB

```bash
# One-off ingestion (waits for chromadb)
docker compose --profile ingest run --rm ingest

# Or synchronous via API
curl -X POST "http://localhost:8080/admin/ingest/sync"
```

Upload a single file:

```bash
curl -F "file=@data/documents/catalog.md" \
  http://localhost:8080/admin/documents/upload
```

### 5. Expose webhook to Meta

For local development, use [ngrok](https://ngrok.com/):

```bash
ngrok http 8080
```

In [Meta for Developers](https://developers.facebook.com/) → your app → **WhatsApp → Configuration**:

1. **Callback URL**: `https://<your-ngrok-host>/` (pywa registers on the FastAPI app root)
2. **Verify token**: same as `WHATSAPP_VERIFY_TOKEN` in `.env`
3. Subscribe to **messages** webhook field

Set `WHATSAPP_CALLBACK_URL` to your public URL if using pywa auto-registration.

### 6. Verify

```bash
curl http://localhost:8080/health
```

Send a WhatsApp text message to your business number.

## Markdown chunking

Documents are split on `#` headings into **sections**. Chunks are built by appending whole sections until `CHUNK_MAX_TOKENS` would be exceeded — sections are never cut mid-heading.

| Behaviour | Detail |
|-----------|--------|
| Section split | ATX headings (`#` … `######`) |
| Chunk assembly | Add full sections until token limit |
| Oversized section | Split on blank-line paragraphs only |
| Token counting | tiktoken (`CHUNK_TOKENIZER_MODEL`, default `gpt-4o-mini`) |

Example: if `## Warranty` + `## Shipping` fit in one chunk, both appear in full. If adding `## Returns` would exceed the limit, it starts a new chunk.

Re-process everything:

```bash
docker compose run --rm app python -m app.ingestion.cli --force
```

## Project layout

```
app/
  main.py              # FastAPI app, admin routes, WhatsApp setup
  config.py            # Environment settings
  db/                  # PostgreSQL models + repository
  chat/                # RAG + OpenAI reply generation
  rag/                 # ChromaDB, OpenAI embeddings, Cohere rerank, retrieval
  ingestion/           # Markdown parse → section chunk → index
  whatsapp/            # Incoming message handlers
data/documents/        # Place knowledge-base files here
docker-compose.yml
Dockerfile
```

## Docker commands

```bash
# Start
docker compose up -d --build

# Logs
docker compose logs -f app

# Stop and remove containers (keeps volumes)
docker compose down

# Stop and remove volumes (full reset)
docker compose down -v
```

## Local development (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start Postgres + Chroma separately, then:
export DATABASE_URL=postgresql+psycopg2://furnisteel:changeme@localhost:5432/furnisteel_chat
export CHROMA_HOST=localhost
uvicorn app.main:app --reload --port 8080
```

## Admin API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Service and index stats |
| `/admin/ingest/sync` | POST | Scan `data/documents/` and index |
| `/admin/ingest` | POST | Background ingestion |
| `/admin/documents/upload` | POST | Upload + index one file |
| `/admin/conversations` | GET | List WhatsApp conversations (for UI) |
| `/admin/conversations/{id}/messages` | GET | List messages in a conversation (for UI) |

## Admin Chat UI

The WhatsApp-style chat viewer runs in a separate container and is bound to **localhost only**.

- Open: `http://127.0.0.1:3000`
- It reads from the API at `http://localhost:8080` (CORS enabled for localhost).

## Daily email: new customers (last 24h)

A separate `notifier` service runs a daily scheduled job that emails you all **new WhatsApp customers** (new `conversations`) created in the last 24 hours.

### Configure

Set these in `.env`:

- `NEW_CUSTOMERS_EMAIL_TO`
- `SMTP_USER`
- `SMTP_PASSWORD` (recommended: Google **App Password**)
- `SMTP_FROM` (optional; defaults to `SMTP_USER`)
- `SMTP_HOST` (default `smtp.gmail.com`)
- `SMTP_PORT` (default `587`)
- `NOTIFIER_TIMEZONE` (default `Asia/Singapore`)
- `NOTIFIER_CRON` (default `0 9 * * *` = 9:00am daily)

### Run

```bash
docker compose up -d --build notifier
docker compose logs -f notifier
```

To test immediately once:

```bash
NOTIFIER_RUN_ON_START=true docker compose up -d --build notifier
```

## Production notes

- Put **nginx** or a cloud load balancer in front with TLS termination.
- Restrict `/admin/*` routes (API key, IP allowlist, or internal network only).
- Use Meta **permanent** system user tokens with least privilege.
- Back up `postgres_data` and `chroma_data` Docker volumes.
- After changing `OPENAI_EMBEDDING_MODEL`, re-ingest all markdown (`--force`) so vectors match.
- Requires valid `OPENAI_API_KEY`; set `COHERE_API_KEY` for reranking (without it, vector order is used as fallback).
- If you see Chroma errors like `KeyError('_type')`, ensure the **Python client** `chromadb` version matches the **server** image version, and consider resetting the `chroma_data` volume.

## License

Proprietary — Furnisteel Systems Pte Ltd.
