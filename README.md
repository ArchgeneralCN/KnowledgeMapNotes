# KnowledgeMapNotes

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Xikcn/KnowledgeMapNotes)

KnowledgeMapNotes 是一个基于知识图谱的笔记系统。它可以将 TXT、Markdown 和 PDF 文档转换为知识图谱，并结合向量检索、实体关系和图谱社区信息完成 HybridRAG 问答。

项目提供 Vue 3 Web 界面和 FastAPI 后端，支持文档增量更新、分块处理进度、大规模图谱社区分页、流式问答及运行时 AI 配置。

## 项目展示

https://github.com/user-attachments/assets/5e9e6ffd-4e18-4915-b3a4-85198eb8bb0f

## 功能概览

- **多格式文档处理**：支持 `.txt`、`.md` 和 `.pdf`，PDF 可选用视觉模型提取图片内容。
- **知识图谱构建**：自动完成实体抽取、关系抽取、关系权重计算和知识融合。
- **可控处理提示词**：提供通用、故事和自定义笔记类型；自定义类型可分别编辑实体抽取、关系抽取和知识融合提示词。
- **可靠的文件更新**：已完成的同名文件可增量更新；上次处理失败的同名文件会清理残留数据并重新完整处理。
- **处理进度跟踪**：展示上传、处理、增量更新、完成和失败状态，以及分块数、百分比、单块耗时和预计剩余时间。
- **HybridRAG 问答**：结合向量召回、实体识别和图谱社区信息，支持普通响应、SSE 流式响应、停止生成和历史上下文。
- **图谱可视化**：支持节点与关系检索、高亮、边权重展示，以及大图谱的 Louvain 社区总览和详情页。
- **知识库管理**：支持文件搜索与筛选、原文预览与下载、主要实体查看、删除文件和单独清理 RAG 历史。
- **断点处理**：图谱构建按文本块保存检查点，可暂停任务并从上次完成位置继续处理。
- **故障自动接管**：主 AI 请求失败或返回无效 JSON 时，自动切换到备用 AI 继续当前文本块。
- **图谱迁移包**：已完成文件可导出 `.kmn.zip`，包含原始文档、图谱页面、处理状态和 RAG 历史；拖拽到另一系统即可恢复，不重新调用 AI。
- **开箱即用示例**：首次部署会自动导入已完成处理的“三国志”，无需配置文本 AI 即可浏览原文和完整知识图谱。
- **灵活的结果工作区**：原文、知识图谱和 RAG 面板可并排查看、隐藏或拖动调整宽度。
- **运行时 AI 配置**：后端无需预先填写文本模型 Base URL 和 API Key；启动后可在前端填写、测试连接并保存到当前进程。
- **单进程运行**：FastAPI 可直接托管 `frontend/dist`，构建前端后只需启动后端即可使用完整 Web 应用。

## 最近更新

- 后端允许在未配置文本模型时启动，模型相关操作会提示先在前端完成设置。
- AI 设置新增连通性测试，测试请求不会保存配置，并返回请求延迟。
- 新增自定义笔记类型和三阶段处理提示词编辑器，默认载入通用提示词。
- 修复失败文件重新上传时错误触发增量更新的问题；失败任务残留会在重试前清理。
- 修复前端 AI 配置错误提示、设置面板滚动条及文件操作图标显示问题。
- 加强前端内容安全：Markdown 禁止原始 HTML 并经过 DOMPurify 清理，外部链接使用安全属性，文件路径参数统一编码。
- 更新前端依赖并替换旧 SVG 加载方案，当前 `npm audit` 无已知漏洞。
- 后端新增前端静态资源托管、SPA 路由回退和 `/api` 前缀兼容。

## 待更新计划

- 新增通过图对各个笔记间建立宏观联系图（寻找公共知识）
- 支持用户自主新增、删除和修改节点与关系
- 对 RAG 问答使用到的节点和关系进行高亮定位
- 允许在线编辑笔记文件，并支持同步更新图谱等内容
- 新增历史版本控制功能

## 技术栈

| 范围 | 技术 |
| --- | --- |
| 后端 | FastAPI、OpenAI Python SDK、ChromaDB、SentenceTransformers |
| 图谱 | NetworkX、PyVis、Louvain Community Detection |
| 前端 | Vue 3、Vite、Element Plus、Axios |
| 内容渲染 | Markdown-It、DOMPurify |
| 部署 | FastAPI 静态托管、Docker Compose、Nginx |

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+，构建或开发前端时需要
- 文本模型 API，使用图谱构建和 RAG 功能时需要，后端启动时可暂不配置
- CUDA GPU，可选；CPU 环境请使用 `DEVICE=cpu`

