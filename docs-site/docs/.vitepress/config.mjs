import { defineConfig } from 'vitepress'

export default defineConfig({
  lang: 'zh-CN',
  title: 'KnowledgeMapNotes',
  description: '将文档转化为可探索、可追溯、可问答的知识图谱',
  cleanUrls: true,
  lastUpdated: true,
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/logo.svg' }],
    ['meta', { name: 'theme-color', content: '#1d8a67' }],
    ['meta', { property: 'og:title', content: 'KnowledgeMapNotes 文档' }],
    ['meta', { property: 'og:description', content: '知识图谱笔记系统的使用、部署与 API 文档' }]
  ],
  themeConfig: {
    logo: '/logo.svg',
    siteTitle: 'KnowledgeMapNotes',
    nav: [
      { text: '首页', link: '/' },
      { text: '快速开始', link: '/guide/getting-started' },
      {
        text: '功能',
        items: [
          { text: '文档处理', link: '/features/document-processing' },
          { text: '知识图谱', link: '/features/knowledge-graph' },
          { text: '文档工作流', link: '/features/document-workflow' },
          { text: 'HybridRAG 问答', link: '/features/hybrid-rag' },
          { text: '历史与迁移', link: '/features/history-migration' }
        ]
      },
      { text: '部署', link: '/deployment/local' },
      { text: 'API', link: '/reference/api' },
      { text: '常见问题', link: '/faq' },
      { text: '路线图', link: '/roadmap' },
      { text: '许可证', link: '/license' }
    ],
    sidebar: {
      '/guide/': [
        {
          text: '入门',
          items: [
            { text: '快速开始', link: '/guide/getting-started' },
            { text: '安装与运行', link: '/guide/installation' },
            { text: '配置 AI 模型', link: '/guide/ai-configuration' },
            { text: '创建第一张图谱', link: '/guide/first-graph' }
          ]
        }
      ],
      '/features/': [
        {
          text: '核心能力',
          items: [
            { text: '文档处理', link: '/features/document-processing' },
            { text: '知识图谱', link: '/features/knowledge-graph' },
            { text: '文档工作流', link: '/features/document-workflow' },
            { text: 'HybridRAG 问答', link: '/features/hybrid-rag' },
            { text: '历史与迁移', link: '/features/history-migration' }
          ]
        }
      ],
      '/deployment/': [
        {
          text: '部署',
          items: [
            { text: '本地部署', link: '/deployment/local' },
            { text: 'Docker 部署', link: '/deployment/docker' },
            { text: '生产环境与安全', link: '/deployment/production' }
          ]
        }
      ],
      '/reference/': [
        {
          text: '参考',
          items: [
            { text: '环境变量', link: '/reference/configuration' },
            { text: 'HTTP API', link: '/reference/api' },
            { text: '数据目录', link: '/reference/data' }
          ]
        }
      ]
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/Xikcn/KnowledgeMapNotes' }
    ],
    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
          modal: {
            noResultsText: '没有找到相关内容',
            resetButtonTitle: '清除查询',
            footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' }
          }
        }
      }
    },
    outline: { label: '本页目录', level: [2, 3] },
    docFooter: { prev: '上一篇', next: '下一篇' },
    lastUpdated: { text: '最后更新' },
    returnToTopLabel: '返回顶部',
    sidebarMenuLabel: '菜单',
    darkModeSwitchLabel: '深色模式',
    footer: {
      message: 'GNU AGPL-3.0 双许可模式 · 数据由你掌控',
      copyright: 'KnowledgeMapNotes 文档站'
    }
  }
})
