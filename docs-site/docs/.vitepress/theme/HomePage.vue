<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'
import {
  ArrowRight,
  BookOpen,
  Bot,
  BrainCircuit,
  Combine,
  ExternalLink,
  FileInput,
  FilePenLine,
  FileText,
  Github,
  History,
  Link2,
  Maximize2,
  MessageSquareText,
  Network,
  Scissors,
  Settings2,
  Sparkles,
  UploadCloud,
  X
} from 'lucide-vue-next'
import { graphExamples } from './generated/examples.js'

const features = [
  {
    icon: UploadCloud,
    title: '多格式文档处理',
    detail: '导入 TXT、Markdown、PDF 与迁移包，按文本块持续保存处理进度。',
    link: '/features/document-processing'
  },
  {
    icon: Network,
    title: '知识图谱可视化',
    detail: '自动抽取实体与关系，以静态布局和社区视图探索大规模图谱。',
    link: '/features/knowledge-graph'
  },
  {
    icon: Bot,
    title: 'HybridRAG 问答',
    detail: '融合向量召回、实体关系和图谱社区，流式回答并保留证据来源。',
    link: '/features/hybrid-rag'
  },
  {
    icon: FilePenLine,
    title: '文档编辑闭环',
    detail: '预览、源码和富文本三种视图，支持草稿、版本历史与增量更新。',
    link: '/features/document-workflow'
  },
  {
    icon: History,
    title: '历史与迁移',
    detail: '图谱与文档联合快照，可回退、导出并在另一实例中完整恢复。',
    link: '/features/history-migration'
  },
  {
    icon: Settings2,
    title: '灵活模型配置',
    detail: '兼容 OpenAI API，可设置备用模型、处理提示词和本地嵌入模型。',
    link: '/guide/ai-configuration'
  }
]

const storyStages = [
  {
    step: '01',
    label: 'DOCUMENT IN',
    title: '文件进入知识库',
    detail: 'TXT、Markdown 或 PDF 被安全接收，系统建立处理任务并保存原始文档。',
    status: '已接收 example.pdf',
    icon: FileInput,
    scene: 'file',
    accent: 'blue'
  },
  {
    step: '02',
    label: 'CHUNKING',
    title: '内容解析与分块',
    detail: '提取正文与图片描述，再按文档类型切成可追踪的文本块，每一块都保留来源位置。',
    status: '已生成 12 个文本块',
    icon: Scissors,
    scene: 'chunks',
    accent: 'gold'
  },
  {
    step: '03',
    label: 'ENTITY EXTRACTION',
    title: '大模型提取实体',
    detail: '模型识别人名、概念、地点、技术与事件，将自然语言中的知识对象结构化。',
    status: '识别 38 个候选实体',
    icon: Sparkles,
    scene: 'entities',
    accent: 'coral'
  },
  {
    step: '04',
    label: 'RELATION EXTRACTION',
    title: '建立实体关系',
    detail: '从上下文中抽取实体之间的方向、说明和权重，并始终关联回原文文本块。',
    status: '建立 54 条加权关系',
    icon: Link2,
    scene: 'relations',
    accent: 'blue'
  },
  {
    step: '05',
    label: 'KNOWLEDGE FUSION',
    title: '融合重复知识',
    detail: '跨文本块判断同义实体和冲突关系，合并重复信息，形成更干净的一致知识层。',
    status: '合并 9 组重复知识',
    icon: Combine,
    scene: 'fusion',
    accent: 'green'
  },
  {
    step: '06',
    label: 'GRAPH READY',
    title: '生成可探索图谱',
    detail: '完成静态布局、关系权重和社区发现，节点与连线都可以继续检索、编辑和回溯。',
    status: '知识图谱已生成',
    icon: Network,
    scene: 'graph',
    accent: 'coral'
  },
  {
    step: '07',
    label: 'HYBRIDRAG',
    title: '带着证据开始问答',
    detail: '向量召回、实体关系和图谱社区共同提供上下文，回答中的依据可以一键回到原文。',
    status: '回答已关联 3 条证据',
    icon: MessageSquareText,
    scene: 'rag',
    accent: 'green'
  }
]

const storySection = ref(null)
const activeStageIndex = ref(0)
const storyProgress = ref(0)
const selectedExample = ref(null)
const modalCloseButton = ref(null)
let scrollFrame = 0