首次启动会加载嵌入和重排模型，需要一定的磁盘空间。在线加载 Hugging Face 模型时还需要网络连接。

首次部署还会从 `backend/default_examples` 自动导入已完成处理的“三国志”示例，不会调用文本 AI，也不会覆盖任何同名数据。如需空白实例，可在 `backend/.env` 中设置 `DEFAULT_EXAMPLES_ENABLED=False`。

### 1. 克隆项目

```bash
git clone https://github.com/Xikcn/KnowledgeMapNotes.git
cd KnowledgeMapNotes
```

### 2. 创建后端配置

```bash
cp backend/.env.example backend/.env
```

不要将包含真实密钥的 `backend/.env` 提交到版本库。

文本模型配置可以暂时留空，后端仍能启动。启动后进入 Web 界面的“设置 -> AI 模型设置”，填写 Base URL、API Key 和模型名称，然后先执行“测试连接”，成功后再保存。

一个适合 CPU 和在线模型加载的配置示例：

```dotenv
# 提示词版本：v1 较快；v2 效果更好但处理时间更长
PROMPTVISION=v1

# OpenAI 兼容文本模型，可留空并在前端设置
BASE_URL=
API_KEY=
MODEL_NAME=
TEMPERATURE=0
ENABLE_THINKING=False
AI_MAX_OUTPUT_TOKENS=8192
AI_MAX_OUTPUT_PARAMETER=max_tokens
RELATION_TEXT_BATCH_CHARS=2000
RELATION_SOURCE_BATCH_SIZE=20
RELATION_MAX_SPLIT_DEPTH=10
FALLBACK_ENABLED=False
FALLBACK_BASE_URL=
FALLBACK_API_KEY=
FALLBACK_MODEL_NAME=
DEFAULT_EXAMPLES_ENABLED=True

# PDF 图片内容识别，可选
VL_API_KEY=
VL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VL_MODEL=qwen-vl-max-latest

# 嵌入与重排模型
IS_USE_LOCAL=False
EMBEDDINGS=BAAI/bge-base-zh
EMBEDDINGS_PATH=/absolute/path/to/bge-base-zh
RERANK_MODEL=BAAI/bge-reranker-base
DEVICE=cpu

# 文本分割器
SIMPLE=[txt,pdf]
SEMANTIC=[]
CHARACTER=[md]

# 运行数据目录，相对于 backend/
CHROMADB_PATH=./chroma_data
UPLOAD_FOLDER=uploads
TXT_FOLDER=txt_files
RESULT_FOLDER=results
```

`SIMPLE`、`SEMANTIC` 和 `CHARACTER` 接收逗号分隔的扩展名，可以写成 `[txt,pdf]` 或 `txt,pdf`。同一个扩展名应只配置在一种分割器中；未匹配到的扩展名会回退到默认分割器。

使用本地嵌入模型时，将 `IS_USE_LOCAL=True`，并让 `EMBEDDINGS_PATH` 指向模型目录。当前 PDF 处理器使用 `qwen-vl-max-latest`；`VL_MODEL` 暂时作为预留配置，修改它不会切换视觉模型。

其他可选环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | 后端监听地址 |
| `PORT` | `8000` | 后端监听端口 |
| `FRONTEND_DIST` | `<项目目录>/frontend/dist` | 前端构建产物目录，建议使用绝对路径覆盖 |
| `RAG_WORKER_COUNT` | `4` | RAG 线程池大小 |
| `CORS_ALLOW_ORIGINS` | `*` | 允许的来源，多个来源用逗号分隔 |

### 3. 安装后端依赖

使用标准 `venv`：

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

Windows PowerShell 激活命令为：

```powershell
.venv\Scripts\Activate.ps1
```

### 4. 选择运行方式

#### 方式一：后端托管打包前端

适合日常使用和单机部署。先构建前端，再启动后端：

```bash
cd frontend
npm ci
npm run build
cd ../backend
python main.py
```

访问地址：

- Web 界面：http://localhost:8000
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

后端会自动挂载 `frontend/dist`。如果目录不存在，后端仍会启动并提供 API，同时在日志中提示先运行 `npm run build`。

#### 方式二：前后端开发模式

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

