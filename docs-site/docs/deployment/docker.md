---
title: Docker 部署
description: 使用 Docker Compose 构建并运行 KnowledgeMapNotes
---

# Docker 部署

## 准备配置

```bash
cp backend/.env.example backend/.env
```

检查模型、数据目录和设备配置。CPU 环境使用：

```dotenv
DEVICE=cpu
```

## 启动

```bash
docker compose up --build
```

后台运行：

```bash
docker compose up -d --build
```

| 服务 | 地址 |
| --- | --- |
| Web 应用 | `http://localhost:8080` |
| 后端 API | `http://localhost:8000` |
| OpenAPI | `http://localhost:8000/docs` |

Compose 使用独立 Nginx 前端容器，并把 `backend/` 挂载到容器 `/app`。运行数据保存在宿主机的后端目录中。

## 镜像内模型

后端镜像构建时会下载 `BAAI/bge-base-zh` 与 `BAAI/bge-reranker-base`。使用镜像内预下载模型：

```dotenv
IS_USE_LOCAL=True
EMBEDDINGS_PATH=/app/models/bge-base-zh
RERANK_MODEL=/app/models/bge-reranker-base
```

## 修改配置

环境变量在启动时读取。修改 `backend/.env` 后重启后端：

```bash
docker compose restart backend
```
