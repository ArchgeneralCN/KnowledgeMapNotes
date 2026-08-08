---
title: HTTP API
description: KnowledgeMapNotes 核心 HTTP API 参考
---

# HTTP API

完整请求模型和在线调试请打开运行实例的 `/docs`。路径可直接调用；通过打包前端、Vite 或 Nginx 访问时也支持 `/api` 前缀。

## 系统与模型

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/ai-settings` | 获取文本模型配置，不返回完整密钥 |
| `PUT` | `/ai-settings` | 更新当前进程配置 |
| `POST` | `/ai-settings/test` | 测试提交的配置，不保存 |
| `GET` | `/processing-prompts/defaults` | 获取通用三阶段提示词 |

## 文件与处理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/upload` | 上传文档，开始完整处理或增量更新 |
| `GET` | `/processing-status/{filename}` | 查询进度与预计剩余时间 |
| `POST` | `/pause-processing/{filename}` | 在当前文本块结束后暂停 |
| `POST` | `/resume-processing/{filename}` | 从检查点恢复 |
| `GET` | `/list-files` | 获取文件列表 |
| `GET` | `/file-content/{filename}` | 获取转换后的文本 |
| `GET` | `/file-entities/{filename}?count=5` | 获取主要实体 |
| `DELETE` | `/delete/{filename}` | 删除文件及关联知识库数据 |
| `GET` | `/export-package/{filename}` | 导出 `.kmn.zip` 迁移包 |

### 上传字段

`POST /upload` 使用 `multipart/form-data`：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file` | 是 | `.txt`、`.md`、`.pdf` 或迁移包 |
| `noteType` | 否 | `general`、`story` 或 `custom` |
| `use_img2txt` | 否 | 是否识别 PDF 图片 |
| `entityPrompt` | 否 | 自定义实体抽取提示词 |
| `relationshipPrompt` | 否 | 自定义关系抽取提示词 |
| `fusionPrompt` | 否 | 自定义知识融合提示词 |

## 图谱

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/result/{filename}` | 获取图谱主页 |
| `GET` | `/result-page/{graph_name}/{page_name}` | 获取主页或社区详情页 |

图谱编辑、历史与原文定位接口以运行实例的 OpenAPI 为准。

## RAG 会话

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/create_session` | 创建问答会话 |
| `POST` | `/hybridrag` | 非流式问答 |
| `POST` | `/hybridrag/stream` | SSE 流式问答 |
| `GET` | `/session_status/{session_id}` | 查询状态和队列长度 |
| `DELETE` | `/session/{session_id}` | 删除空闲会话 |
| `DELETE` | `/rag-history/{filename}` | 清理指定文件的 RAG 历史 |

## 文件路径编码

文件名和图谱名作为路径参数时必须进行 URL 编码，尤其是中文、空格、`#` 和斜杠等字符。前端已统一使用路径编码辅助函数；自定义客户端也应采用等价处理。