访问 http://localhost:8080。Vite 会将浏览器的 `/api` 请求代理到 `http://127.0.0.1:8000`。

如果前后端不通过同一站点代理，可以在前端环境变量中指定 API 地址：

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

## Docker 部署

先创建并检查 `backend/.env`，然后在项目根目录执行：

```bash
docker compose up --build
```

后台运行：

```bash
docker compose up -d --build
```

Docker Compose 当前仍使用独立的 Nginx 前端容器：

- Web 界面：http://localhost:8080
- 后端 API：http://localhost:8000
- API 文档：http://localhost:8000/docs

后端镜像构建时会下载 `BAAI/bge-base-zh` 和 `BAAI/bge-reranker-base`，首次构建耗时较长。Compose 将 `backend/` 挂载到容器 `/app`，运行数据会保存在宿主机的 `backend/uploads`、`backend/txt_files`、`backend/results` 和 `backend/chroma_data`。

使用镜像内预下载模型时，可在 `backend/.env` 中设置：

```dotenv
IS_USE_LOCAL=True
EMBEDDINGS_PATH=/app/models/bge-base-zh
RERANK_MODEL=/app/models/bge-reranker-base
```

## 安全建议

当前项目没有内置用户登录或 API 鉴权，不应将后端端口直接暴露到不受信任的公网环境。

- 仅在本机使用时，可以设置 `HOST=127.0.0.1`。
- 局域网或公网部署时，建议通过带身份验证和 HTTPS 的反向代理访问。
- 将 `CORS_ALLOW_ORIGINS` 限制为实际使用的前端来源，不要在公网部署中保留通配符。
- 不要提交 `backend/.env`、运行日志、上传文件或知识库数据。
- AI 连通性测试只发送固定的最小测试消息，不会发送已上传的文档内容。

## 使用说明

### 配置 AI 模型

1. 启动应用并打开左侧设置面板。
2. 填写 OpenAI 兼容服务的 Base URL、API Key 和模型名称。
3. 根据服务能力设置温度和思考模式。
4. 点击“测试连接”。测试会发起一个最小对话请求，但不会保存配置。
5. 测试成功后点击“保存 AI 配置”。新配置会立即用于后续图谱抽取和 RAG 请求。

运行时配置仅保存在后端内存中，重启后会重新读取 `backend/.env`。后端返回设置时只提供 API Key 是否已配置及脱敏提示，不会返回完整密钥。若不修改已有密钥，保存或测试时可以将 API Key 输入框留空。

### 选择笔记类型

- **通用**：使用当前提示词版本中的通用处理模板。
- **故事**：使用面向故事内容的图谱处理方式。
- **自定义**：可分别编辑实体抽取、关系抽取和知识融合提示词。

首次选择“自定义”时会载入通用提示词作为初始值。“恢复通用提示词”会重新读取当前 `PROMPTVISION` 对应的模板。每个自定义提示词最多 30,000 个字符，并保存在当前浏览器的本地存储中；上传文件时会随请求提交，不会修改服务器上的模板文件。

### 上传和重新处理文件

1. 在设置中选择笔记类型；处理扫描 PDF 或图片内容时，开启“PDF 图片内容识别”。
2. 点击或拖拽上传 `.txt`、`.md` 或 `.pdf` 文件。
3. 在文件列表查看处理状态和分块进度。
4. 处理完成后点击文件进入结果工作区。

处理中可通过文件右键菜单暂停任务；后端会在当前文本块完成并保存检查点后安全停止。之后选择继续处理即可从检查点恢复，无需重复已完成的 AI 请求。

同名文件的处理规则：

- 已有完整文本、知识库和图谱结果时，前端会询问是否执行增量更新。
- 上次处理状态为失败时，重新上传不会执行增量更新；后端会删除可能残留的文本、图谱结果和知识库记录，然后完整重建。
- 已完成文件可在右键菜单中下载 `.kmn.zip` 迁移包。迁移包本身是 ZIP，可直接解压查看原始文档和 HTML 图谱，也可拖拽回上传区完整恢复数据。
- 数据不完整时，即使文件名相同也会执行完整处理，避免在缺失结果上进行增量更新。

### 查看结果

结果工作区包含三个面板：

- **原文件**：在 Markdown 预览和源码之间切换，并支持复制和下载。
- **知识图谱**：浏览节点、关系和权重；大图谱会生成社区总览和详情页。
- **RAG 问答**：针对当前文件提问，可启用流式输出和历史上下文，并可停止正在生成的回答。

