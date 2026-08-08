# syntax=docker/dockerfile:1

ARG BASE_REGISTRY=docker.m.daocloud.io/library

# Build the Vue frontend.
FROM ${BASE_REGISTRY}/node:18-alpine AS frontend-build

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# Build a single production image in which FastAPI also serves the frontend.
FROM ${BASE_REGISTRY}/python:3.12-slim AS production

ARG PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG TORCH_FIND_LINKS=https://mirrors.aliyun.com/pytorch-wheels/cpu/

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
    && python -m pip install modelscope --index-url "${PYPI_INDEX}" \
    && python -m pip install 'torch==2.6.0+cpu' --find-links "${TORCH_FIND_LINKS}" \
    && python -m pip install -r requirements.txt --index-url "${PYPI_INDEX}" \
    && modelscope download BAAI/bge-base-zh \
        --local_dir /app/models/bge-base-zh \
        --exclude '*.bin' '*.onnx' \
    && modelscope download BAAI/bge-reranker-base \
        --local_dir /app/models/bge-reranker-base \
        --exclude '*.bin' '*.onnx'

COPY backend/ ./
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

# Catch a truncated archive, text/LFS pointer, or invalid manifest before
# publishing the image.
RUN python -c "from pathlib import Path; from transfer_package import read_transfer_package; p=Path('default_examples/本软件使用说明.kmn.zip'); assert p.is_file(), f'Missing bundled default example: {p}'; read_transfer_package(p.read_bytes())"

RUN mkdir -p \
    /app/backend/chroma_data \
    /app/backend/uploads \
    /app/backend/txt_files \
    /app/backend/results

EXPOSE 7860

CMD ["python", "main.py"]
