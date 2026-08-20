# 后端架构与维护说明

## 应用入口

`backend/main.py` 是 FastAPI 组合入口，负责：

- 创建应用、中间件和静态前端挂载；
- 初始化图谱、向量库、分割器和模型代理；
- 注入并挂载 `services/` 中的业务服务；
- 保留文件处理、图谱编辑、迁移包和文件管理路由。

新功能应优先放到职责对应的模块中。只有应用装配、跨模块依赖注入和短小兼容包装器应继续留在 `main.py`。

## 服务模块

| 模块 | 职责 |
| --- | --- |
| `services/ai_runtime.py` | AI 配置、客户端创建、模型发现、连接验证和运行时设置 API |
| `services/document_store.py` | 原文、草稿、富文本、文档快照及版本历史路径和读写 |
| `services/processing_progress.py` | 处理状态持久化、三阶段进度、速度采样、ETA 和重启恢复 |
| `services/rag_service.py` | RAG 会话队列、同文件串行锁、普通/流式问答、引用和会话 API |

`main.py` 中保留部分指向服务实例的兼容别名，例如 `PROCESS_STATUS`、`initialize_session` 和 `build_rag_citations`。已有测试或外部脚本可以继续导入这些名称，但新代码应直接使用服务对象。

## 文件处理流程

文件处理分为三个独立阶段：

1. 实体抽取，以文本块为单位记录进度；
2. 关系抽取，以文本块为单位记录进度；
3. 知识融合，以待融合实体对为单位记录进度。

每次完成单项时记录真实耗时，通过累计耗时计算平均速度和阶段剩余时间。总体百分比按三个阶段等权汇总，总 ETA 使用各阶段已测得的平均单项耗时；尚无样本时会复用已有阶段的平均值，无法可靠估计时返回 `null`，前端不应虚构倒计时。

任务状态写入 `backend/processing_states/*.json`。每个检查点同时保存分块参数、社区阈值和处理位置。浏览器刷新只会丢失当前页面的临时渲染，不会取消后台任务；前端重新请求文件列表和状态接口即可恢复显示。后端进程意外停止后，启动恢复逻辑会把未结束任务标记为 `interrupted`，用户可从已保存块继续。

## 分块、流式与社区设置

- `KG_CHUNK_MAX_TOKENS`、`KG_CHUNK_MIN_TOKENS` 是环境默认值，上传表单中的 `chunkMaxTokens`、`chunkMinTokens` 可按任务覆盖。
- `AI_STREAM` 和 `FALLBACK_STREAM` 分别控制主、备用模型的结构化处理调用；运行时 AI 设置可以覆盖环境值。
- `GRAPH_COMMUNITY_MIN_SIZE_MODE=custom` 使用固定最小节点数。
- `GRAPH_COMMUNITY_MIN_SIZE_MODE=auto` 按 `ceil((总节点数 + 平均度数) × 百分比)` 计算并限制在 1 到总节点数之间。

分块越小，长文实体漏抽风险通常越低，但模型请求次数和总处理时间会增加。修改这些参数只影响新任务或显式重新处理，不应隐式改写正在恢复的任务。

## 运行数据

以下目录不是缓存，项目清理时不得删除：

- `backend/uploads/`
- `backend/txt_files/`
- `backend/results/`
- `backend/chroma_data/`
- `backend/processing_states/`
- `backend/graph_history/`

`backend/images/` 是 PDF 解析产生的临时图片目录，不属于知识库持久化数据，已加入 `.gitignore`。

## 验证命令

```bash
cd backend
python -m py_compile main.py services/*.py
python -m unittest tests.test_processing_progress -v
python -m unittest tests.test_rag_service -v

cd ../frontend
npm run build

cd ..
git diff --check
```

涉及图谱、迁移包或模型代理的改动，还应运行对应的 `backend/tests/test_*.py` 模块。测试不得依赖或清空真实运行数据目录。