桌面端可以拖动文件列表边界和面板分隔条。空间不足时，非活动面板会自动隐藏，也可以通过顶部标签手动显示或隐藏。

### 管理文件与问答历史

选中已完成文件后，可以：

- 删除文件及其上传文件、转换文本、图谱结果和知识库数据。
- 仅清除该文件的 RAG 历史，保留文件与知识图谱。

聊天历史还会保存在浏览器本地存储中。前端执行删除或清理操作时会同步清理对应的本地缓存。

### 关系权重与检索参数

关系权重范围为 `0` 到 `1`，表示当前语境下关系的重要程度。图谱使用边的粗细展示权重。HybridRAG 请求可以通过以下参数控制检索：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `top_k` | `1` | 向量召回数量 |
| `weight_threshold` | `0.3` | 参与问答的最低关系权重 |
| `max_relations` | `20` | 最多使用的关系数量 |

## API 概览

完整请求和响应结构请查看启动后的 `/docs`。API 可以直接使用表中的路径；由打包前端、Vite 或 Nginx 调用时也支持 `/api` 前缀。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/ai-settings` | 获取当前文本模型配置，不返回完整 API Key |
| `PUT` | `/ai-settings` | 更新当前进程的文本模型配置 |
| `POST` | `/ai-settings/test` | 测试提交的模型配置，不保存设置 |
| `GET` | `/processing-prompts/defaults` | 获取当前版本的通用三阶段处理提示词 |
| `POST` | `/upload` | 上传文档并开始完整处理或增量更新 |
| `GET` | `/export-package/{filename}` | 下载可跨系统恢复的原文与图谱迁移包 |
| `GET` | `/processing-status/{filename}` | 查询状态、分块进度和预计剩余时间 |
| `POST` | `/pause-processing/{filename}` | 请求在当前文本块完成后暂停处理 |
| `POST` | `/resume-processing/{filename}` | 从已保存的检查点继续处理 |
| `GET` | `/list-files` | 获取知识库文件列表 |
| `GET` | `/file-content/{filename}` | 获取转换后的文本内容 |
| `GET` | `/file-entities/{filename}?count=5` | 获取文件的主要实体 |
| `GET` | `/result/{filename}` | 获取知识图谱主页 |
| `GET` | `/result-page/{graph_name}/{page_name}` | 获取图谱主页或社区详情页 |
| `DELETE` | `/delete/{filename}` | 删除文件、图谱和相关知识库数据 |
| `DELETE` | `/rag-history/{filename}` | 清除指定文件的 RAG 历史 |
| `POST` | `/create_session` | 创建问答会话 |
| `POST` | `/hybridrag` | 非流式 HybridRAG 问答 |
| `POST` | `/hybridrag/stream` | SSE 流式 HybridRAG 问答 |
| `GET` | `/session_status/{session_id}` | 查询会话状态和队列长度 |
| `DELETE` | `/session/{session_id}` | 删除空闲会话 |

`POST /upload` 使用 `multipart/form-data`，支持以下字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file` | 是 | `.txt`、`.md` 或 `.pdf` 文件 |
| `noteType` | 否 | `general`、`story` 或 `custom`，默认 `general` |
| `use_img2txt` | 否 | 是否识别 PDF 图片内容 |
| `entityPrompt` | 自定义类型时可选 | 实体抽取提示词，留空时使用通用模板 |
| `relationshipPrompt` | 自定义类型时可选 | 关系抽取提示词，留空时使用通用模板 |
| `fusionPrompt` | 自定义类型时可选 | 知识融合提示词，留空时使用通用模板 |

HybridRAG 请求示例：

```json
{
  "request": "这篇文档的核心观点是什么？",
  "filename": "example.pdf",
  "flow": true,
  "top_k": 3,
  "weight_threshold": 0.3,
  "max_relations": 20,
  "messages": [],
  "session_id": null
}
```

## 数据与目录

