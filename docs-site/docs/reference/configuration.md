---
title: 环境变量
description: 后端、模型、图谱、存储和前端环境变量参考
---

# 环境变量

配置文件位于 `backend/.env`。修改后需重启后端进程。

## 服务

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | 后端监听地址 |
| `PORT` | `8000` | 后端监听端口 |
| `FRONTEND_DIST` | `frontend/dist` | 前端构建产物目录 |
| `CORS_ALLOW_ORIGINS` | `*` | 允许的来源，多个值以逗号分隔 |
| `RAG_WORKER_COUNT` | `4` | RAG 线程池大小 |

## 文本模型

| 变量 | 示例 | 说明 |
| --- | --- | --- |
| `BASE_URL` | `https://example.com/v1` | OpenAI 兼容 API 地址 |
| `API_KEY` | - | 主模型密钥 |
| `MODEL_NAME` | `qwen-plus` | 主模型名称 |
| `TEMPERATURE` | `0` | 生成温度 |
| `ENABLE_THINKING` | `False` | 是否请求思考模式 |
| `AI_MAX_OUTPUT_TOKENS` | `8192` | 最大输出 token |
| `AI_MAX_OUTPUT_PARAMETER` | `max_tokens` | 服务商使用的 token 参数名 |
| `PROMPTVISION` | `v1` | 提示词版本；`v2` 更充分但更慢 |

## 备用模型

| 变量 | 说明 |
| --- | --- |
| `FALLBACK_ENABLED` | 是否启用自动接管 |
| `FALLBACK_BASE_URL` | 备用 API 地址 |
| `FALLBACK_API_KEY` | 备用 API 密钥 |
| `FALLBACK_MODEL_NAME` | 备用模型名称 |

## 嵌入、重排与分块

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `IS_USE_LOCAL` | `False` | 是否使用本地嵌入模型目录 |
| `EMBEDDINGS` | `BAAI/bge-base-zh` | 在线嵌入模型 |
| `EMBEDDINGS_PATH` | - | 本地嵌入模型绝对路径 |
| `RERANK_MODEL` | `BAAI/bge-reranker-base` | 重排模型名或路径 |
| `DEVICE` | 依环境 | `cpu` 或 `cuda` |
| `SIMPLE` | `[txt,pdf]` | 简单分割器扩展名 |
| `SEMANTIC` | `[]` | 语义分割器扩展名 |
| `CHARACTER` | `[md]` | 字符分割器扩展名 |

## 数据目录

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CHROMADB_PATH` | `./chroma_data` | ChromaDB 持久化目录 |
| `UPLOAD_FOLDER` | `uploads` | 原始上传文件 |
| `TXT_FOLDER` | `txt_files` | 转换后的文本 |
| `RESULT_FOLDER` | `results` | 图谱 HTML 结果 |
| `DEFAULT_EXAMPLES_ENABLED` | `True` | 首次启动导入内置使用说明 |

更多处理批次参数请参考仓库中的 `backend/.env.example`，该文件是当前代码支持项的最终依据。
