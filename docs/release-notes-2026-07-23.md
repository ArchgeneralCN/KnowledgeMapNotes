# KnowledgeMapNotes 推送说明

## 变更摘要

本次推送整合了后端运行时 AI 配置、文件处理可靠性、可自定义笔记提示词、前端安全升级、单进程部署和文档更新。

## 功能变更

- 后端在 `BASE_URL`、`API_KEY` 未配置时仍可启动，用户可以从前端设置 AI 服务。
- 新增 AI 配置连通性测试接口和设置面板按钮；测试请求不会保存配置，也不会发送用户文档内容。
- 新增“自定义”笔记类型，可分别编辑实体抽取、关系抽取和知识融合提示词；空字段自动回退到通用提示词。
- 失败文件重新上传时强制完整重建，避免因为残留文本或知识库数据错误触发增量更新。
- 完成文件支持独立删除文件和清除 RAG 历史，恢复 RAG 操作图标显示。
- 后端可直接托管 `frontend/dist`，并支持 `/api` 前缀和 Vue History 路由回退。
- 结果工作区支持原文、知识图谱和 RAG 面板调整，设置面板在窄屏下保持可用。

## 安全与依赖

- Markdown 原始 HTML 被禁用，渲染结果经过 DOMPurify 清理。
- 外部链接添加 `target` 和 `rel="noopener noreferrer"`。
- 文件路径参数统一编码和校验。
- 替换 `vite-plugin-svg-icons` 为 `vite-svg-loader`，移除未使用的 `echarts`。
- 升级前端依赖，推送前 `npm audit --audit-level=low` 结果为 0 个漏洞。
- 新增根级 `.gitignore`，防止密钥、运行数据、缓存和构建产物被意外提交。

## 部署方式

### 单进程部署

```bash
cd frontend
npm ci
npm run build
cd ../backend
python main.py
```

访问 `http://localhost:8000`。如构建目录不在默认位置，可设置 `FRONTEND_DIST`。

### 开发模式

```bash
# 终端一
cd backend
python main.py

# 终端二
cd frontend
npm ci
npm run dev
```

开发前端地址为 `http://localhost:8080`，Vite 将 `/api` 请求代理到后端。

## 兼容性说明

- 已有 `backend/.env` 无需增加新必填字段；`ENABLE_THINKING` 为可选配置。
- 运行时保存的 AI 配置只存在于当前后端进程，重启后仍以 `backend/.env` 为初始值。
- Docker Compose 继续使用独立的 Nginx 前端容器，单进程托管方式不改变 Docker 入口。
- 运行数据、API Key、日志、`frontend/node_modules` 和构建产物不应作为源码提交。

## 验证记录

- `npm run build`：通过。
- `npm audit --audit-level=low`：`found 0 vulnerabilities`。
- `python -m py_compile backend/main.py`：通过。
- `git diff --check`：通过。
- 单进程接口检查：`/`、`/home`、`/api/health` 返回 200，缺失静态资源返回 404，未知 API 返回 404。

## 提交建议

建议提交标题：

```text
完善 AI 配置、文件处理与单进程前端部署
```

推送前请确认：

1. `backend/.env` 未被暂存。
2. `backend/uploads`、`backend/results`、`backend/chroma_data` 等运行数据未被暂存。
3. 在目标环境重新执行 `npm ci` 和 `npm run build`，或确认已包含有效的 `frontend/dist`。
4. 生产环境不要直接将未鉴权的后端端口暴露到公网。
