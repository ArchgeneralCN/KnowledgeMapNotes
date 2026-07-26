# 默认示例

此目录中的 `.kmn.zip` 是已完成处理的知识图谱迁移包。后端首次启动时会自动导入这些文件，但检测到任何同名用户数据后会跳过，不执行覆盖。

`三国志.kmn.zip` 由本地已完成的“三国志”生成，不包含个人 RAG 对话。更新本地处理结果后，可在项目根目录重新构建：

```bash
python backend/scripts/build_default_example.py 三国志
```

部署者可在 `backend/.env` 中设置 `DEFAULT_EXAMPLES_ENABLED=False`，关闭默认示例导入。
