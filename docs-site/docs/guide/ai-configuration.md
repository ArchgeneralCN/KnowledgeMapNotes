---
title: 配置 AI 模型
description: 配置主模型、备用模型、视觉模型与处理提示词
---

# 配置 AI 模型

KnowledgeMapNotes 使用 OpenAI 兼容接口完成实体抽取、关系抽取、知识融合和 RAG 问答。后端可以在未配置文本模型时启动，但相关能力会返回明确提示。

## 主模型

在“设置 → AI 模型设置”中填写：

| 字段 | 说明 |
| --- | --- |
| Base URL | 兼容服务地址，必须以 `http://` 或 `https://` 开头，通常包含 `/v1` |
| API Key | 服务密钥，已保存的值只显示脱敏提示 |
| 模型名称 | 服务商提供的真实模型标识，例如 `qwen-plus` |
| 温度 | `0` 到 `2`；结构化抽取建议使用较低值 |
| 思考模式 | 仅在模型支持对应参数时开启 |

先执行“测试连接”，成功后再保存。测试仅发送最小请求，不会保存表单，也不会上传知识库内容。

## 备用模型

开启“备用 AI 自动接管”后填写第二套 Base URL、API Key 和模型名称。当主模型请求失败、超时或返回无效 JSON 时，系统会用备用模型继续当前文本块。

## 持久化配置

前端修改只作用于当前后端进程。长期使用应把配置写入 `backend/.env`：

```dotenv
BASE_URL=https://example.com/v1
API_KEY=replace-with-your-key
MODEL_NAME=qwen-plus
TEMPERATURE=0
ENABLE_THINKING=False
AI_MAX_OUTPUT_TOKENS=8192
AI_MAX_OUTPUT_PARAMETER=max_tokens

FALLBACK_ENABLED=False
FALLBACK_BASE_URL=
FALLBACK_API_KEY=
FALLBACK_MODEL_NAME=
```

## PDF 图片识别

扫描件或包含重要图片的 PDF 可以启用图片内容识别：

```dotenv
VL_API_KEY=replace-with-your-key
VL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VL_MODEL=qwen-vl-max-latest
```

上传 PDF 前在图谱构建设置中开启“PDF 图片内容识别”。纯文本 PDF 通常无需开启，以免增加时间和调用费用。

## 笔记类型与提示词

- **通用**：适合技术资料、普通笔记和综合内容。
- **故事**：更关注人物、地点、事件与情节关系。
- **自定义**：分别编辑实体抽取、关系抽取和知识融合提示词。

自定义提示词随当前上传请求提交，不会自动重处理已经完成的文件。

## 嵌入与重排

在线模型：

```dotenv
IS_USE_LOCAL=False
EMBEDDINGS=BAAI/bge-base-zh
RERANK_MODEL=BAAI/bge-reranker-base
DEVICE=cpu
```

本地模型：

```dotenv
IS_USE_LOCAL=True
EMBEDDINGS_PATH=/absolute/path/to/bge-base-zh
RERANK_MODEL=/absolute/path/to/bge-reranker-base
DEVICE=cuda
```

`DEVICE=cuda` 要求 PyTorch 与 CUDA 版本匹配，否则请使用 `cpu`。
