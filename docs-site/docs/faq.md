---
title: 常见问题
description: KnowledgeMapNotes 安装、模型、PDF、图谱和配置问题
---

# 常见问题

## 没有填写模型配置，后端能启动吗？

可以。后端与内置说明仍可使用；上传处理和 RAG 等依赖模型的接口会返回 `503` 和配置提示。

## 为什么只能打开 API，Web 页面是空的？

先在 `frontend/` 运行 `npm run build`，确认 `frontend/dist/index.html` 存在。自定义目录时设置 `FRONTEND_DIST`。

## 为什么启动时找不到提示词或 `.env`？

请从 `backend/` 目录启动：

```bash
cd backend
python main.py
```

## AI 测试成功，重启后为什么丢失？

前端保存的是当前进程运行时配置。需要持久化时，把相同配置写入 `backend/.env` 并重启。

## 失败文件重新上传会做增量更新吗？

不会。只有文档、知识库和图谱结果完整存在时才允许增量更新。失败文件会先清理残留再完整处理。

## 如何使用本地嵌入模型？

设置 `IS_USE_LOCAL=True`，让 `EMBEDDINGS_PATH` 指向模型目录。CUDA 环境还要确保 PyTorch 与本机 CUDA 版本匹配；否则使用 `DEVICE=cpu`。

## 扫描 PDF 为什么没有图片内容？

在前端开启“PDF 图片内容识别”，并检查 `VL_API_KEY` 和 `VL_BASE_URL`。纯文本 PDF 通常不需要视觉模型。

## 为什么大图谱有多个页面？

系统会为较大的 Louvain 社区生成详情页，并保留跨社区总览。通过 `GRAPH_COMMUNITY_MIN_SIZE` 控制详情页的最小社区规模，修改后需重新生成图谱。

## 修改 `.env` 为什么没有生效？

环境变量只在进程启动时加载。普通环境重启后端；Docker 环境执行：

```bash
docker compose restart backend
```

## 可以把服务直接部署到公网吗？

不建议。当前没有内置登录和 API 鉴权。请使用带身份验证和 HTTPS 的反向代理，并限制 CORS 与后端端口访问。
