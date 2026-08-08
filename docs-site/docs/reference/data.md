---
title: 数据目录
description: KnowledgeMapNotes 的运行数据、备份边界和目录结构
---

# 数据目录

## 主要结构

```text
KnowledgeMapNotes/
├── backend/
│   ├── uploads/                 # 上传的原始文件
│   ├── txt_files/               # 转换后的文本
│   ├── results/<文档名>/        # 图谱主页和社区页
│   ├── chroma_data/             # ChromaDB 持久化数据
│   ├── processing_states/       # 任务状态与检查点
│   ├── graph_history/           # 图谱与文档联合历史
│   ├── default_examples/        # 首次部署的内置示例
│   └── kmnzips/                 # 可选迁移包
├── frontend/
│   ├── src/                     # Vue 应用源码
│   └── dist/                    # 前端构建产物
└── docs-site/                   # 本文档站源码
```

## 一致性边界

原始文件、转换文本、向量集合、处理状态和图谱 HTML 互相关联。整体备份时应在服务停止或数据静止时复制，避免不同目录来自不同处理阶段。

## 默认示例

首次部署默认导入 `backend/default_examples/本软件使用说明.kmn.zip`。它已经处理完成，不调用文本 AI，也不会覆盖同名用户数据。

`backend/kmnzips` 中的其他迁移包不会自动导入，需要在上传页手动选择。设置 `DEFAULT_EXAMPLES_ENABLED=False` 可创建空白实例。
