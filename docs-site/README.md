# KnowledgeMapNotes 文档站

这是 KnowledgeMapNotes 的独立应用文档站，基于 VitePress 构建。内容覆盖快速开始、AI 配置、核心功能、部署、安全、HTTP API、数据目录、常见问题和许可证。首页额外提供滚动式处理流程与真实图谱示例。

## 环境要求

- Node.js 18 或更高版本
- npm 9 或更高版本

## 本地开发

```bash
npm install
npm run dev
```

默认访问 `http://localhost:5173`。若端口已被占用，VitePress 会自动选择下一个可用端口。

## 目录结构

```text
docs-site/
├── covers/                  # 首页图谱封面源文件
├── docs/                    # Markdown 页面与 VitePress 主题
│   ├── .vitepress/          # 站点配置、自定义首页和全局样式
│   └── public/examples/     # 可部署的图谱静态页面
├── scripts/
│   └── sync-examples.mjs    # 同步图谱、封面和本地依赖
├── package.json
└── README.md
```

## 编辑文档

- 新增或修改页面：编辑 `docs/` 下的 Markdown 文件。
- 调整导航和侧栏：编辑 `docs/.vitepress/config.mjs`。
- 修改首页流程、画廊或弹窗：编辑 `docs/.vitepress/theme/HomePage.vue`。
- 修改首页和站点视觉：编辑 `docs/.vitepress/theme/style.css`。

每个 Markdown 页面应设置明确的 `title` 和 `description`。新增页面后，还应把入口加入顶部导航或对应侧栏。

## 图谱示例

启动和构建前会自动扫描 `../backend/results/`，把所有图谱主页面与社区详情页同步到首页示例库。同步过程会把 vis-network 依赖替换为本地静态资源，并为每个图谱生成稳定的 ASCII 入口地址。也可以手动执行：

```bash
npm run sync:examples
```

首页示例封面统一放在 `covers/`，文件名以图谱目录名开头即可匹配，例如：

```text
covers/三国志_封面.png
covers/改命记实录(道之光)_设计.png
```

支持的图片格式：

- `.png`、`.jpg`、`.jpeg`、`.webp`、`.avif`

未提供匹配封面时，首页会使用内置应用预览图。开发和构建命令会自动同步封面与图谱文件。建议封面采用 `4:3` 比例。

每个图谱目录优先使用与目录同名的 HTML 作为主图；后续新增图谱时保持这一命名规则即可自动出现在首页。

## 生产构建

```bash
npm run build
npm run preview
```

构建产物位于 `docs/.vitepress/dist`，可以部署到任意静态站点服务。

部署时应发布整个 `docs/.vitepress/dist/` 目录，不能只上传首页文件，否则图谱、社区视图和本地 vis-network 资源会缺失。若部署在子路径下，请同步设置 VitePress 的 `base`，并确认首页、封面、四个图谱入口和社区详情页都能访问。

## 提交前检查

```bash
npm ci
npm run sync:examples
npm run build
```

不要提交 `node_modules/`、`docs/.vitepress/cache/`、`docs/.vitepress/dist/` 或同步生成的 `docs/public/examples/graph-*/cover.*`。`docs/public/examples/` 中的图谱 HTML、本地 vis-network 依赖和清单是首页示例所需的静态源文件，需要随文档站提交；封面源文件只保留在 `covers/`。
