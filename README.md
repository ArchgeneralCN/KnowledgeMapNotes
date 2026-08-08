<p align="center">
  <strong>English</strong> |
  <a href="README.zh-CN.md">简体中文</a> |
  <a href="README.ja.md">日本語</a> |
  <a href="README.ko.md">한국어</a>
</p>

# KnowledgeMapNotes

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Xikcn/KnowledgeMapNotes)

KnowledgeMapNotes is a knowledge-graph-based note system. It converts TXT, Markdown, and PDF documents into knowledge graphs and provides HybridRAG question answering using vector retrieval, entity relationships, and graph community information.

The project includes a Vue 3 web interface and a FastAPI backend. It supports incremental document updates, per-chunk processing progress, paginated communities for large graphs, streaming answers, and runtime AI configuration.

## Demo

https://github.com/user-attachments/assets/5e9e6ffd-4e18-4915-b3a4-85198eb8bb0f

## Features

- **Multi-format document processing**: Supports `.txt`, `.md`, and `.pdf`; PDF images can optionally be extracted with a vision model.
- **Knowledge graph construction**: Automatically extracts entities and relationships, calculates relationship weights, and performs knowledge fusion.
- **Configurable processing prompts**: Provides general, story, and custom note types. Custom types can edit prompts for entity extraction, relationship extraction, and knowledge fusion independently.
- **Reliable file updates**: Completed files with the same name can be updated incrementally. Residual data from a previously failed file is cleared before a complete retry.
- **Processing progress**: Displays upload, processing, incremental update, completion, and failure states, including chunk count, percentage, time per chunk, and estimated remaining time.
- **HybridRAG Q&A**: Combines vector retrieval, entity recognition, and graph communities. Supports regular and SSE streaming responses, stopping generation, and conversation history.
- **Graph visualization**: Supports node and relationship search, highlighting, edge weights, Louvain community overviews, and detail pages for large graphs.
- **Readable graph layout**: Uses static ForceAtlas2 for graph generation and redraws. Isolated nodes are placed around the relational graph, while coordinate scaling and collision resolution reduce overlap.
- **Knowledge base management**: Search and filter files, preview or download originals, inspect primary entities, delete files, and clear RAG history separately.
- **Source evidence navigation**: Click a node or relationship to jump to its source chunk. Layered highlighting distinguishes the source chunk, current entities/relationships, other entities/relationships, and relationship descriptions.
- **Document workflow**: Preview documents by default, inspect source, edit rich text, save drafts, browse document history, restore versions, apply incremental updates, and redraw graphs automatically.
- **Unified history restore**: Graph history stores document snapshots as well. Restoring a graph also restores its document, and document, incremental, and graph operations can be rolled back together.
- **Themes and readability**: Default, dark, blue, and eye-care themes share coordinated colors for text, panels, code blocks, draft notices, and evidence highlighting.
- **Resumable processing**: Graph construction saves checkpoints per text chunk, allowing tasks to pause and continue from the last completed chunk.
- **Automatic AI failover**: If the primary AI request fails or returns invalid JSON, the current chunk is retried with the fallback AI configuration.
- **Portable graph packages**: Export completed files as `.kmn.zip` packages containing the original document, graph pages, processing status, and RAG history. Drop the package into another instance to restore it without rerunning AI processing.
- **Built-in guide**: A completed software guide is imported on first deployment without requiring a text AI. Additional importable examples are available in `backend/kmnzips`.
- **Flexible workspace**: The source document, knowledge graph, and RAG panels can be viewed side by side, hidden, or resized.
- **Runtime AI settings**: The backend can start without a text-model Base URL or API key. Configure, test, and save the connection from the web interface after startup.
- **Single-process deployment**: FastAPI can serve `frontend/dist`, so the complete web application can run from the backend process after the frontend is built.

## Recent Updates

- The backend can start without a configured text model and now directs model-dependent operations to the web settings.
- AI settings include a connection test that does not save the submitted configuration and reports request latency.
- Added custom note types and a three-stage prompt editor with the general prompts loaded by default.
- Fixed failed reuploads incorrectly starting incremental updates; failed-task remnants are cleared before retrying.
- Strengthened frontend content security: raw Markdown HTML is disabled, output is sanitized with DOMPurify, external links use safe attributes, and file path parameters are encoded consistently.
- Updated frontend dependencies and replaced the legacy SVG loading solution; `npm audit` currently reports no known vulnerabilities.
- Added backend static frontend hosting, SPA route fallback, and `/api` prefix compatibility.
- Added document preview, source, and rich-text modes, draft saving, version restore, incremental file updates, and automatic graph redraws.
- Graph history now stores graph and document snapshots together.
- Reworked the four themes with softer color scales and coordinated highlighting.

