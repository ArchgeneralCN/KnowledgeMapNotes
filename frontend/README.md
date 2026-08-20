# KnowledgeMapNotes Frontend

The active frontend is a React 19 application built with Vite. The entry point is `src/main.jsx`; the retired Vue implementation has been removed.

## Development

```bash
npm ci
npm run dev
```

The development server listens on `http://127.0.0.1:8080` and proxies `/api` to `http://127.0.0.1:8000`.

## Production Build

```bash
npm run build
```

Vite writes the static application to `frontend/dist`. The FastAPI application mounts this directory automatically when it exists.

Large source documents are split into render chunks in `OriginalDocumentPanel.jsx`. Only the initial chunks are rendered immediately; later chunks are appended near the scroll boundary. Full-document evidence highlighting uses a viewport window so off-screen text does not keep expensive highlight markup mounted.
