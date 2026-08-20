# Git 提交说明

本文根据当前工作区的后端、前端、启动脚本、配置、文档和测试改动整理。这里只准备提交说明，不执行 `git commit` 或 `git push`；提交前请重新检查 `git status`，因为当前改动同时存在于暂存区和工作区。

## 推荐标题

```text
feat: rebuild knowledge workspace and modularize backend services
```

## 推荐正文

```text
- introduce the React/Vite workspace for upload, file library, graph exploration, RAG chat, original-document editing, history, settings, and responsive layouts
- add Sigma.js static graph pages, topology-aware layouts, community navigation, entity-type icons, and graph-to-document evidence highlighting while retaining the PyVis editor
- split AI runtime, document storage, processing progress, and RAG session logic into backend services without changing existing API compatibility names
- add streaming model responses, stage-level progress and ETA, pause/resume checkpoints, per-file chunk settings, and configurable community pagination
- improve graph extraction/fusion/batching, graph editing and history, vector context retrieval, text encoding/splitting, document processing, transfer metadata, and prompt/config handling
- add cross-platform local launchers that prepare the virtual environment, dependencies, local embedding/reranker models, frontend build, environment paths, and fallback ports
- update Docker assets, dependency manifests, examples, multilingual documentation, architecture and deployment guides, and add regression coverage for services, launchers, graph rendering, progress, stores, RAG, and checkpoint flows
```

## 兼容与迁移说明

- 后端 HTTP API 路径和前端请求格式保持兼容；`main.py` 继续导出进度、RAG 和其他历史兼容名称。
- Vite 的默认入口改为 React 的 `frontend/src/main.jsx`。旧 Vue 源码仍在工作区中，当前差异没有删除它们；提交前请确认是否保留这部分过渡代码。
- 首次使用 `start.py`、`start.bat` 或 `start.sh` 需要 Python 3.10+、Node.js 18+ 和网络连接。启动器会创建 `.venv`、安装依赖、从 ModelScope 下载本地嵌入/重排模型、更新 `backend/.env` 并构建前端。
- 启动器默认监听 `127.0.0.1:8000`；端口被占用时会自动选择后续可用端口。若设置 `HOST=0.0.0.0`，请自行确认防火墙和访问安全。
- `backend/.env` 中的 API Key 和其他本地配置不会被启动器覆盖；模型目录、虚拟环境和前端构建产物均为本地生成数据。
- `backend/uploads/`、`backend/txt_files/`、`backend/results/`、`backend/chroma_data/`、`backend/processing_states/` 和 `backend/graph_history/` 是运行数据，提交或清理时不要误删。
- 当前还有未跟踪的 `uv.lock`。项目现行依赖入口是 `backend/requirements.txt`，默认建议不要把这个本地生成的锁文件混入本次提交；如决定保留，请先确认 `pyproject.toml` 的忽略规则和团队的依赖管理方式。

## 改动范围

| 区域 | 主要内容 |
| --- | --- |
| 后端 | `main.py` 服务装配、AI/文档/进度/RAG 服务、知识图谱与 Sigma 静态页面、图谱编辑/历史、存储和文本处理 |
| 前端 | React/Vite 工作区、文件库、原文编辑与历史、图谱和 RAG 面板、设置、响应式样式、Sigma 运行资源和实体类型图标 |
| 启动与部署 | 跨平台启动器、Dockerfile、Compose、环境示例、忽略规则、前后端依赖清单 |
| 测试与文档 | 服务、启动器、图谱、进度、存储、RAG、检查点和文本处理测试；README、架构、本地部署及示例文档 |

## 提交前检查

```bash
# 先确认暂存区、工作区和未跟踪文件
git status --short
git diff --stat
git diff --cached --stat

# 仅将确认过的文件加入暂存区；决定是否包含 uv.lock 后再执行
git add <confirmed-files>
git diff --cached --check

# 前端构建
cd frontend
npm ci
npm run build

# 后端语法与测试
cd ../backend
python -m py_compile main.py services/*.py
python -m unittest discover -s tests -v

# 回到项目根目录复核
cd ..
git diff --cached --check
```

确认暂存区内容后，在 Git 提交编辑器中粘贴上面的标题和正文即可创建本地提交；本次不执行推送。
