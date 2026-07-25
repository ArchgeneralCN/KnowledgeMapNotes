# syntax=docker/dockerfile:1

# Build the Vue frontend.
FROM node:18-alpine AS frontend-build

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# Build a single production image in which FastAPI also serves the frontend.
FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    HOST=0.0.0.0 \
    PORT=7860 \
    FRONTEND_DIST=/app/frontend/dist \
    PROMPTVISION=v1 \
    IS_USE_LOCAL=True \
    EMBEDDINGS=BAAI/bge-base-zh \
    EMBEDDINGS_PATH=/app/models/bge-base-zh \
    RERANK_MODEL=/app/models/bge-reranker-base \
    DEVICE=cpu \
    SIMPLE="[txt,pdf]" \
    SEMANTIC="" \
    CHARACTER="[md]" \
    CHROMADB_PATH=/app/backend/chroma_data \
    UPLOAD_FOLDER=/app/backend/uploads \
    TXT_FOLDER=/app/backend/txt_files \
    RESULT_FOLDER=/app/backend/results

WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt

# Cache the Python dependencies and local models in layers that are not
# invalidated when only application source files change.
RUN python -m pip install --upgrade pip \
    && python -m pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple \
    && python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple \
    && modelscope download --model BAAI/bge-base-zh --local_dir /app/models/bge-base-zh \
    && modelscope download --model BAAI/bge-reranker-base --local_dir /app/models/bge-reranker-base

COPY backend/ ./
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

RUN mkdir -p \
    /app/backend/chroma_data \
    /app/backend/uploads \
    /app/backend/txt_files \
    /app/backend/results

EXPOSE 7860

CMD ["python", "main.py"]