## Planned Improvements

- Add a cross-note overview graph for discovering shared knowledge and topic relationships.
- Improve lazy loading, loading skeletons, and segmented rendering for very large documents.
- Add user-configurable theme colors and font density.

## Technology Stack

| Area | Technology |
| --- | --- |
| Backend | FastAPI, OpenAI Python SDK, ChromaDB, SentenceTransformers |
| Graph | NetworkX, PyVis, Louvain Community Detection |
| Frontend | Vue 3, Vite, Element Plus, Axios |
| Content rendering | Markdown-It, DOMPurify |
| Deployment | FastAPI static hosting, Docker Compose, Nginx |

## Documentation Site

Read the documentation online at [archgeneralcn.github.io/KMN_docs_site](https://archgeneralcn.github.io/KMN_docs_site/).

An independent VitePress documentation site is available in `docs-site/`. It covers setup, core workflows, deployment, security, environment variables, HTTP APIs, and troubleshooting, with local search, dark mode, and responsive navigation.

```bash
cd docs-site
npm install
npm run dev
```

Open http://localhost:5173. Run `npm run build` for a production build; static output is written to `docs-site/docs/.vitepress/dist`.

## Quick Start

### Requirements

- Python 3.10+
- Node.js 18+ for frontend builds or development
- A text-model API for graph construction and RAG; it does not have to be configured before the backend starts
- An optional CUDA GPU; use `DEVICE=cpu` in CPU-only environments

The first startup loads embedding and reranking models and therefore requires disk space. An internet connection is also required when downloading models from Hugging Face.

On the first deployment, only `backend/default_examples/本软件使用说明.kmn.zip` is imported automatically. This does not call the text AI or overwrite data with the same name. Optional completed packages in `backend/kmnzips` can be imported manually from the upload page. Set `DEFAULT_EXAMPLES_ENABLED=False` in `backend/.env` to start with an empty instance.

### 1. Clone the Repository

```bash
git clone https://github.com/Xikcn/KnowledgeMapNotes.git
cd KnowledgeMapNotes
```

### 2. Create the Backend Configuration

```bash
cp backend/.env.example backend/.env
```

Do not commit `backend/.env` when it contains real credentials.

The text-model fields may remain empty. After startup, open **Settings -> AI Model Settings** in the web interface, enter the Base URL, API key, and model name, test the connection, and then save it.

Example configuration for a CPU environment with online model loading:

```dotenv
# Prompt version: v1 is faster; v2 is slower but produces better results
PROMPTVISION=v1

# OpenAI-compatible text model; these fields may be configured in the UI
BASE_URL=
API_KEY=
MODEL_NAME=
TEMPERATURE=0
ENABLE_THINKING=False
AI_MAX_OUTPUT_TOKENS=8192
AI_MAX_OUTPUT_PARAMETER=max_tokens
RELATION_TEXT_BATCH_CHARS=2000
RELATION_SOURCE_BATCH_SIZE=20
RELATION_MAX_SPLIT_DEPTH=10
FALLBACK_ENABLED=False
FALLBACK_BASE_URL=
FALLBACK_API_KEY=
FALLBACK_MODEL_NAME=
DEFAULT_EXAMPLES_ENABLED=True

# Optional PDF image recognition
VL_API_KEY=
VL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VL_MODEL=qwen-vl-max-latest

# Embedding and reranking models
IS_USE_LOCAL=False
EMBEDDINGS=BAAI/bge-base-zh
EMBEDDINGS_PATH=/absolute/path/to/bge-base-zh
RERANK_MODEL=BAAI/bge-reranker-base
DEVICE=cpu

# Text splitters
SIMPLE=[txt,pdf]
SEMANTIC=[]
CHARACTER=[md]

# Runtime data directories, relative to backend/
CHROMADB_PATH=./chroma_data
UPLOAD_FOLDER=uploads
TXT_FOLDER=txt_files
RESULT_FOLDER=results
```

`SIMPLE`, `SEMANTIC`, and `CHARACTER` accept comma-separated extensions in forms such as `[txt,pdf]` or `txt,pdf`. An extension should appear in only one splitter. Unmatched extensions use the default splitter.

To use a local embedding model, set `IS_USE_LOCAL=True` and point `EMBEDDINGS_PATH` to the model directory. The current PDF processor uses `qwen-vl-max-latest`; `VL_MODEL` is reserved and changing it does not currently switch the vision model.

Other optional environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Backend listen address |
| `PORT` | `8000` | Backend listen port |
| `FRONTEND_DIST` | `<project>/frontend/dist` | Frontend build directory; use an absolute path when overriding it |
| `RAG_WORKER_COUNT` | `4` | RAG thread-pool size |
| `CORS_ALLOW_ORIGINS` | `*` | Allowed origins, separated by commas |

### 3. Install Backend Dependencies

With standard `venv`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Or with `uv`:

```bash
uv venv
source .venv/bin/activate
uv pip install -r backend/requirements.txt
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

### 4. Choose a Run Mode

#### Option A: Serve the Built Frontend from FastAPI

Recommended for daily use and single-machine deployments:

```bash
cd frontend
npm ci
npm run build
cd ../backend
python main.py
```

- Web interface: http://localhost:8000
- API documentation: http://localhost:8000/docs
- Health check: http://localhost:8000/health

The backend mounts `frontend/dist` automatically. If it is missing, the API still starts and logs a message asking you to run `npm run build`.

#### Option B: Frontend and Backend Development Servers

Terminal 1:

```bash
cd backend
python main.py
```

Terminal 2:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:8080. Vite proxies browser requests under `/api` to `http://127.0.0.1:8000`.

When the frontend and backend are not behind the same site, set the frontend API address:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

## Docker Deployment

Create and review `backend/.env`, then run from the repository root:

```bash
docker compose up --build
```

To run in the background:

```bash
docker compose up -d --build
```

Docker Compose uses a separate Nginx frontend container:

- Web interface: http://localhost:8080
- Backend API: http://localhost:8000
- API documentation: http://localhost:8000/docs

The backend image downloads `BAAI/bge-base-zh` and `BAAI/bge-reranker-base`, so the first build can take some time. Compose mounts `backend/` at `/app`; runtime data is stored on the host under `backend/uploads`, `backend/txt_files`, `backend/results`, and `backend/chroma_data`.

To use the models preloaded in the image:

```dotenv
IS_USE_LOCAL=True
EMBEDDINGS_PATH=/app/models/bge-base-zh
RERANK_MODEL=/app/models/bge-reranker-base
```

## Security

The project does not include built-in user login or API authentication. Do not expose the backend port directly to an untrusted public network.

- For local-only use, set `HOST=127.0.0.1`.
- For LAN or public deployment, use an authenticated HTTPS reverse proxy.
- Restrict `CORS_ALLOW_ORIGINS` to the actual frontend origins instead of using a wildcard publicly.
- Do not commit `backend/.env`, logs, uploaded files, or knowledge-base data.
- The AI connection test sends only a fixed minimal message and never sends uploaded document content.

## Usage

### Configure an AI Model

1. Start the application and open the settings panel.
2. Enter the Base URL, API key, and model name of an OpenAI-compatible service.
3. Configure temperature and thinking mode as supported by the service.
4. Select **Test Connection**. The test sends a minimal request without saving the configuration.
5. After the test succeeds, select **Save AI Configuration**. New graph extraction and RAG requests use it immediately.

Runtime settings are stored only in backend memory and are reloaded from `backend/.env` after a restart. The backend returns only whether an API key exists and a masked hint, never the complete key. Leave the key field empty to retain an existing key during a save or test.

### Select a Note Type

- **General**: Uses the general processing template for the active prompt version.
- **Story**: Uses graph-processing prompts designed for narrative content.
- **Custom**: Allows independent prompts for entity extraction, relationship extraction, and knowledge fusion.

The general prompts initialize a custom type the first time it is selected. Restoring general prompts reloads the templates for the active `PROMPTVISION`. Each custom prompt is limited to 30,000 characters, stored in browser local storage, and submitted with uploads without changing server templates.

### Upload and Reprocess Files

1. Select a note type; enable PDF image recognition when processing scanned PDFs or image content.
2. Click or drag a `.txt`, `.md`, or `.pdf` file into the upload area.
3. Follow the processing state and chunk progress in the file list.
4. Select the completed file to open the result workspace.

Use the file context menu to pause processing. The backend stops after finishing and checkpointing the current chunk. Resume later without repeating completed AI requests.

For files with the same name:

- A file with complete text, knowledge-base, and graph data can be updated incrementally.
- A previously failed file is fully rebuilt after residual text, graph, and knowledge-base records are removed.
- A completed file can be exported as `.kmn.zip` from its context menu and restored by dropping it into another instance.
- Incomplete data always triggers a full rebuild.

### View Results

The result workspace contains three panels:

- **Source file**: Switch between Markdown preview and source, copy content, or download the file.
- **Knowledge graph**: Browse nodes, relationships, and weights; large graphs provide community overview and detail pages.
- **RAG Q&A**: Ask questions about the current file, use streaming output and history, or stop an active response.

On desktop, drag the file-list boundary and panel dividers. Panels can also be shown or hidden from the tabs at the top.

### Manage Files and History

For a completed file, you can delete its upload, converted text, graph, and knowledge-base data, or clear only its RAG history. Chat history stored in browser local storage is cleared together with the corresponding delete operation.

### Relationship Weights and Retrieval

Relationship weights range from `0` to `1` and describe importance in the current context. Edge thickness represents this value.

| Parameter | Default | Description |
| --- | --- | --- |
| `top_k` | `1` | Number of vector retrieval results |
| `weight_threshold` | `0.3` | Minimum relationship weight used for Q&A |
| `max_relations` | `20` | Maximum number of relationships used |

## API Overview

See `/docs` on a running backend for complete request and response schemas. The listed routes can be called directly and also support an `/api` prefix through the built frontend, Vite, or Nginx.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `GET` | `/ai-settings` | Read text-model settings without exposing the complete API key |
| `PUT` | `/ai-settings` | Update text-model settings for the current process |
| `POST` | `/ai-settings/test` | Test submitted settings without saving them |
| `GET` | `/processing-prompts/defaults` | Read the current general three-stage processing prompts |
| `POST` | `/upload` | Upload a document for full processing or an incremental update |
| `GET` | `/export-package/{filename}` | Download a portable document and graph package |
| `GET` | `/processing-status/{filename}` | Read state, chunk progress, and estimated remaining time |
| `POST` | `/pause-processing/{filename}` | Pause after the current chunk finishes |
| `POST` | `/resume-processing/{filename}` | Resume from the saved checkpoint |
| `GET` | `/list-files` | List knowledge-base files |
| `GET` | `/file-content/{filename}` | Read converted text |
| `GET` | `/file-entities/{filename}?count=5` | Read primary entities |
| `GET` | `/result/{filename}` | Read the graph home page |
| `GET` | `/result-page/{graph_name}/{page_name}` | Read a graph home or community detail page |
| `DELETE` | `/delete/{filename}` | Delete a file and its related data |
| `DELETE` | `/rag-history/{filename}` | Clear RAG history for a file |
| `POST` | `/create_session` | Create a Q&A session |
| `POST` | `/hybridrag` | Run non-streaming HybridRAG Q&A |
| `POST` | `/hybridrag/stream` | Run SSE streaming HybridRAG Q&A |
| `GET` | `/session_status/{session_id}` | Read session state and queue length |
| `DELETE` | `/session/{session_id}` | Delete an idle session |

`POST /upload` uses `multipart/form-data`:

| Field | Required | Description |
| --- | --- | --- |
| `file` | Yes | A `.txt`, `.md`, or `.pdf` file |
| `noteType` | No | `general`, `story`, or `custom`; defaults to `general` |
| `use_img2txt` | No | Whether to recognize PDF image content |
| `entityPrompt` | Optional for custom | Entity extraction prompt; empty uses the general template |
| `relationshipPrompt` | Optional for custom | Relationship extraction prompt; empty uses the general template |
| `fusionPrompt` | Optional for custom | Knowledge fusion prompt; empty uses the general template |

HybridRAG request example:

```json
{
  "request": "What are the main ideas in this document?",
  "filename": "example.pdf",
  "flow": true,
  "top_k": 3,
  "weight_threshold": 0.3,
  "max_relations": 20,
  "messages": [],
  "session_id": null
}
```

## Data and Directories

```text
KnowledgeMapNotes/
├── backend/
│   ├── main.py                    # FastAPI application entry point
│   ├── KnowledgeGraphManager/     # Graph construction, fusion, and visualization
│   ├── LLM/                       # Model calls and RAG output processing
│   ├── OmniStore/                 # ChromaDB and knowledge-base storage
│   ├── OmniText/                  # PDF and Markdown text extraction
│   ├── TextSlicer/                # Text splitters
│   ├── embedding_tools/           # Embedding and reranking tools
│   ├── prompt/                    # v1/v2 prompt templates
│   ├── uploads/                   # Uploaded source files
│   ├── txt_files/                 # Converted text files
│   ├── results/<document>/        # Graph home and community pages
│   └── chroma_data/               # Persistent ChromaDB data
└── frontend/
    ├── src/                       # Vue 3 application source
    ├── dist/                      # Output generated by npm run build
    ├── vite.config.js             # Development server and API proxy
    └── nginx.conf                 # Docker frontend reverse proxy
```

`uploads`, `txt_files`, `results`, and `chroma_data` form one related runtime data set. Keep them consistent when migrating, restoring, or backing up a knowledge base.

## Douyin Chat JSON to TXT

The repository includes a helper for JSON exported by `douyin-chat-export`:

```bash
python "backend/validation/将抖音聊天转txt.py" chat.json chat.txt
```

Without the second argument it writes `result.txt` in the current directory. It can also read standard input:

```bash
python "backend/validation/将抖音聊天转txt.py" < chat.json
```

The script retains normal messages (`type=0`, excluding `[系统消息]`) and `type=24` messages and writes one `accountName:content` entry per line. The resulting TXT file can be uploaded directly.

## FAQ

### Can the backend start without a Base URL and API key?

Yes. Configure the text model later in the web settings. Model-dependent upload and RAG endpoints return `503` with a clear message until configuration is complete.

### Why can I access the API but not the web interface?

Run `npm run build` in `frontend/` and confirm that `frontend/dist/index.html` exists. Set `FRONTEND_DIST` when using a custom build directory. The backend startup log reports the mounted path or explains that it is missing.

### Why are prompts or `.env` not found when the backend starts?

Prompt and runtime paths are relative to `backend/`. Start the application from that directory:

```bash
cd backend
python main.py
```

You can also run `uvicorn main:app --host 0.0.0.0 --port 8000` from the same directory.

### The AI connection test succeeded. Why did the configuration disappear after restart?

Settings saved in the web interface apply only to the current backend process. Add them to `backend/.env` and restart the backend to persist them.

### Does reuploading a failed file perform an incremental update?

No. Failed-file remnants are removed before a complete rebuild. Incremental updates are offered only when the knowledge base, converted text, and graph are all complete.

### How do I use a local embedding model?

Set `IS_USE_LOCAL=True` and point `EMBEDDINGS_PATH` to the local model directory. `DEVICE=cuda` requires a PyTorch build compatible with the installed CUDA version; otherwise use `DEVICE=cpu`.

### Why was image content not recognized in a scanned PDF?

Enable PDF image recognition in the web settings and verify `VL_API_KEY` and `VL_BASE_URL`. Text-only PDFs normally do not require this option.

### Why does a large graph open multiple pages?

When Louvain finds multiple communities and at least one reaches the pagination threshold, the system generates a cross-community overview and detail pages for larger communities. By default, detail pages are generated for communities with at least 20 nodes. Set `GRAPH_COMMUNITY_MIN_SIZE=1` in `backend/.env` and regenerate the graph to create detail pages for every community; increase it to reduce the number of pages.

### Why did changes to `.env` not take effect?

Environment variables are loaded when the backend starts. Restart the backend after editing the file. With Docker, run `docker compose restart backend`.

## Roadmap

- Supplement local graph answers with online knowledge when needed.
- Improve text chunking and vector/triple fusion.
- Add note fact-checking, review tests, and explanatory video generation.
- Improve private-data redaction and restoration workflows.

## License

This project is open source under the GNU AGPL-3.0 in a dual-license model.

| Use case | Fee | Requirement |
| --- | --- | --- |
| Personal learning, research, and non-commercial use | Free | Comply with AGPL-3.0, publish modifications, and retain copyright notices |
| Derivative work in an open-source project | Free | The derivative work must be released under AGPL-3.0 |
| Internal enterprise tool without distribution | Free | Comply with AGPL-3.0 |
| Closed-source commercial use or packaged sales | Commercial license required | AGPL-3.0 does not permit closed-source distribution |
| SaaS or network service without source disclosure | Commercial license required | AGPL-3.0 requires source availability for network users |
| Integration into proprietary software for redistribution | Commercial license required | Incompatible with AGPL-3.0 copyleft requirements |

In short: personal and open-source use is free. For closed-source sales or SaaS operation without source disclosure, purchase a commercial license.

### Commercial licensing

To obtain a commercial license that is not subject to AGPL-3.0 requirements, contact:

- QQ: `1615242125`
- WeChat: `XKJ1615242125`

See [LICENSE](LICENSE) for the full AGPL-3.0 text and [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md) for the dual-license notice.
