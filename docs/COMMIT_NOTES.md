# 提交说明

## 建议提交标题

`feat: 完善知识图谱证据定位、文档同步和主题视觉体验`

## 提交内容

- 优化静态 ForceAtlas2 图谱布局，分离孤立节点并增加节点碰撞消解。
- 增强节点和关系的原文定位，区分文本块、实体、关系、关系说明和当前查询对象的高亮颜色。
- 增加“全部 / 当前”高亮范围设置，并持久化用户选择。
- 增加文档预览、源码和富文本编辑工作流，支持草稿、文档历史、还原和文件列表增量更新。
- 增量更新完成后自动重绘图谱，并在图谱历史还原时同步恢复文档内容。
- 增加文件切换未保存保护和异步请求序号，避免快速切换文件导致空白或旧内容覆盖。
- 完善默认、暗色、蓝色和护眼主题的颜色变量、代码块、草稿提示和证据高亮配色。
- 重新组织文档工具栏布局，改善桌面端和移动端的控件间距。

## 验证结果

- `python -m py_compile backend/main.py backend/KnowledgeGraphManager/graph_editing.py backend/KnowledgeGraphManager/graph_interactions.py`
- `PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -q`
- `npm run build`
- `git diff --check`

## 提交前检查

- 检查四种主题下文档工具栏、原文高亮、编辑器和 RAG 面板的显示效果。
- 检查切换文件时未保存草稿的保存、放弃和取消分支。
- 检查增量更新完成后图谱页面和文档内容是否同步刷新。
- 检查图谱历史还原后文档内容、草稿状态和引用文本块是否一致。
- 确认不提交 `backend/.env`、运行时数据库、上传文件和生成结果目录中的敏感数据。

## 推送说明

本次只准备提交说明，不执行 `git commit`、`git push` 或远程分支操作。