```text
KnowledgeMapNotes/
├── backend/
│   ├── main.py                    # FastAPI 应用入口
│   ├── KnowledgeGraphManager/     # 图谱构建、融合与可视化
│   ├── LLM/                       # 大模型调用与 RAG 输出处理
│   ├── OmniStore/                 # ChromaDB 和知识库存储
│   ├── OmniText/                  # PDF、Markdown 文本提取
│   ├── TextSlicer/                # 文本分割器
│   ├── embedding_tools/           # 嵌入和重排工具
│   ├── prompt/                    # v1/v2 提示词模板
│   ├── uploads/                   # 上传的原始文件
│   ├── txt_files/                 # 转换后的文本文件
│   ├── results/<文档名>/          # 图谱主页和社区详情页
│   └── chroma_data/               # ChromaDB 持久化数据
└── frontend/
    ├── src/                       # Vue 3 应用源码
    ├── dist/                      # npm run build 生成的前端产物
    ├── vite.config.js             # 开发服务器与 API 代理
    └── nginx.conf                 # Docker 前端反向代理
```

`uploads`、`txt_files`、`results` 和 `chroma_data` 是一组关联的运行时数据。迁移、恢复或备份知识库时，应保持这些目录一致。

## 抖音聊天 JSON 转 TXT

仓库提供了一个辅助脚本，用于处理 `douyin-chat-export` 导出的 JSON：

```bash
python "backend/validation/将抖音聊天转txt.py" chat.json chat.txt
```

省略第二个参数时，脚本会在当前目录输出 `result.txt`：

```bash
python "backend/validation/将抖音聊天转txt.py" chat.json
```

也可以从标准输入读取：

```bash
python "backend/validation/将抖音聊天转txt.py" < chat.json
```

脚本会保留普通消息（`type=0`，排除 `[系统消息]`）和 `type=24` 消息，并输出为每行 `accountName:content` 的文本。生成的 TXT 可以直接上传到系统。

## 常见问题

### 未填写 Base URL 和 API Key，后端能否启动？

可以。后端会等待用户在 Web 设置中配置文本模型。上传处理、RAG 问答等需要模型的接口在配置完成前会返回 `503` 和明确提示。

### 为什么启动后只能访问 API，打不开 Web 界面？

确认已在 `frontend/` 中运行 `npm run build`，并检查 `frontend/dist/index.html` 是否存在。使用自定义构建目录时设置 `FRONTEND_DIST`。后端启动日志会显示实际挂载目录或缺失提示。

### 启动后端时找不到提示词或 `.env`

后端的提示词和多数运行目录仍使用相对路径。请从 `backend/` 目录执行：

```bash
python main.py
```

也可以执行：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### AI 连接测试成功，但重启后配置丢失

前端保存的 AI 配置只应用于当前后端进程。需要持久化时，请同步填写 `backend/.env`，然后重启后端。

### 重新上传失败文件时会增量更新吗？

不会。前端允许直接重传失败文件，后端会识别失败状态并清理残留后完整处理。只有知识库、转换文本和图谱结果都完整存在时才允许增量更新。

### 如何使用本地嵌入模型？

设置 `IS_USE_LOCAL=True`，并将 `EMBEDDINGS_PATH` 指向本地模型目录。`DEVICE=cuda` 需要安装与本机 CUDA 版本匹配的 PyTorch；否则使用 `DEVICE=cpu`。

### 扫描 PDF 没有识别出图片内容

在前端设置中开启“PDF 图片内容识别”，并检查 `VL_API_KEY` 和 `VL_BASE_URL`。纯文本 PDF 通常不需要开启该功能。

### 为什么大图谱会打开多个页面？

当 Louvain 发现多个社区，且至少一个社区达到分页阈值时，系统会生成跨社区总览页和较大社区的详情页。这是大规模图谱的默认渲染策略。默认只为节点数不少于 20 的社区生成详情页；更小的社区仍然存在于总览图中，但不会出现在详情列表。

如需查看所有社区，在 `backend/.env` 中设置 `GRAPH_COMMUNITY_MIN_SIZE=1`，然后重新生成该文件的图谱。设置为更大的数值可以减少页面数量。

### 修改 `.env` 后没有生效

环境变量在后端启动时加载。修改后需要重启后端；Docker 环境可以执行 `docker compose restart backend`。

## 外部功能整合

项目可配合 [QAlite](https://github.com/Xikcn/QAlite) 和对应 MCP 服务整理 QA 类型笔记。

![QAlite](readme_img/img.png)

旧版演示视频：

https://github.com/user-attachments/assets/5b62e85b-1340-4b79-814c-994380a8e146

## Roadmap

- 当本地知识图谱无法回答时，按需联网补充相关知识。
- 优化文本分块和向量/三元组融合策略。
- 增加笔记事实检查、复习试卷和讲解视频生成能力。
- 完善隐私数据脱敏与还原流程。

## 许可证

MIT