const activeStage = computed(() => storyStages[activeStageIndex.value])

const updateStoryProgress = () => {
  scrollFrame = 0
  const section = storySection.value
  if (!section) return

  const sectionRect = section.getBoundingClientRect()
  const travel = Math.max(1, section.offsetHeight - window.innerHeight)
  const progress = Math.min(1, Math.max(0, (64 - sectionRect.top) / travel))
  storyProgress.value = progress
  activeStageIndex.value = Math.min(
    storyStages.length - 1,
    Math.floor(progress * storyStages.length)
  )
}

const requestStoryUpdate = () => {
  if (scrollFrame) return
  scrollFrame = window.requestAnimationFrame(updateStoryProgress)
}

const goToStage = index => {
  const section = storySection.value
  if (!section) return

  const travel = Math.max(1, section.offsetHeight - window.innerHeight)
  const stageProgress = (index + 0.5) / storyStages.length
  const targetTop = window.scrollY + section.getBoundingClientRect().top - 64 + travel * stageProgress
  window.scrollTo({ top: targetTop, behavior: 'smooth' })
}

const formatSize = sizeBytes => {
  if (sizeBytes < 1024 * 1024) return `${Math.max(1, Math.round(sizeBytes / 1024))} KB`
  return `${(sizeBytes / 1024 / 1024).toFixed(1)} MB`
}

const openExample = async example => {
  selectedExample.value = example
  document.body.classList.add('km-modal-open')
  await nextTick()
  modalCloseButton.value?.focus()
}

const closeExample = () => {
  selectedExample.value = null
  document.body.classList.remove('km-modal-open')
}

const handleGlobalKeydown = event => {
  if (event.key === 'Escape' && selectedExample.value) closeExample()
}

onMounted(() => {
  window.addEventListener('scroll', requestStoryUpdate, { passive: true })
  window.addEventListener('resize', requestStoryUpdate)
  window.addEventListener('keydown', handleGlobalKeydown)
  updateStoryProgress()
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', requestStoryUpdate)
  window.removeEventListener('resize', requestStoryUpdate)
  window.removeEventListener('keydown', handleGlobalKeydown)
  if (scrollFrame) window.cancelAnimationFrame(scrollFrame)
  document.body.classList.remove('km-modal-open')
})
</script>

