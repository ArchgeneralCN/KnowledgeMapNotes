---
title: 快速开始
description: 用最短路径运行 KnowledgeMapNotes 并创建第一张知识图谱
---

# 快速开始

KnowledgeMapNotes 会把 TXT、Markdown 和 PDF 文档转换为知识图谱，并结合向量检索、实体关系与图谱社区完成 HybridRAG 问答。本页给出从启动到第一次探索图谱的最短路径。

## 运行条件

- Python 3.10+
- Node.js 18+
- 一个 OpenAI API 兼容的文本模型
- 可选 CUDA GPU；CPU 环境使用 `DEVICE=cpu`

::: tip 无模型也能先体验
首次部署会自动导入已经处理好的“本软件使用说明”。它不调用 AI，可以直接查看文档、知识图谱和出处定位。新的 RAG 问答仍需配置模型。
:::

## 1. 获取代码

```bash
git clone https://github.com/Xikcn/KnowledgeMapNotes.git
cd KnowledgeMapNotes
cp backend/.env.example backend/.env
```

## 2. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cd frontend
npm ci
npm run build
```

Windows PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活虚拟环境。

## 3. 启动应用

前端构建后可由 FastAPI 直接托管：

```bash
cd ../backend
python main.py
```

打开以下地址：

| 服务 | 地址 |
| --- | --- |
| Web 应用 | `http://localhost:8000` |
| API 文档 | `http://localhost:8000/docs` |
| 健康检查 | `http://localhost:8000/health` |

## 4. 配置 AI

1. 打开左侧导航底部的“设置”。
2. 填写 Base URL、API Key 和模型名称。
3. 点击“测试连接”，确认请求成功及延迟。
4. 点击“保存 AI 配置”。

前端保存的是当前后端进程的运行时配置。需要重启后继续生效时，请把相同配置写入 `backend/.env`。详见[配置 AI 模型](/guide/ai-configuration)。

## 5. 导入第一份文档

返回上传页，将 `.txt`、`.md`、`.pdf` 或 `.kmn.zip` 文件拖入上传区域。普通文档会依次经历：

```text
上传 -> 文本提取 -> 分块 -> 实体抽取 -> 关系抽取 -> 知识融合 -> 图谱生成
```

处理完成后，双击文件卡片进入结果工作区。你可以并排打开文档内容、知识图谱和 RAG 问答。

## 接下来

- [创建第一张图谱](/guide/first-graph)：掌握节点、关系和原文定位
- [知识图谱](/features/knowledge-graph)：了解社区视图与图谱编辑
- [HybridRAG 问答](/features/hybrid-rag)：调整检索范围与证据来源
- [Docker 部署](/deployment/docker)：通过容器运行前后端
