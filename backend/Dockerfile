ARG BASE_REGISTRY=docker.m.daocloud.io/library

FROM ${BASE_REGISTRY}/python:3.12-slim

ARG PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PYPI_FALLBACK_INDEX=https://pypi.org/simple
ARG TORCH_FIND_LINKS=https://mirrors.aliyun.com/pytorch-wheels/cpu/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    HF_ENDPOINT=https://huggingface.co

WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install modelscope \
        --index-url "${PYPI_INDEX}" \
        --extra-index-url "${PYPI_FALLBACK_INDEX}" \
    && python -m pip install 'torch==2.6.0+cpu' --find-links "${TORCH_FIND_LINKS}" \
    && python -m pip install -r requirements.txt \
        --index-url "${PYPI_INDEX}" \
        --extra-index-url "${PYPI_FALLBACK_INDEX}"
RUN modelscope download BAAI/bge-base-zh \
    --local_dir /app/models/bge-base-zh \
    --exclude '*.bin' '*.onnx'
RUN modelscope download BAAI/bge-reranker-base \
    --local_dir /app/models/bge-reranker-base \
    --exclude '*.bin' '*.onnx'

# 复制应用代码
COPY . .

# Catch a truncated archive, text/LFS pointer, or invalid manifest before
# publishing the image.
RUN python -c "from pathlib import Path; from transfer_package import read_transfer_package; p=Path('default_examples/本软件使用说明.kmn.zip'); assert p.is_file(), f'Missing bundled default example: {p}'; read_transfer_package(p.read_bytes())"

RUN mkdir -p /app/chroma_data /app/uploads /app/txt_files /app/results /app/processing_states /app/graph_history

# 暴露端口
EXPOSE 8000

# 启动应用
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
