---
title: 本地部署
description: 单进程和开发模式部署 KnowledgeMapNotes
---

# 本地部署

## 推荐：后端托管前端

这种方式只有一个对外端口，适合个人电脑和局域网服务。

```bash
cd frontend
npm ci
npm run build

cd ../backend
python main.py
```

默认监听 `0.0.0.0:8000`。如果只允许本机访问，在 `backend/.env` 中设置：

```dotenv
HOST=127.0.0.1
PORT=8000
```

如前端构建产物不在默认位置，设置绝对路径：

```dotenv
FRONTEND_DIST=/absolute/path/to/frontend/dist
```

## 开发模式

后端：

```bash
cd backend
python main.py
```

前端：

```bash
cd frontend
npm run dev
```

开发服务器监听 `8080`，并把 `/api` 转发至 `8000`。

## 进程资源

CPU 环境建议：

```dotenv
DEVICE=cpu
RAG_WORKER_COUNT=4
```

首次运行可能需要下载嵌入和重排模型。生产环境或离线环境建议预先下载并配置本地路径。
