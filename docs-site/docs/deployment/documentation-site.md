---
title: 文档站安装与 Docker 部署
description: 使用 npm、本地预览或 Docker Compose 安装 KnowledgeMapNotes 文档站
---

# 文档站安装与 Docker 部署

文档站是独立的 VitePress 静态站点，不需要启动 FastAPI。开发时使用 Node.js，生产环境推荐构建成静态文件后由 Nginx 或其他静态服务器托管。

## 环境要求

- Node.js 18 或更高版本
- npm 9 或更高版本
- Docker 24 或更高版本，以及 Docker Compose v2

## npm 安装

在仓库根目录执行：

```bash
cd docs-site
npm ci
npm run dev
```

打开 `http://localhost:5173/`。开发服务器启动前会自动同步 `backend/results/` 中的图谱；如果该目录不存在，则保留仓库中已经提交的示例页面，并从 `covers/` 更新封面。

生产构建和本地预览：

```bash
npm run build
npm run preview
```

构建结果位于 `docs/.vitepress/dist/`，预览地址通常为 `http://localhost:4173/`。

## Docker Compose

在 `docs-site/` 目录执行：

```bash
docker compose up -d --build
```

默认访问 `http://localhost:4173/`。修改宿主机端口：

```bash
DOCS_PORT=8088 docker compose up -d --build
```

查看状态和日志：

```bash
docker compose ps
docker compose logs -f docs-site
```

停止并删除容器：

```bash
docker compose down
```

Compose 使用 `Dockerfile` 的多阶段构建：第一阶段运行 `npm ci` 和 `npm run build`，第二阶段只保留 Nginx 和静态产物。图谱 HTML、社区页面、封面和本地 vis-network 资源都会一起进入镜像，不需要挂载宿主机目录。

## 单独构建镜像

```bash
docker build -t knowledgemapnotes-docs:latest .
docker run --rm -p 4173:80 knowledgemapnotes-docs:latest
```

验证首页、健康检查和一个图谱入口：

```bash
curl -I http://localhost:4173/
curl -fsS http://localhost:4173/healthz
curl -I http://localhost:4173/examples/graph-0761dd98984f/index.html
```

健康检查返回 `ok` 后再接入反向代理或容器编排平台。

## 更新内容

修改 Markdown、主题代码或 `covers/` 后重新构建镜像：

```bash
docker compose build --no-cache docs-site
docker compose up -d docs-site
```

新增图谱时，需要把结果放入 `backend/results/<图谱名称>/`，把封面放入 `covers/`，然后在仓库根目录的 `docs-site/` 中重新构建。部署镜像不依赖运行时的后端数据目录。

## 子路径部署

如果文档站部署在 `https://example.com/knowledge/`，需要在 `docs/.vitepress/config.mjs` 中设置对应的 VitePress `base`，重新构建镜像，并让反向代理把 `/knowledge/` 转发到容器的 80 端口。根路径部署不需要额外配置。
