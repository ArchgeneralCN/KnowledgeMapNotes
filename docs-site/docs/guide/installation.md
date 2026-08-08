---
title: 安装与运行
description: KnowledgeMapNotes 的本地安装、构建和开发模式
---

# 安装与运行

## 后端环境

创建虚拟环境并安装依赖：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

也可以使用 `uv`：

```bash
uv venv
source .venv/bin/activate
uv pip install -r backend/requirements.txt
```

首次加载嵌入与重排模型需要一定磁盘空间。在线加载 Hugging Face 模型时需要网络连接；离线环境可在 `.env` 中指定本地模型路径。

## 单进程模式

适合日常使用和单机部署。先构建 Vue 前端：

```bash
cd frontend
npm ci
npm run build
```

再从 `backend/` 启动服务：

```bash
cd ../backend
python main.py
```

FastAPI 会挂载 `frontend/dist`，Web 应用与 API 共用 `8000` 端口。

::: warning 启动目录
后端提示词和部分运行目录使用相对路径，请从 `backend/` 目录执行 `python main.py`。
:::

## 前后端开发模式

终端一：

```bash
cd backend
python main.py
```

终端二：

```bash
cd frontend
npm ci
npm run dev
```

访问 `http://localhost:8080`。Vite 会把 `/api` 请求代理至 `http://127.0.0.1:8000`。

若前后端不通过同一站点代理，可设置：

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

## 验证安装

```bash
curl http://localhost:8000/health
```

浏览器能打开 Web 页面且健康检查返回成功，即代表基础安装完成。普通文档建图前还需完成[模型配置](/guide/ai-configuration)。
