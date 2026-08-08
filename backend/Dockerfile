ARG BASE_REGISTRY=docker.m.daocloud.io/library

FROM ${BASE_REGISTRY}/python:3.12-slim

ARG PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG TORCH_FIND_LINKS=https://mirrors.aliyun.com/pytorch-wheels/cpu/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install modelscope --index-url "${PYPI_INDEX}" \
    && python -m pip install 'torch==2.6.0+cpu' --find-links "${TORCH_FIND_LINKS}" \
    && python -m pip install -r requirements.txt --index-url "${PYPI_INDEX}"
RUN modelscope download BAAI/bge-base-zh \
    --local_dir /app/models/bge-base-zh \
    --exclude '*.bin' '*.onnx'
RUN modelscope download BAAI/bge-reranker-base \
    --local_dir /app/models/bge-reranker-base \
    --exclude '*.bin' '*.onnx'

# 复制应用代码
COPY . .

RUN mkdir -p /app/chroma_data /app/uploads /app/txt_files /app/results /app/processing_states /app/graph_history

# 暴露端口
EXPOSE 8000

# 启动应用
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