<template>
  <div class="km-home">
    <section class="km-hero" aria-labelledby="km-hero-title">
      <img class="km-hero-image" src="/app-preview.png" alt="KnowledgeMapNotes 知识图谱工作区" />
      <div class="km-hero-shade"></div>
      <div class="km-hero-content">
        <p class="km-eyebrow"><span></span> 开源知识图谱笔记系统</p>
        <h1 id="km-hero-title">KnowledgeMapNotes</h1>
        <p class="km-hero-lead">把文档变成可探索、可追溯、可问答的知识网络</p>
        <p class="km-hero-copy">从 TXT、Markdown 和 PDF 自动抽取实体关系，结合 HybridRAG，让每个结论都能回到原文。</p>
        <div class="km-hero-actions">
          <a class="km-button km-button-primary" href="/guide/getting-started">
            <BookOpen :size="18" /> 快速开始 <ArrowRight :size="17" />
          </a>
          <a class="km-button km-button-secondary" href="https://github.com/Xikcn/KnowledgeMapNotes" target="_blank" rel="noreferrer">
            <Github :size="18" /> 查看源码
          </a>
        </div>
      </div>
      <div class="km-hero-meta">
        <span>Vue 3 + FastAPI</span>
        <span>HybridRAG</span>
        <span>AGPL-3.0</span>
      </div>
    </section>

    <section ref="storySection" class="km-story" aria-labelledby="km-story-title">
      <div class="km-story-sticky">
        <div class="km-story-shell">
          <div class="km-story-copy">
            <p class="km-story-kicker">FROM FILE TO ANSWER</p>
            <h2 id="km-story-title">一份文档，如何成为知识图谱</h2>
            <p class="km-story-intro">建图不是黑盒。滚动页面，处理过程会按真实顺序逐层展开。</p>

            <div class="km-stage-list" aria-label="文档处理流程">
              <button
                v-for="(stage, index) in storyStages"
                :key="stage.step"
                type="button"
                class="km-stage-nav"
                :class="{ active: index === activeStageIndex, complete: index < activeStageIndex }"
                :aria-current="index === activeStageIndex ? 'step' : undefined"
                @click="goToStage(index)"
              >
                <span>{{ stage.step }}</span>
                <strong>{{ stage.title }}</strong>
              </button>
            </div>
          </div>

          <div class="km-story-visual" :data-accent="activeStage.accent">
            <div class="km-story-progress" aria-hidden="true">
              <span :style="{ width: `${storyProgress * 100}%` }"></span>
            </div>
            <div class="km-story-visual-head">
              <div class="km-story-icon"><component :is="activeStage.icon" :size="22" :stroke-width="1.8" /></div>
              <div>
                <span>{{ activeStage.step }} / {{ activeStage.label }}</span>
                <strong>{{ activeStage.status }}</strong>
              </div>
            </div>

            <Transition name="km-stage-swap" mode="out-in">
              <div :key="activeStage.scene" class="km-scene">
                <div v-if="activeStage.scene === 'file'" class="km-scene-file">
                  <div class="km-file-sheet">
                    <span>PDF</span>
                    <FileText :size="54" :stroke-width="1.25" />
                    <i></i><i></i><i></i>
                  </div>
                  <div class="km-file-route"><ArrowRight :size="24" /></div>
                  <div class="km-inbox"><UploadCloud :size="34" /><strong>知识库</strong><span>任务已创建</span></div>
                </div>

                <div v-else-if="activeStage.scene === 'chunks'" class="km-scene-chunks">
                  <div v-for="index in 8" :key="index" class="km-chunk" :style="{ '--delay': `${index * 35}ms` }">
                    <span># {{ String(index).padStart(2, '0') }}</span><i></i><i></i><i></i>
                  </div>
                </div>

                <div v-else-if="activeStage.scene === 'entities'" class="km-scene-entities">
                  <p>KnowledgeMapNotes 使用 <mark>大模型</mark> 从 <mark>文档</mark> 中识别 <mark>实体</mark>，并为每个知识对象保留来源。</p>
                  <div><span>软件</span><span>技术</span><span>数据对象</span></div>
                </div>

                <div v-else-if="activeStage.scene === 'relations'" class="km-mini-network km-relations">
                  <span class="km-edge e1"></span><span class="km-edge e2"></span><span class="km-edge e3"></span>
                  <div class="km-node n1">文档</div><div class="km-node n2">实体</div><div class="km-node n3">关系</div><div class="km-node n4">来源</div>
                  <small class="km-relation-label l1">包含</small><small class="km-relation-label l2">提取</small>
                </div>

                <div v-else-if="activeStage.scene === 'fusion'" class="km-scene-fusion">
                  <div class="km-fusion-source"><span>KG Notes</span><span>知识图谱笔记</span><span>KnowledgeMap</span></div>
                  <div class="km-fusion-arrows"><ArrowRight :size="25" /><ArrowRight :size="25" /><ArrowRight :size="25" /></div>
                  <div class="km-fusion-result"><Combine :size="34" /><strong>KnowledgeMapNotes</strong><span>统一实体 · 9 个来源</span></div>
                </div>

                <div v-else-if="activeStage.scene === 'graph'" class="km-mini-network km-graph-scene">
                  <svg class="km-graph-links" viewBox="0 0 520 315" preserveAspectRatio="none" aria-hidden="true">
                    <line x1="247" y1="153" x2="51" y2="60" />
                    <line x1="247" y1="153" x2="469" y2="54" />
                    <line x1="247" y1="153" x2="66" y2="267" />
                    <line x1="247" y1="153" x2="454" y2="271" />
                    <line x1="247" y1="153" x2="459" y2="161" />
                    <line x1="51" y1="60" x2="66" y2="267" />
                    <line x1="469" y1="54" x2="459" y2="161" />
                    <line x1="459" y1="161" x2="454" y2="271" />
                  </svg>
                  <div class="km-graph-node gn1">知识图谱</div><div class="km-graph-node gn2">RAG</div><div class="km-graph-node gn3">文档</div>
                  <div class="km-graph-node gn4">实体</div><div class="km-graph-node gn5">关系</div><div class="km-graph-node gn6">社区</div>
                </div>

                <div v-else class="km-scene-rag">
                  <div class="km-question">这份文档的核心内容是什么？</div>
                  <div class="km-answer"><BrainCircuit :size="22" /><p>系统将文档转化为可探索的实体关系网络，并使用 HybridRAG 生成带出处的回答。</p></div>
                  <div class="km-sources"><span>来源 01 · 文本块 4</span><span>来源 02 · 关系“生成”</span><span>来源 03 · 社区 1</span></div>
                </div>
              </div>
            </Transition>

            <div class="km-story-caption">
              <span>{{ activeStage.step }}</span>
              <div><h3>{{ activeStage.title }}</h3><p>{{ activeStage.detail }}</p></div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="km-examples-band" aria-labelledby="km-examples-title">
      <div class="km-section km-examples">
        <div class="km-section-heading km-section-heading-left">
          <p>GRAPH GALLERY</p>
          <h2 id="km-examples-title">看看真实文档生成的图谱</h2>
          <span>每个示例都来自当前项目的处理结果。打开后可以缩放、搜索节点，并进入社区详情。</span>
        </div>
        <div class="km-example-grid">
          <article
            v-for="example in graphExamples"
            :key="example.id"
            class="km-example"
            :data-accent="example.accent"
            role="button"
            tabindex="0"
            :aria-label="`打开 ${example.name} 知识图谱`"
            @click="openExample(example)"
            @keydown.enter.prevent="openExample(example)"
            @keydown.space.prevent="openExample(example)"
          >
            <div class="km-example-cover">
              <img
                :src="withBase(example.coverUrl)"
                :title="`${example.name} 图谱封面`"
                :alt="`${example.name} 图谱封面`"
                loading="lazy"
              />
              <div class="km-example-cover-action"><Maximize2 :size="18" /><span>打开图谱</span></div>
            </div>
            <div class="km-example-info">
              <div><h3>{{ example.name }}</h3><p>{{ example.filename }}</p></div>
              <span>{{ example.pageCount }} 个视图 · {{ formatSize(example.sizeBytes) }}</span>
            </div>
          </article>
        </div>
      </div>
    </section>

    <section class="km-section km-intro">
      <div class="km-section-heading">
        <p>CORE CAPABILITIES</p>
        <h2>从资料导入到知识回溯，一处完成</h2>
        <span>不是只展示图谱，而是把处理、阅读、编辑、问答与迁移串成完整工作流。</span>
      </div>
      <div class="km-feature-grid">
        <a v-for="feature in features" :key="feature.title" :href="feature.link" class="km-feature">
          <div class="km-feature-icon"><component :is="feature.icon" :size="23" :stroke-width="1.8" /></div>
          <h3>{{ feature.title }}</h3>
          <p>{{ feature.detail }}</p>
          <span class="km-more">了解详情 <ArrowRight :size="15" /></span>
        </a>
      </div>
    </section>

    <section class="km-section km-cta">
      <div>
        <p>READY TO START?</p>
        <h2>从第一份文档开始</h2>
        <span>本地运行、数据自持，未配置文本模型也可以先体验内置说明。</span>
      </div>
      <a class="km-button km-button-primary" href="/guide/installation">
        查看安装指南 <ArrowRight :size="17" />
      </a>
    </section>

    <Teleport to="body">
      <div v-if="selectedExample" class="km-graph-modal" role="dialog" aria-modal="true" :aria-label="`${selectedExample.name} 知识图谱`" @click.self="closeExample">
        <div class="km-graph-dialog">
          <header>
            <div><span>GRAPH EXAMPLE</span><h2>{{ selectedExample.name }}</h2><p>{{ selectedExample.filename }}</p></div>
            <div class="km-dialog-actions">
              <a :href="withBase(selectedExample.graphUrl)" target="_blank" rel="noreferrer" title="在新窗口打开图谱"><ExternalLink :size="19" /><span>新窗口打开</span></a>
              <button ref="modalCloseButton" type="button" title="关闭图谱" aria-label="关闭图谱" @click="closeExample"><X :size="22" /></button>
            </div>
          </header>
          <div class="km-graph-frame">
            <iframe
              :src="withBase(selectedExample.graphUrl)"
              :title="`${selectedExample.name} 完整知识图谱`"
              sandbox="allow-scripts allow-same-origin allow-popups"
              allow="fullscreen"
              allowfullscreen
            ></iframe>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
