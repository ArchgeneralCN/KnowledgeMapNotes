<script setup>
import SideBar from "./components/SideBar.vue";
import {computed, ref, reactive, onMounted, onUnmounted, watch, nextTick} from "vue";
import SvgIcon from "@/components/SvgIcon/index.vue";
import {
  ArrowDown,
  ChatDotRound,
  Connection,
  CopyDocument,
  Document,
  Download,
  Hide,
  Loading,
  SuccessFilled,
  View
} from '@element-plus/icons-vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import DOMPurify from 'dompurify';
import MarkdownIt from 'markdown-it';
import api, { apiUrl, encodePathSegment, getApiErrorMessage } from '@/api/client';
import { themes, applyTheme } from '@/styles/theme';

const markdownRenderer = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true,
  typographer: true
});
const defaultLinkOpen = markdownRenderer.renderer.rules.link_open
  || ((tokens, index, options, env, self) => self.renderToken(tokens, index, options));
markdownRenderer.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index].attrSet('target', '_blank');
  tokens[index].attrSet('rel', 'noopener noreferrer');
  return defaultLinkOpen(tokens, index, options, env, self);
};

const sideBarRef = ref();
const fileListExpand = ref(false);
const isSearch = ref(false);
const searchValue = ref('');
const uploadFileList = ref([]);
const filteredFileList = ref([]);
const currentPage = ref(1);
const pageSize = 10;
const paginatedFileList = computed(() => {
  const start = (currentPage.value - 1) * pageSize;
  return filteredFileList.value.slice(start, start + pageSize);
});

// 新增顶部导航和视图控制
const activeView = ref('upload'); // 'upload', 'result'
const activeTab = ref('original'); // 'original', 'knowledge-graph', 'rag'
const currentFile = ref(null); // 当前选中的文件

// 面板显示状态
const panelVisible = reactive({
  original: true,
  'knowledge-graph': true,
  rag: true
});

const PANEL_ORDER = ['original', 'knowledge-graph', 'rag'];
const PANEL_LABELS = {
  original: '原文件',
  'knowledge-graph': '知识图谱',
  rag: 'RAG 问答'
};
const PANEL_MIN_WIDTH = 280;
const PANEL_RESIZER_WIDTH = 8;
const FILE_LIST_MIN_WIDTH = 260;
const FILE_LIST_MAX_WIDTH = 560;
const RESULT_AREA_MIN_WIDTH = 420;
const fileListWidth = ref(280);
const contentPanelsRef = ref(null);
const resizeMode = ref(null);
const panelWeights = reactive({
  original: 1,
  'knowledge-graph': 1,
  rag: 1
});
const visiblePanelKeys = computed(() => PANEL_ORDER.filter(panel => panelVisible[panel]));
const contentStyle = computed(() => ({
  marginLeft: fileListExpand.value ? `${fileListWidth.value}px` : '0'
}));

let activeResizeCleanup = null;
let panelResizeObserver = null;

const getPanelLabel = (panel) => PANEL_LABELS[panel] || panel;

const getNextVisiblePanel = (panel) => {
  const panelIndex = visiblePanelKeys.value.indexOf(panel);
  return panelIndex >= 0 ? visiblePanelKeys.value[panelIndex + 1] : null;
};

const getPanelStyle = (panel) => ({
  flex: `${panelWeights[panel]} 1 0px`,
  minWidth: `${PANEL_MIN_WIDTH}px`
});

const snapshotPanelWidths = () => {
  if (!contentPanelsRef.value) return;

  visiblePanelKeys.value.forEach(panel => {
    const panelElement = contentPanelsRef.value.querySelector(`[data-panel="${panel}"]`);
    if (panelElement) panelWeights[panel] = panelElement.getBoundingClientRect().width;
  });
};

const finishResizeSession = () => {
  activeResizeCleanup?.();
};

const startResizeSession = (mode, onMove, onEnd = () => {}) => {
  finishResizeSession();
  resizeMode.value = mode;
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';

  const finish = () => {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', finish);
    window.removeEventListener('pointercancel', finish);
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    resizeMode.value = null;
    activeResizeCleanup = null;
    onEnd();
  };

  activeResizeCleanup = finish;
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', finish);
  window.addEventListener('pointercancel', finish);
};

const getFileListMaxWidth = () => Math.max(
  FILE_LIST_MIN_WIDTH,
  Math.min(FILE_LIST_MAX_WIDTH, window.innerWidth - RESULT_AREA_MIN_WIDTH - 72)
);

const startFileListResize = (event) => {
  if (window.innerWidth <= 820) return;

  event.preventDefault();
  const startX = event.clientX;
  const startWidth = fileListWidth.value;

  startResizeSession('file-list', moveEvent => {
    const nextWidth = startWidth + moveEvent.clientX - startX;
    fileListWidth.value = Math.min(
      getFileListMaxWidth(),
      Math.max(FILE_LIST_MIN_WIDTH, nextWidth)
    );
  }, () => {
    localStorage.setItem('file-list-width', String(Math.round(fileListWidth.value)));
  });
};

const collapsePanel = (panel, notify = false) => {
  if (!panelVisible[panel] || visiblePanelKeys.value.length <= 1) return false;

  panelVisible[panel] = false;
  if (activeTab.value === panel) {
    activeTab.value = visiblePanelKeys.value[0];
  }
  if (notify) {
    ElMessage.info(`${getPanelLabel(panel)}宽度低于 ${PANEL_MIN_WIDTH}px，已自动隐藏`);
  }

  nextTick(snapshotPanelWidths);
  return true;
};

const ensurePanelsFit = () => {
  const container = contentPanelsRef.value;
  if (!container || window.innerWidth <= 820 || resizeMode.value === 'panel') return;

  const visiblePanels = visiblePanelKeys.value;
  const requiredWidth = visiblePanels.length * PANEL_MIN_WIDTH
    + Math.max(0, visiblePanels.length - 1) * PANEL_RESIZER_WIDTH;
  if (visiblePanels.length <= 1 || container.clientWidth >= requiredWidth) return;

  const panelToHide = [...visiblePanels].reverse().find(panel => panel !== activeTab.value)
    || visiblePanels[visiblePanels.length - 1];
  if (collapsePanel(panelToHide)) nextTick(ensurePanelsFit);
};

const startPanelResize = (event, leftPanel) => {
  const rightPanel = getNextVisiblePanel(leftPanel);
  const container = contentPanelsRef.value;
  if (!rightPanel || !container || window.innerWidth <= 820) return;

  const leftElement = container.querySelector(`[data-panel="${leftPanel}"]`);
  const rightElement = container.querySelector(`[data-panel="${rightPanel}"]`);
  if (!leftElement || !rightElement) return;

  event.preventDefault();
  snapshotPanelWidths();
  const startX = event.clientX;
  const startLeftWidth = leftElement.getBoundingClientRect().width;
  const startRightWidth = rightElement.getBoundingClientRect().width;

  startResizeSession('panel', moveEvent => {
    const delta = moveEvent.clientX - startX;
    const leftWidth = startLeftWidth + delta;
    const rightWidth = startRightWidth - delta;

    if (leftWidth < PANEL_MIN_WIDTH) {
      collapsePanel(leftPanel, true);
      finishResizeSession();
      return;
    }
    if (rightWidth < PANEL_MIN_WIDTH) {
      collapsePanel(rightPanel, true);
      finishResizeSession();
      return;
    }

    panelWeights[leftPanel] = leftWidth;
    panelWeights[rightPanel] = rightWidth;
  });
};

watch(contentPanelsRef, container => {
  panelResizeObserver?.disconnect();
  panelResizeObserver = null;

  if (container && typeof ResizeObserver !== 'undefined') {
    panelResizeObserver = new ResizeObserver(ensurePanelsFit);
    panelResizeObserver.observe(container);
    nextTick(ensurePanelsFit);
  }
});

// RAG聊天相关
const chatMessages = ref([
]);
const userInput = ref('');
const chatLoading = ref(false);
const currentChatFile = ref(null); // 当前正在聊天的文件
const abortController = ref(null); // 用于取消请求的控制器
const fileChatStates = ref({}); // 存储每个文件的聊天状态
const processingTimers = new Map();
let knowledgeGraphRequestId = 0;
let knowledgeGraphReadyTimer = null;
const fileContextMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  file: null
});

const closeFileContextMenu = () => {
  fileContextMenu.visible = false;
  fileContextMenu.file = null;
};

const openFileContextMenu = (event, file) => {
  event.preventDefault();
  event.stopPropagation();
  const menuWidth = 176;
  const menuHeight = 300;
  fileContextMenu.file = file;
  fileContextMenu.x = Math.max(8, Math.min(event.clientX, window.innerWidth - menuWidth - 8));
  fileContextMenu.y = Math.max(8, Math.min(event.clientY, window.innerHeight - menuHeight - 8));
  fileContextMenu.visible = true;
};

// 添加文件内容相关状态
const fileContent = ref('');
const fileContentLoading = ref(false);
const evidenceResults = ref([]);
const activeEvidenceIndex = ref(0);
const evidenceKind = ref('node');
const sourceHighlightHtml = ref('');
const documentContentRef = ref(null);
let evidenceRequestId = 0;
const contentViewMode = ref('preview');
const contentViewOptions = [
  { label: '预览', value: 'preview' },
  { label: '源码', value: 'source' }
];
const renderedFileContent = computed(() => DOMPurify.sanitize(
  markdownRenderer.render(fileContent.value || ''),
  { ADD_ATTR: ['target'] }
));
const fileContentStats = computed(() => {
  if (!fileContent.value) return '';
  const characters = fileContent.value.replace(/\s/g, '').length;
  const lines = fileContent.value.split(/\r?\n/).length;
  return `${characters.toLocaleString()} 字 · ${lines.toLocaleString()} 行`;
});

const activeEvidence = computed(() => evidenceResults.value[activeEvidenceIndex.value] || null);

const escapeDocumentHtml = (value) => String(value ?? '').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[character]));

const getGraphName = (filename) => {
  const name = String(filename || '');
  const lastDot = name.lastIndexOf('.');
  return lastDot > 0 ? name.slice(0, lastDot) : name;
};

const makeSourceHighlight = (result) => {
  if (!result || result.start < 0 || result.end <= result.start) return '';
  const content = fileContent.value;
  const html = `${escapeDocumentHtml(content.slice(0, result.start))}`
    + `<mark class="source-highlight">${escapeDocumentHtml(content.slice(result.start, result.end))}</mark>`
    + `${escapeDocumentHtml(content.slice(result.end))}`;
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['mark'],
    ALLOWED_ATTR: ['class']
  });
};

const jumpToEvidence = (index) => {
  if (!evidenceResults.value.length) return;
  const normalizedIndex = (index + evidenceResults.value.length) % evidenceResults.value.length;
  activeEvidenceIndex.value = normalizedIndex;
  contentViewMode.value = 'source';
  sourceHighlightHtml.value = makeSourceHighlight(evidenceResults.value[normalizedIndex]);
  nextTick(() => {
    const highlight = documentContentRef.value?.querySelector('.source-highlight');
    highlight?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
};

const locateEvidenceResults = (sourceBlocks, blocks) => {
  const content = fileContent.value || '';
  const normalizedBlocks = (Array.isArray(blocks) ? blocks : [])
    .filter(block => block && typeof block === 'object');
  const blockById = new Map(normalizedBlocks.map((block, index) => [String(block.bid), { ...block, index }]));
  const references = (Array.isArray(sourceBlocks) ? sourceBlocks : [])
    .map(reference => {
      if (reference && typeof reference === 'object') {
        return {
          bid: String(reference.source_block || reference.bid || ''),
          evidence: reference.evidence || '',
          score: reference.score
        };
      }
      return { bid: String(reference || ''), evidence: '', score: null };
    })
    .filter(reference => reference.bid && blockById.has(reference.bid));

  const uniqueReferences = references.filter((reference, index, all) =>
    all.findIndex(candidate => candidate.bid === reference.bid) === index
  );
  // Build positions against every block in document order. Searching only the
  // selected results could mistake a repeated block for an earlier occurrence.
  let searchOffset = 0;
  const positionsById = new Map();
  normalizedBlocks.forEach(block => {
    const text = String(block.text || '');
    let start = text ? content.indexOf(text, searchOffset) : -1;
    if (start < 0 && text) start = content.indexOf(text);
    const end = start >= 0 ? start + text.length : -1;
    if (start >= 0) searchOffset = end;
    positionsById.set(String(block.bid), { start, end });
  });

  return uniqueReferences.map(reference => {
    const block = blockById.get(reference.bid);
    const text = String(block.text || '');
    const position = positionsById.get(reference.bid) || { start: -1, end: -1 };
    return {
      ...reference,
      text,
      index: block.index,
      start: position.start,
      end: position.end,
      preview: text.replace(/\s+/g, ' ').trim().slice(0, 180)
    };
  }).sort((left, right) => left.index - right.index);
};

const handleKnowledgeGraphEvidence = async (event) => {
  if (
    event.data?.type !== 'knowledge-graph-evidence'
    || event.source !== knowledgeGraphFrameRef.value?.contentWindow
  ) return;

  const filename = currentFile.value?.name;
  if (!filename) return;
  const expectedGraphName = getGraphName(filename);
  if (event.data.graphName && event.data.graphName !== expectedGraphName) return;

  const requestId = ++evidenceRequestId;
  try {
    if (!fileContent.value) await loadFileContent(currentFile.value);
    const response = await api.get(`/graph-sources/${encodePathSegment(filename)}`);
    if (requestId !== evidenceRequestId) return;
    const results = locateEvidenceResults(event.data.sourceBlocks, response.data?.blocks || []);
    evidenceResults.value = results;
    evidenceKind.value = event.data.kind === 'edge' ? 'edge' : 'node';
    activeEvidenceIndex.value = 0;
    sourceHighlightHtml.value = '';
    panelVisible.original = true;
    activeTab.value = 'original';
    contentViewMode.value = 'source';
    nextTick(() => {
      if (results.length) jumpToEvidence(0);
      else ElMessage.info('该节点或关系暂无可定位的出处文本块');
    });
  } catch (error) {
    if (requestId === evidenceRequestId) {
      evidenceResults.value = [];
      sourceHighlightHtml.value = '';
      ElMessage.warning(getApiErrorMessage(error, '加载出处文本块失败'));
    }
  }
};

// 在 script setup 部分添加
const knowledgeGraphUrl = ref(null);
const knowledgeGraphLoading = ref(false);
const knowledgeGraphFrameRef = ref(null);
const ragReferenceData = ref({ nodes: [], links: [], blocks: [] });
let ragReferenceRequestId = 0;

const loadRagReferenceData = async (filename) => {
  if (!filename) return;
  const requestId = ++ragReferenceRequestId;
  try {
    const [graphResponse, sourceResponse] = await Promise.all([
      api.get(`/graph-data/${encodePathSegment(filename)}`),
      api.get(`/graph-sources/${encodePathSegment(filename)}`)
    ]);
    if (requestId !== ragReferenceRequestId || currentFile.value?.name !== filename) return;
    ragReferenceData.value = {
      nodes: graphResponse.data?.nodes || [],
      links: graphResponse.data?.links || [],
      blocks: sourceResponse.data?.blocks || []
    };
  } catch (error) {
    if (requestId === ragReferenceRequestId) {
      ragReferenceData.value = { nodes: [], links: [], blocks: [] };
      console.warn('加载 RAG 图谱引用数据失败:', error);
    }
  }
};

const finishKnowledgeGraphLoading = () => {
  if (knowledgeGraphReadyTimer) clearTimeout(knowledgeGraphReadyTimer);
  knowledgeGraphReadyTimer = null;
  knowledgeGraphLoading.value = false;
};

const handleKnowledgeGraphReadyMessage = (event) => {
  if (
    event.data?.type === 'knowledge-graph-ready'
    && event.source === knowledgeGraphFrameRef.value?.contentWindow
  ) {
    finishKnowledgeGraphLoading();
  }
  handleKnowledgeGraphEvidence(event);
};

const handleKnowledgeGraphFrameLoad = () => {
  // New graph pages notify after their first canvas draw. Keep a short fallback
  // for graph packages created by older versions that do not send the event.
  if (knowledgeGraphReadyTimer) clearTimeout(knowledgeGraphReadyTimer);
  knowledgeGraphReadyTimer = setTimeout(finishKnowledgeGraphLoading, 1800);
};

// 修改主题相关状态
const themeOptions = [
  { name: '默认主题', value: 'default' },
  { name: '暗色主题', value: 'dark' },
  { name: '蓝色主题', value: 'blue' },
  { name: '护眼主题', value: 'green' }
];
const currentTheme = ref('default');

// 添加RAG流式输出开关设置
const enableStreamOutput = ref(false);
// 添加PDF图片文本识别设置
const useImg2txt = ref(false);
// 添加笔记类型设置
const noteType = ref('general');
const emptyCustomPrompts = {
  entityExtraction: '',
  relationshipExtraction: '',
  knowledgeFusion: ''
};
const loadCustomPrompts = () => {
  try {
    const saved = JSON.parse(localStorage.getItem('custom-processing-prompts') || '{}');
    return {
      entityExtraction: typeof saved.entityExtraction === 'string' ? saved.entityExtraction : '',
      relationshipExtraction: typeof saved.relationshipExtraction === 'string' ? saved.relationshipExtraction : '',
      knowledgeFusion: typeof saved.knowledgeFusion === 'string' ? saved.knowledgeFusion : ''
    };
  } catch {
    return { ...emptyCustomPrompts };
  }
};
const customPrompts = ref(loadCustomPrompts());

watch(customPrompts, value => {
  localStorage.setItem('custom-processing-prompts', JSON.stringify(value));
}, { deep: true });

// 保存和获取流式输出设置
const saveStreamSetting = () => {
  localStorage.setItem('rag-stream-output', enableStreamOutput.value ? 'true' : 'false');
};

// 保存图片文本识别设置
const saveImg2txtSetting = () => {
  localStorage.setItem('use-img2txt', useImg2txt.value ? 'true' : 'false');
};

// 自动滚动到底部功能
const chatMessagesContainer = ref(null);
const showScrollButton = ref(false);
const autoScroll = ref(true);

// 添加流式处理状态变量
const streamingStatus = ref('');

// 监听聊天消息区域的滚动事件
const handleChatScroll = () => {
  if (!chatMessagesContainer.value) return;

  const container = chatMessagesContainer.value;
  const isScrolledToBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 100;

  // 只有当用户手动上滑时才禁用自动滚动
  if (!isScrolledToBottom && !chatLoading.value) {
    autoScroll.value = false;
    showScrollButton.value = true;
  } else if (isScrolledToBottom) {
    autoScroll.value = true;
    showScrollButton.value = false;
  }
};

// 滚动到底部函数
const scrollToBottom = () => {
  if (!chatMessagesContainer.value) return;

  nextTick(() => {
    chatMessagesContainer.value.scrollTop = chatMessagesContainer.value.scrollHeight;
    autoScroll.value = true;
    showScrollButton.value = false;
  });
};

// 修改主题切换函数
const changeTheme = (theme) => {
  currentTheme.value = theme;
  applyTheme(theme);
  localStorage.setItem('app-theme', theme);
};

// 获取知识图谱数据
const fetchKnowledgeGraph = async (filename) => {
  if (!filename) {
    console.error('文件名不能为空');
    return;
  }

  const requestId = ++knowledgeGraphRequestId;

  try {
    knowledgeGraphLoading.value = true;
    if (knowledgeGraphReadyTimer) clearTimeout(knowledgeGraphReadyTimer);

    // Use the directory-shaped page URL as the iframe document URL. Community
    // links remain valid even when an older backend returns an empty <base>.
    localStorage.removeItem(`kg_${filename}`);
    if (requestId === knowledgeGraphRequestId) {
      const lastDot = filename.lastIndexOf('.');
      const graphName = lastDot > 0 && lastDot < filename.length - 1
        ? filename.slice(0, lastDot)
        : filename;
      const mainPageName = `${graphName}.html`;
      knowledgeGraphUrl.value = apiUrl(
        `/result-page/${encodePathSegment(graphName)}/${encodePathSegment(mainPageName)}`
      ) + '?graph-editor=1';
    }
  } catch (error) {
    console.error('获取知识图谱失败:', error);
    finishKnowledgeGraphLoading();
    ElMessage.error('获取知识图谱失败');
  }
};

// 格式化文本，确保正确显示换行符
const formatTextWithLineBreaks = (text) => {
  if (!text) return '';
  if (Array.isArray(text)) {
    return text.join('\n');
  }
  return text;
};

const addRagReferenceCandidate = (candidates, seen, label, payload, priority = 0) => {
  const normalizedLabel = String(label || '').trim();
  if (normalizedLabel.length < 2 || seen.has(`${payload.kind}:${payload.id}:${normalizedLabel}`)) return;
  seen.add(`${payload.kind}:${payload.id}:${normalizedLabel}`);
  candidates.push({ label: normalizedLabel, payload, priority });
};

const getRagReferenceCandidates = (text) => {
  const data = ragReferenceData.value;
  const candidates = [];
  const seen = new Set();
  const links = Array.isArray(data.links) ? data.links : [];

  (Array.isArray(data.blocks) ? data.blocks : []).forEach(block => {
    const blockText = String(block.text || '').trim();
    if (!blockText || !String(text || '').includes(blockText)) return;
    addRagReferenceCandidate(candidates, seen, blockText, {
      kind: 'evidence', id: String(block.bid), sourceBlocks: [String(block.bid)]
    }, 100);
  });

  links.forEach(link => {
    const sourceBlocks = link.evidence_blocks || (link.source_block ? [link.source_block] : []);
    const payload = { kind: 'edge', id: String(link.id), sourceBlocks };
    const source = String(link.source || '');
    const target = String(link.target || '');
    const relation = String(link.relation || '');
    const context = String(link.context || link.evidence || '');
    const weight = link.weight ?? link.score ?? '';
    [
      `Edge from ${source} to ${target}, Relation: ${relation}, context:${context}, weight:${weight}`,
      `Edge from ${source} to ${target}, Relation: ${relation}, context:${context}`,
      `${source} -> ${target}，${relation}`
    ].forEach(label => {
      if (String(text || '').includes(label)) addRagReferenceCandidate(candidates, seen, label, payload, 90);
    });
    if (String(text || '').includes(relation)) {
      addRagReferenceCandidate(candidates, seen, relation, payload, 60);
    }
  });

  (Array.isArray(data.nodes) ? data.nodes : []).forEach(node => {
    const name = String(node.name || node.id || '');
    if (String(text || '').includes(name)) {
      addRagReferenceCandidate(candidates, seen, name, {
        kind: 'node', id: String(node.id), sourceBlocks: node.source_blocks || []
      }, 30);
    }
  });
  return candidates;
};

const renderRagContent = (content) => {
  const text = formatTextWithLineBreaks(content);
  if (!text) return '';
  const candidates = getRagReferenceCandidates(text);
  const ranges = [];
  candidates
    .sort((left, right) => right.label.length - left.label.length || right.priority - left.priority)
    .forEach(candidate => {
      let from = 0;
      while (from < text.length) {
        const start = text.indexOf(candidate.label, from);
        if (start < 0) break;
        const end = start + candidate.label.length;
        if (!ranges.some(range => start < range.end && end > range.start)) {
          ranges.push({ start, end, label: candidate.label, payload: candidate.payload });
        }
        from = end;
      }
    });
  ranges.sort((left, right) => left.start - right.start);
  let cursor = 0;
  return ranges.map(range => {
    const payload = encodeURIComponent(JSON.stringify(range.payload));
    const html = escapeDocumentHtml(text.slice(cursor, range.start))
      + `<a href="#" class="rag-reference" data-reference="${payload}">${escapeDocumentHtml(range.label)}</a>`;
    cursor = range.end;
    return html;
  }).join('') + escapeDocumentHtml(text.slice(cursor));
};

const postGraphHighlight = (kind, id) => {
  if (!knowledgeGraphFrameRef.value?.contentWindow || !currentFile.value?.name) return;
  knowledgeGraphFrameRef.value.contentWindow.postMessage({
    type: 'knowledge-graph-highlight',
    graphName: getGraphName(currentFile.value.name),
    kind,
    id: String(id)
  }, '*');
};

const handleRagReferenceClick = (event) => {
  const link = event.target?.closest?.('.rag-reference');
  if (!link) return;
  event.preventDefault();
  let reference;
  try {
    reference = JSON.parse(decodeURIComponent(link.dataset.reference || ''));
  } catch {
    return;
  }
  const data = ragReferenceData.value;
  const sourceBlocks = reference.sourceBlocks || [];
  const blockIds = new Set(sourceBlocks.map(block =>
    String(typeof block === 'object' ? block.source_block || block.bid || '' : block)
  ));
  let graphTarget = reference.kind === 'edge' ? { kind: 'edge', id: reference.id } : null;
  if (reference.kind === 'evidence') {
    const edge = (data.links || []).find(item =>
      (item.evidence_blocks || []).some(item => blockIds.has(String(item.source_block || item.bid || item)))
    );
    const node = (data.nodes || []).find(item =>
      (item.source_blocks || []).some(block => blockIds.has(String(block)))
    );
    graphTarget = edge
      ? { kind: 'edge', id: edge.id }
      : node ? { kind: 'node', id: node.id } : null;
  }
  if (graphTarget) postGraphHighlight(graphTarget.kind, graphTarget.id);
  if (!sourceBlocks.length || !data.blocks.length) return;

  const results = locateEvidenceResults(sourceBlocks, data.blocks);
  evidenceResults.value = results;
  evidenceKind.value = reference.kind === 'edge' ? 'edge' : 'node';
  activeEvidenceIndex.value = 0;
  panelVisible.original = true;
  activeTab.value = 'original';
  contentViewMode.value = 'source';
  nextTick(() => {
    if (results.length) jumpToEvidence(0);
    else ElMessage.info('该引用暂无可定位的原文文本块');
  });
};

const copyFileContent = async () => {
  if (!fileContent.value) return;
  try {
    await navigator.clipboard.writeText(fileContent.value);
    ElMessage.success('内容已复制');
  } catch (error) {
    console.error('复制文件内容失败:', error);
    ElMessage.error('复制失败，请切换到源码后手动复制');
  }
};

const downloadFileContent = () => {
  if (!fileContent.value) return;

  const currentName = currentFile.value?.name || 'document.md';
  const lastDot = currentName.lastIndexOf('.');
  const extension = lastDot > -1 ? currentName.slice(lastDot).toLowerCase() : '';
  const baseName = lastDot > 0 ? currentName.slice(0, lastDot) : currentName;
  const downloadName = ['.md', '.markdown', '.txt'].includes(extension)
    ? currentName
    : `${baseName}.md`;
  const blob = new Blob([fileContent.value], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = downloadName;
  link.click();
  URL.revokeObjectURL(url);
};

// 从localStorage加载聊天历史
const loadChatHistory = (filename) => {
  if (!filename) return;

  try {
    const savedChat = localStorage.getItem(`chat_${filename}`);
    if (savedChat) {
      const parsed = JSON.parse(savedChat);
      // 确保内容格式正确
      chatMessages.value = parsed.map(msg => {
        if (msg.role === 'assistant' && typeof msg.content === 'object') {
          return {
            ...msg,
            content: {
              answer: formatTextWithLineBreaks(msg.content.answer),
              material: formatTextWithLineBreaks(msg.content.material)
            }
          };
        }
        return msg;
      });
    } else {
      chatMessages.value = [];
    }
  } catch (error) {
    console.error('加载聊天历史失败:', error);
    chatMessages.value = [];
  }
};

// 页面加载时获取历史文件列表
onMounted(async () => {
  window.addEventListener('click', closeFileContextMenu);
  window.addEventListener('blur', closeFileContextMenu);
  window.addEventListener('resize', closeFileContextMenu);
  window.addEventListener('scroll', closeFileContextMenu, true);
  window.addEventListener('message', handleKnowledgeGraphReadyMessage);
  const savedFileListWidth = Number(localStorage.getItem('file-list-width'));
  if (Number.isFinite(savedFileListWidth)) {
    fileListWidth.value = Math.min(
      getFileListMaxWidth(),
      Math.max(FILE_LIST_MIN_WIDTH, savedFileListWidth)
    );
  }

  try {
    // 初始化主题
    const savedTheme = localStorage.getItem('app-theme') || 'default';
    changeTheme(savedTheme);

    // 加载流式输出设置
    const savedStreamSetting = localStorage.getItem('rag-stream-output');
    enableStreamOutput.value = savedStreamSetting === 'true';

    // 加载图片文本识别设置
    const savedImg2txtSetting = localStorage.getItem('use-img2txt');
    useImg2txt.value = savedImg2txtSetting === 'true';

    const response = await api.get('/list-files');
    if (response.data && Array.isArray(response.data.files)) {
      // 将历史文件添加到文件列表，保持原始文件名和状态
      uploadFileList.value = response.data.files.map(file => ({
        name: file.filename || file.name || file,  // 保持原始文件名
        status: file.status || 'completed',
        display_status: file.display_status || (file.status ? getStatusText(file.status) : '已完成'),
        size: file.size || 0,
        percentage: file.percentage ?? (file.status === 'completed' ? 100 : 0),
        completedChunks: file.completed_chunks || 0,
        totalChunks: file.total_chunks || 0,
        latestChunkSeconds: file.latest_chunk_seconds,
        estimatedRemainingSeconds: file.estimated_remaining_seconds,
        partialAvailable: Boolean(file.partial_available),
        resumable: Boolean(file.resumable),
        errorMessage: file.error_message || ''
      }));

      // 初始化过滤后的文件列表
      filteredFileList.value = [...uploadFileList.value];

      // 检查是否有未完成的文件
      uploadFileList.value.forEach(file => {
        // 包括所有处理中状态
        const processingStatuses = [
          'uploading', 'processing', 'updating', 'resuming', 'pausing'
        ];

        if (processingStatuses.includes(file.status)) {
          checkFileProcessingStatus(file);
        }
      });
    }
  } catch (error) {
    console.error('获取历史文件列表失败:', error);
    ElMessage.error('获取历史文件列表失败');
  }
});

// 删除文件
const deleteFile = async (file) => {
  try {
    // 添加确认弹窗
    await ElMessageBox.confirm(
        `确定要删除文件 ${file.name} 吗？此操作将同时删除相关的聊天记录和知识图谱。`,
        '删除确认',
        {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning',
        }
    );

    await api.delete(`/delete/${encodePathSegment(file.name)}`);
    stopFileStatusPolling(file.name);

    // 从列表中移除文件
    const index = uploadFileList.value.findIndex(item => item.name === file.name);
    if (index !== -1) {
      uploadFileList.value.splice(index, 1);
    }

    // 清理本地缓存
    localStorage.removeItem(`kg_${file.name}`);  // 删除知识图谱数据
    localStorage.removeItem(`chat_${file.name}`);  // 删除聊天记录

    // 清理聊天状态
    if (fileChatStates.value[file.name]) {
      delete fileChatStates.value[file.name];
    }

    // 如果删除的是当前查看的文件，关闭结果视图
    if (currentFile.value && currentFile.value.name === file.name) {
      closeResultView();
    }

    ElMessage.success(`文件 ${file.name} 已删除`);
  } catch (error) {
    if (error !== 'cancel') {  // 如果不是用户取消操作
      console.error('删除文件失败:', error);
      ElMessage.error('删除文件失败');
    }
  }
};

// 删除RAG历史记录功能
const deleteRagHistory = async (file, event) => {
  // 阻止事件冒泡，防止触发文件查看
  event?.stopPropagation();

  try {
    // 添加确认弹窗
    await ElMessageBox.confirm(
        `确定要清除文件 ${file.name} 的RAG聊天记录吗？此操作不会删除文件和知识图谱。`,
        '清除RAG历史',
        {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning',
        }
    );

    // 调用后端API删除RAG历史
    await api.delete(`/rag-history/${encodePathSegment(file.name)}`);

    // 清理本地缓存
    localStorage.removeItem(`chat_${file.name}`);  // 删除本地聊天记录

    // 清理聊天状态
    if (fileChatStates.value[file.name]) {
      delete fileChatStates.value[file.name];
    }

    // 如果当前正在查看该文件的RAG，清空聊天消息
    if (currentFile.value && currentFile.value.name === file.name) {
      chatMessages.value = [];
    }

    ElMessage.success(`文件 ${file.name} 的RAG历史记录已清除`);
  } catch (error) {
    if (error !== 'cancel') {  // 如果不是用户取消操作
      console.error('清除RAG历史记录失败:', error);
      ElMessage.error('清除RAG历史记录失败');
    }
  }
};

// 添加停止RAG回答的函数
const stopRagResponse = () => {
  if (abortController.value) {
    abortController.value.abort();
    abortController.value = null;
    chatLoading.value = false;
    // 移除未完成的回答，避免将半截内容保存为历史记录。
    chatMessages.value = chatMessages.value.filter(msg => !msg.thinking && !msg.streaming);
    ElMessage.info('已停止回答');
  }
};

// 处理流式输出的函数 - 使用 EventSource
const processStreamResponse = async (url, data, messageIndex) => {
  try {
    chatLoading.value = true;
    streamingStatus.value = '准备连接...';

    // 创建一个新的AbortController
    abortController.value = new AbortController();

    // 直接以POST方式发送数据
    const postResponse = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
      signal: abortController.value.signal
    });

    if (!postResponse.ok) {
      const errorText = await postResponse.text();
      throw new Error(`HTTP error! status: ${postResponse.status}, message: ${errorText}`);
    }

    streamingStatus.value = '已连接，等待响应...';
    const reader = postResponse.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    // 开始读取流数据
    while (true) {
      if (!abortController.value) break; // 如果已中断，退出循环

      const { done, value } = await reader.read();
      if (done) break;

      // 解码收到的数据
      buffer += decoder.decode(value, { stream: true });

      // 处理SSE格式的数据
      const lines = buffer.split(/\r?\n\r?\n/);
      buffer = lines.pop() || ''; // 最后一行可能不完整，保留到下一次处理

      for (const line of lines) {
        const payload = line
          .split(/\r?\n/)
          .filter(item => item.startsWith('data:'))
          .map(item => item.slice(5).trimStart())
          .join('\n');
        if (!payload) continue;

        try {
          const eventData = JSON.parse(payload);

          // 根据不同类型的消息进行处理
          if (eventData.type === 'status') {
            // 在UI上显示当前处理状态
            streamingStatus.value = eventData.content;
          }
          else if (eventData.type === 'content') {
            // 更新聊天内容
            if (messageIndex !== -1 && chatMessages.value[messageIndex]) {
              // 确保正确处理换行符
              let formattedContent = eventData.full;
              // 如果内容是字符串数组，用换行符连接
              if (Array.isArray(formattedContent)) {
                formattedContent = formattedContent.join('\n');
              }
              chatMessages.value[messageIndex].content.answer = formattedContent;

              // 自动滚动到底部
              if (autoScroll.value) {
                scrollToBottom();
              }
            }
          }
          else if (eventData.type === 'final') {
            // 接收最终结果，包括答案和参考资料
            if (messageIndex !== -1 && chatMessages.value[messageIndex]) {
              // 检查响应内容是否为JSON格式
              let finalAnswer = eventData.answer;
              let finalMaterial = eventData.material;

              // 使用正则表达式匹配```json和```之间的内容
              const jsonRegex = /```json\s*([\s\S]*?)\s*```/;


              if (typeof finalAnswer === 'string') {
                const jsonMatch = finalAnswer.match(jsonRegex);
                if (jsonMatch && jsonMatch[1]) {
                  try {
                    const jsonContent = JSON.parse(jsonMatch[1]);
                    if (jsonContent.answer) {
                      // 如果answer是数组，则将其连接为字符串
                      if (Array.isArray(jsonContent.answer)) {
                        finalAnswer = jsonContent.answer.join('\n');
                      } else {
                        finalAnswer = jsonContent.answer;
                      }
                    }

                    // 检查material是否存在且非空
                    if (jsonContent.material) {
                      if (Array.isArray(jsonContent.material) && jsonContent.material.length > 0) {
                        finalMaterial = jsonContent.material.join('\n');
                      } else if (typeof jsonContent.material === 'string' && jsonContent.material.trim() !== '') {
                        finalMaterial = jsonContent.material;
                      } else {
                        finalMaterial = '';
                      }
                    } else {
                      finalMaterial = '';
                    }
                  } catch (e) {
                    console.warn('无法解析JSON代码块内容:', e);
                  }
                } else if (finalAnswer.trim().startsWith('{') && finalAnswer.trim().endsWith('}')) {
                  // 尝试直接解析可能的JSON字符串
                  try {
                    const jsonContent = JSON.parse(finalAnswer);
                    if (jsonContent.answer) {
                      if (Array.isArray(jsonContent.answer)) {
                        finalAnswer = jsonContent.answer.join('\n');
                      } else {
                        finalAnswer = jsonContent.answer;
                      }
                    }

                    if (jsonContent.material) {
                      if (Array.isArray(jsonContent.material) && jsonContent.material.length > 0) {
                        finalMaterial = jsonContent.material.join('\n');
                      } else if (typeof jsonContent.material === 'string' && jsonContent.material.trim() !== '') {
                        finalMaterial = jsonContent.material;
                      } else {
                        finalMaterial = '';
                      }
                    } else {
                      finalMaterial = '';
                    }
                  } catch (e) {
                    console.warn('无法解析answer中的JSON内容:', e);
                  }
                }
              }

              // 更新聊天消息
              chatMessages.value[messageIndex].content.answer = finalAnswer;
              if (finalMaterial && finalMaterial.trim() !== '') {
                chatMessages.value[messageIndex].content.material = finalMaterial;
              } else {
                // 如果material为空则不显示
                chatMessages.value[messageIndex].content.material = '';
              }
              chatMessages.value[messageIndex].streaming = false;

              // 自动滚动到底部
              if (autoScroll.value) {
                scrollToBottom();
              }

              // 保存聊天记录到localStorage
              if (currentFile.value?.name) {
                const chatHistory = chatMessages.value.filter(msg => !msg.thinking && !msg.streaming);
                localStorage.setItem(`chat_${currentFile.value.name}`, JSON.stringify(chatHistory));
              }
            }
          }
          else if (eventData.type === 'error') {
            // 处理错误
            console.error('Stream error:', eventData.content);
            ElMessage.error(eventData.content || '获取回复失败');
          }
          else if (eventData.type === 'done') {
            // 处理完成
            // console.log('Stream completed');
            streamingStatus.value = '';
            break;
          }
        } catch (e) {
          console.error('Error parsing SSE data:', e, line);
        }
      }
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      // 请求被中断，不处理
      console.log('Stream aborted by user');
      streamingStatus.value = '已停止生成';
      setTimeout(() => {
        streamingStatus.value = '';
      }, 2000);
      return;
    }

    console.error('流式输出处理失败:', error);
    ElMessage.error(error.message || '获取回复失败');
    streamingStatus.value = '';

    // 移除流式输出消息
    if (messageIndex !== -1 && chatMessages.value[messageIndex]) {
      chatMessages.value.splice(messageIndex, 1);
    }
  } finally {
    chatLoading.value = false;
    abortController.value = null;
  }
};

// 修改RAG请求函数
const sendMessage = async () => {
  if (!userInput.value.trim() || chatLoading.value) return;

  // 首先检查是否有选中的文件
  if (!currentFile.value?.name) {
    ElMessage.error('请先选择一个文件');
    return;
  }
  if (!ragReferenceData.value.links.length && !ragReferenceData.value.blocks.length) {
    loadRagReferenceData(currentFile.value.name);
  }

  // 如果切换了文件，保存当前文件的聊天记录
  if (currentChatFile.value && currentChatFile.value !== currentFile.value.name) {
    const chatHistory = chatMessages.value.filter(msg => !msg.thinking && !msg.streaming);
    localStorage.setItem(`chat_${currentChatFile.value}`, JSON.stringify(chatHistory));
  }

  // 更新当前聊天文件
  currentChatFile.value = currentFile.value.name;

  chatMessages.value.push({ role: 'user', content: userInput.value });
  const currentQuestion = userInput.value;
  userInput.value = '';
  chatLoading.value = true;

  // 处理历史消息，确保格式正确
  const historyMessages = chatMessages.value
      .filter(msg => !msg.thinking && !msg.streaming && msg.role !== 'system')
      .map(msg => {
        if (msg.role === 'assistant' && typeof msg.content === 'object') {
          return {
            role: msg.role,
            content: Array.isArray(msg.content.answer)
                ? msg.content.answer.join('\n')
                : msg.content.answer
          };
        }
        return {
          role: msg.role,
          content: msg.content
        };
      });

  // 添加思考中的消息或初始化流式输出的容器
  if (enableStreamOutput.value) {
    // 流式输出模式，显示初始化的空消息
    chatMessages.value.push({
      role: 'assistant',
      content: {
        answer: '',
        material: ''
      },
      streaming: true // 标记为流式输出中
    });

    // 启用自动滚动
    autoScroll.value = true;
    // 自动滚动到底部
    scrollToBottom();

    // 使用流式处理函数，连接到新的流式端点
    const streamingIndex = chatMessages.value.length - 1;
    await processStreamResponse(apiUrl('/hybridrag/stream'), {
      request: currentQuestion,
      flow: true,
      filename: currentFile.value.name,
      messages: enableHistoryContext.value ? historyMessages : null
    }, streamingIndex);
  } else {
    // 非流式输出模式
    // 添加思考中的消息
    chatMessages.value.push({ role: 'assistant', content: '思考中...', thinking: true });

    // 启用自动滚动
    autoScroll.value = true;
    // 自动滚动到底部
    scrollToBottom();

    try {
      const response = await api.post('/hybridrag', {
        request: currentQuestion,
        flow: false,
        filename: currentFile.value.name,
        messages: enableHistoryContext.value ? historyMessages : null
      }, {
        signal: abortController.value ? abortController.value.signal : undefined
      });

      // 检查响应是否有效
      if (!response || !response.data) {
        throw new Error('服务器响应无效');
      }

      // 检查响应状态
      if (response.data.status === 'processing') {
        ElMessage.warning('文件正在处理中，请稍后再试');
        chatMessages.value = chatMessages.value.filter(msg => !msg.thinking && !msg.streaming);
        return;
      } else if (response.data.status === 'error') {
        ElMessage.error(response.data.message || '文件处理失败');
        chatMessages.value = chatMessages.value.filter(msg => !msg.thinking && !msg.streaming);
        return;
      }

      // 检查结果是否存在
      if (!response.data.result) {
        throw new Error('服务器返回结果为空');
      }

      // 非流式输出模式，替换"思考中"的消息
      const thinkingIndex = chatMessages.value.findIndex(msg => msg.thinking);
      if (thinkingIndex !== -1) {
        chatMessages.value[thinkingIndex] = {
          role: 'assistant',
          content: {
            answer: response.data.result.answer,
            material: response.data.result.material
          }
        };
      }

      // 如果启用自动滚动，自动滚到最新消息
      if (autoScroll.value) {
        scrollToBottom();
      }

      // 保存聊天记录到localStorage
      if (currentFile.value?.name) {
        const chatHistory = chatMessages.value.filter(msg => !msg.thinking && !msg.streaming);
        localStorage.setItem(`chat_${currentFile.value.name}`, JSON.stringify(chatHistory));
      }
    } catch (error) {
      if (error.name === 'CanceledError' || error.name === 'AbortError') {
        // 请求被取消，不需要显示错误信息
        return;
      }
      console.error('获取RAG回复失败:', error);
      chatMessages.value = chatMessages.value.filter(msg => !msg.thinking && !msg.streaming);
      ElMessage.error(getApiErrorMessage(error, '获取回复失败，请稍后重试'));
    } finally {
      chatLoading.value = false;
      abortController.value = null;

      // 如果启用自动滚动，自动滚到最新消息
      if (autoScroll.value) {
        scrollToBottom();
      }
    }
  }
};

const menuItemSelect = (index) => {
  if (index === "home") {
    fileListExpand.value = false;
    activeView.value = 'upload';  // 切换到上传视图
    currentFile.value = null;     // 清空当前文件
  } else if (index === "fileList") {
    fileListExpand.value = true;
  }
}

// 修改 closeFileList 函数
const closeFileList = () => {
  sideBarRef.value.openMenuItem("home");
  fileListExpand.value = false;
}

// 文件状态: 'uploading', 'processing', 'success', 'error'
let aiValidationPromise = null;

const validateAiSettingsBeforeUpload = async () => {
  // Share one validation request when several files are selected together.
  if (!aiValidationPromise) {
    aiValidationPromise = api.post('/ai-settings/validate')
      .then(() => true)
      .catch(error => {
        ElMessage.error(getApiErrorMessage(error, '请先完成正确的 AI 配置'));
        return false;
      })
      .finally(() => {
        aiValidationPromise = null;
      });
  }
  return aiValidationPromise;
};

const beforeUpload = async (file) => {
  const isTransferPackage = file.name.toLowerCase().endsWith('.kmn.zip');
  if (!isTransferPackage && !await validateAiSettingsBeforeUpload()) return false;

  if (isTransferPackage) {
    uploadFileList.value.push({
      uid: Date.now(),
      name: file.name,
      status: 'uploading',
      display_status: '导入迁移包',
      size: file.size,
      percentage: 0,
      completedChunks: 0,
      totalChunks: 0,
      isTransferPackage: true
    });
    fileListExpand.value = true;
    return true;
  }

  // 检查文件是否已存在
  const existingFile = uploadFileList.value.find(item => item.name === file.name);

  if (existingFile) {
    if (existingFile.status === 'error') {
      existingFile.status = 'uploading';
      existingFile.display_status = '上传中';
      existingFile.percentage = 0;
      existingFile.completedChunks = 0;
      existingFile.totalChunks = 0;
      existingFile.latestChunkSeconds = null;
      existingFile.estimatedRemainingSeconds = null;
      existingFile.isUpdate = false;
      fileListExpand.value = true;
      return true;
    }

    // 询问用户是否要覆盖已存在的文件
    try {
      await ElMessageBox.confirm(
        `文件 "${file.name}" 已存在，是否要进行增量更新？`,
        '文件已存在',
        {
          confirmButtonText: '增量更新',
          cancelButtonText: '取消上传',
          type: 'warning',
        }
      );

      // 用户确认更新，修改原文件状态为更新中
      existingFile.status = 'updating';
      existingFile.display_status = '增量更新中';
      existingFile.percentage = 0;
      existingFile.completedChunks = 0;
      existingFile.totalChunks = 0;
      existingFile.latestChunkSeconds = null;
      existingFile.estimatedRemainingSeconds = null;
      existingFile.isUpdate = true; // 标记为增量更新
      return true;
    } catch (e) {
      // 用户取消上传
      return false;
    }
  }

  // 新文件，正常上传
  const fileObj = {
    uid: Date.now(),
    name: file.name,  // 保持原始文件名（包含后缀）
    status: 'uploading',
    size: file.size,
    percentage: 0,
    completedChunks: 0,
    totalChunks: 0,
    latestChunkSeconds: null,
    estimatedRemainingSeconds: null
  }
  uploadFileList.value.push(fileObj);
  fileListExpand.value = true;
  return true;
}

const onUploadProgress = (event, file) => {
  const targetFile = uploadFileList.value.find(item => item.name === file.name);
  if (targetFile) {
    targetFile.percentage = Math.round(event.percent);
  }
}

const onUploadSuccess = (response, file) => {
  const targetFile = uploadFileList.value.find(item => item.name === file.name);
  if (targetFile) {
    if (response?.imported) {
      targetFile.name = response.filename;
      targetFile.status = 'completed';
      targetFile.display_status = '已导入';
      targetFile.percentage = 100;
      targetFile.isTransferPackage = false;
      targetFile.partialAvailable = false;
      targetFile.resumable = false;
      ElMessage.success(response.message || '图谱迁移包已导入');
      return;
    }
    // 后端会根据处理状态和结果完整性决定是否允许增量更新。
    targetFile.isUpdate = Boolean(response?.is_update);
    if (targetFile.isUpdate) {
      // 更新状态为增量更新处理中
      targetFile.status = 'updating';
      targetFile.display_status = '增量更新中';
      targetFile.percentage = 0;
      targetFile.resultId = response.resultId || Date.now();
    } else {
      // 新文件，修改状态为处理中
      targetFile.status = 'processing';
      targetFile.display_status = '处理中';
      targetFile.percentage = 0;
      targetFile.resultId = response.resultId || Date.now();
    }

    // 开始检查处理状态
    checkFileProcessingStatus(targetFile);
  }
}

const stopFileStatusPolling = (filename) => {
  const timer = processingTimers.get(filename);
  if (timer) clearTimeout(timer);
  processingTimers.delete(filename);
};

// 轮询在上次请求完成后再安排下一次，避免网络慢时重叠请求。
const checkFileProcessingStatus = async (file) => {
  if (!file?.name) return;

  const filename = file.name;
  const startedAt = Date.now();
  const timeout = 10 * 60 * 1000;
  stopFileStatusPolling(filename);

  const poll = async () => {
    await updateFileStatus(file);
    const finished = ['completed', 'paused', 'interrupted', 'error'].includes(file.status);

    if (finished || Date.now() - startedAt >= timeout) {
      stopFileStatusPolling(filename);
      return;
    }

    processingTimers.set(filename, setTimeout(poll, 3000));
  };

  await poll();
};

// 添加一个更新文件状态的函数
const updateFileStatus = async (file) => {
  try {
    const response = await api.get(`/processing-status/${encodePathSegment(file.name)}`);
    if (response.data) {
      // 更新文件状态
      file.status = response.data.status;
      file.percentage = Math.min(100, Math.max(0, response.data.percentage ?? 0));
      file.completedChunks = response.data.completed_chunks || 0;
      file.totalChunks = response.data.total_chunks || 0;
      file.latestChunkSeconds = response.data.latest_chunk_seconds;
      file.estimatedRemainingSeconds = response.data.estimated_remaining_seconds;
      file.partialAvailable = Boolean(response.data.partial_available);
      file.resumable = Boolean(response.data.resumable);
      file.errorMessage = response.data.error_message || '';
      if (response.data.display_status) {
        file.display_status = response.data.display_status;
      } else {
        file.display_status = getStatusText(response.data.status);
      }

      // 如果文件存在增量更新标记并且状态已变为completed，清除更新标记
      if (file.isUpdate && response.data.status === 'completed') {
        file.isUpdate = false;
      }

      return true;
    }
    return false;
  } catch (error) {
    console.error('获取文件状态失败:', error);
    return false;
  }
};

const onUploadError = (error, file) => {
  const targetFile = uploadFileList.value.find(item => item.name === file.name);
  if (targetFile) {
    targetFile.status = 'error';
    targetFile.display_status = '上传失败';
    targetFile.isUpdate = false;
    stopFileStatusPolling(file.name);
    ElMessage.error(getApiErrorMessage(error, `文件 ${file.name} 上传失败`));
  }
}

const pauseFileProcessing = async (file) => {
  if (!file?.name || !['uploading', 'processing', 'updating', 'resuming'].includes(file.status)) {
    ElMessage.warning('该文件当前无法暂停');
    return;
  }

  try {
    const response = await api.post(`/pause-processing/${encodePathSegment(file.name)}`);
    file.status = response.data?.status || 'pausing';
    file.display_status = '暂停中';
    ElMessage.info('将在当前文本块完成并保存后暂停');
    checkFileProcessingStatus(file);
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error, '暂停处理失败'));
  }
};

const resumeFileProcessing = async (file) => {
  if (!file?.name || !file.resumable) {
    ElMessage.warning('缺少恢复数据，请重新上传原文件');
    return;
  }

  try {
    const response = await api.post(`/resume-processing/${encodePathSegment(file.name)}`);
    file.status = response.data?.status || 'resuming';
    file.display_status = '继续处理中';
    file.errorMessage = '';
    ElMessage.success('已从上次完成的文本块继续处理');
    checkFileProcessingStatus(file);
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error, '继续处理失败'));
  }
};

const downloadTransferPackage = async (file) => {
  if (!file?.name || file.status !== 'completed') return;
  try {
    const response = await api.get(
      `/export-package/${encodePathSegment(file.name)}`,
      { responseType: 'blob' }
    );
    const baseName = file.name.replace(/\.[^.]+$/, '');
    const blobUrl = URL.createObjectURL(response.data);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = `${baseName}.kmn.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
    ElMessage.success('迁移包下载已开始');
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error, '下载图谱迁移包失败'));
  }
};

const redrawFileGraph = async (file) => {
  if (!file?.name || file.status !== 'completed') {
    ElMessage.warning('只有已完成的文件才能重新绘制图谱');
    return;
  }

  try {
    await ElMessageBox.confirm(
      `确定根据当前保存的图谱状态重新绘制文件 ${file.name} 的全部图谱页面吗？不会重新调用 AI。`,
      '重新绘制图谱',
      {
        confirmButtonText: '重新绘制',
        cancelButtonText: '取消',
        type: 'info'
      }
    );
  } catch {
    return;
  }

  stopFileStatusPolling(file.name);
  file.status = 'redrawing';
  file.display_status = '重新绘制图谱中';
  file.errorMessage = '';
  try {
    await api.post(`/redraw-graph/${encodePathSegment(file.name)}`);
    await updateFileStatus(file);
    if (currentFile.value?.name === file.name) {
      finishKnowledgeGraphLoading();
      knowledgeGraphUrl.value = null;
      await nextTick();
      await fetchKnowledgeGraph(file.name);
    }
    ElMessage.success('图谱已重新绘制');
  } catch (error) {
    await updateFileStatus(file);
    ElMessage.error(getApiErrorMessage(error, '重新绘制图谱失败'));
  }
};

const handleFileContextAction = async (action) => {
  const file = fileContextMenu.file;
  closeFileContextMenu();
  if (!file) return;

  if (action === 'pause') await pauseFileProcessing(file);
  if (action === 'resume') await resumeFileProcessing(file);
  if (action === 'view') await viewFileResult(file);
  if (action === 'redraw') await redrawFileGraph(file);
  if (action === 'download-package') await downloadTransferPackage(file);
  if (action === 'clear-history') await deleteRagHistory(file);
  if (action === 'delete') await deleteFile(file);
};

// 添加handleSearch函数，这个函数在搜索框输入时被调用，但之前未定义
const handleSearch = () => {
  handleFilter();
};

// 查看文件结果
const viewFileResult = async (file) => {
  if (
    file.status === 'completed'
    || (['paused', 'interrupted'].includes(file.status) && file.partialAvailable)
  ) {
    try {
      // 如果切换了文件，保存当前文件的聊天记录
      if (currentChatFile.value && currentChatFile.value !== file.name) {
        const chatHistory = chatMessages.value.filter(msg => !msg.thinking);
        localStorage.setItem(`chat_${currentChatFile.value}`, JSON.stringify(chatHistory));
      }

      // 如果当前有正在进行的请求，取消它
      if (abortController.value) {
        abortController.value.abort();
        abortController.value = null;
        chatLoading.value = false;
      }

      activeView.value = 'result';
      currentFile.value = file;
      currentChatFile.value = file.name;
      evidenceRequestId += 1;
      evidenceResults.value = [];
      sourceHighlightHtml.value = '';
      activeEvidenceIndex.value = 0;
      if (window.innerWidth <= 820) {
        fileListExpand.value = false;
      }

      fileContentLoading.value = true;
      fileContent.value = '';

      if (!file.name) {
        ElMessage.error('文件名不存在');
        return;
      }
      ragReferenceData.value = { nodes: [], links: [], blocks: [] };
      loadRagReferenceData(file.name);

      try {
        const [contentResponse] = await Promise.all([
          // 使用原始文件名获取内容
          api.get(`/file-content/${encodePathSegment(file.name)}`).catch(error => {
            console.error('获取文件内容失败:', error);
            return { data: { content: '' } };
          }),
          fetchKnowledgeGraph(file.name)  // 使用原始文件名获取知识图谱
        ]);

        if (contentResponse.data && contentResponse.data.content) {
          fileContent.value = contentResponse.data.content;
        }
      } catch (error) {
        console.error('获取文件内容失败:', error);
        ElMessage.warning('获取原文件内容失败');
      } finally {
        fileContentLoading.value = false;
      }

      // 使用新函数加载聊天历史记录
      loadChatHistory(file.name);

      // 启用自动滚动
      autoScroll.value = true;

      // 不管当前是什么标签，先切换到RAG标签
      activeTab.value = 'rag';

      // 使用nextTick确保DOM已更新
      nextTick(() => {
        scrollToBottom();
      });
    } catch (error) {
      console.error('查看文件结果失败:', error);
      ElMessage.error('查看文件结果失败');
    }
  } else if (file.status === 'error') {
    ElMessage.warning(file.resumable
      ? `文件 ${file.name} 处理失败，可点击“继续处理”重试`
      : `文件 ${file.name} 处理失败，请重新上传原文件后重试`);
  } else {
    // 对于uploading、processing等状态，只显示提示
    ElMessage.info(`文件 ${file.name} 正在${file.display_status || getStatusText(file.status)}，请稍后查看`);
  }
};

// 关闭结果视图
const closeResultView = () => {
  // 如果当前有正在进行的请求，取消它
  if (abortController.value) {
    abortController.value.abort();
    abortController.value = null;
    chatLoading.value = false;
  }

  if (currentChatFile.value) {
    // 过滤掉思考中和流式输出中的消息
    const chatHistory = chatMessages.value.filter(msg => !msg.thinking && !msg.streaming);
    localStorage.setItem(`chat_${currentChatFile.value}`, JSON.stringify(chatHistory));
  }
  activeView.value = 'upload';
  finishKnowledgeGraphLoading();
  knowledgeGraphUrl.value = null;
  ragReferenceRequestId += 1;
  ragReferenceData.value = { nodes: [], links: [], blocks: [] };
  evidenceRequestId += 1;
  evidenceResults.value = [];
  sourceHighlightHtml.value = '';
  currentChatFile.value = null;
  chatMessages.value = [];
}

// 修改切换面板显示状态的函数
const togglePanelVisibility = (panel) => {
  // 记录之前的状态
  const previousState = panelVisible[panel];

  // 避免关闭所有面板
  const visibleCount = Object.values(panelVisible).filter(v => v).length;
  if (visibleCount > 1 || !panelVisible[panel]) {
    panelVisible[panel] = !panelVisible[panel];

    // 如果当前激活的面板被关闭，则切换到第一个可见面板
    if (activeTab.value === panel && !panelVisible[panel]) {
      const firstVisiblePanel = Object.keys(panelVisible).find(key => panelVisible[key]);
      if (firstVisiblePanel) {
        activeTab.value = firstVisiblePanel;
      }
    }

    // 如果知识图谱面板从隐藏变为显示，则重新加载
    if (panel === 'knowledge-graph' && !previousState && panelVisible[panel]) {
      reloadKnowledgeGraph();
    }

    if (!previousState && panelVisible[panel]) {
      nextTick(ensurePanelsFit);
    }
  } else {
    ElMessage.warning('至少保留一个面板');
  }
};

// 切换标签
const switchTab = (tab) => {
  if (panelVisible[tab]) {
    activeTab.value = tab;

    // 在切换到rag标签时，自动滚动到最新消息
    if (tab === 'rag') {
      nextTick(() => {
        scrollToBottom();
      });
    }
  }
};

// 获取文件状态的文本描述
const getStatusText = (status) => {
  switch (status) {
    case 'uploading':
      return '上传中';
    case 'processing':
      return '处理中';
    case 'updating':
      return '增量更新中';
    case 'resuming':
      return '继续处理中';
    case 'pausing':
      return '暂停中';
    case 'redrawing':
      return '重新绘制图谱中';
    case 'paused':
      return '已暂停';
    case 'completed':
      return '已完成';
    case 'interrupted':
      return '部分完成，可继续';
    case 'error':
      return '处理失败';
    default:
      return status;
  }
};

const isFileProcessing = (status) => {
  return ['uploading', 'processing', 'updating', 'resuming', 'pausing', 'redrawing'].includes(status);
};

const formatRemainingTime = (seconds) => {
  if (seconds == null || !Number.isFinite(Number(seconds))) return '';

  const totalSeconds = Math.max(0, Math.round(Number(seconds)));
  if (totalSeconds < 60) return `${totalSeconds}秒`;

  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  if (minutes < 60) return remainingSeconds ? `${minutes}分${remainingSeconds}秒` : `${minutes}分钟`;

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}小时${remainingMinutes}分钟` : `${hours}小时`;
};

const getFileProgressSummary = (file) => {
  if (file.status === 'redrawing') return '正在重新绘制全部图谱页面';
  if (file.status === 'uploading') return `上传 ${file.percentage || 0}%`;
  if (!file.totalChunks) return '正在准备分块';

  const chunkProgress = `${file.completedChunks || 0}/${file.totalChunks} 块`;
  const latestChunkSeconds = Number(file.latestChunkSeconds);
  const speed = Number.isFinite(latestChunkSeconds) && latestChunkSeconds > 0
    ? ` · 速度 ${latestChunkSeconds.toFixed(1).replace(/\.0$/, '')}秒/块`
    : ` · ${file.percentage || 0}%`;
  return `${chunkProgress}${speed}`;
};

const getFileEstimatedTime = (file) => {
  if (file.status === 'uploading') return '';
  const remainingTime = formatRemainingTime(file.estimatedRemainingSeconds);
  return remainingTime ? `预计剩余 ${remainingTime}` : '';
};

// 获取文件状态对应的图标
const getFileIcon = (status) => {
  switch (status) {
    case 'uploading':
    case 'processing':
    case 'updating':
    case 'resuming':
    case 'pausing':
      return Loading;
    case 'completed':
      return SuccessFilled;
    case 'error':
    case 'interrupted':
    case 'paused':
      return 'circle-close';
    default:
      return Document;
  }
};

// 修改重新加载知识图谱函数
const reloadKnowledgeGraph = () => {
  if (panelVisible['knowledge-graph'] && currentFile.value?.name) {
    fetchKnowledgeGraph(currentFile.value.name);
  }
};

// 添加筛选相关的状态
const fileTypeFilter = ref('all');
const statusFilter = ref('all');

// 文件类型选项
const fileTypeOptions = [
  { value: 'all', label: '全部' },
  { value: 'txt', label: 'TXT' },
  { value: 'pdf', label: 'PDF' },
  { value: 'docx', label: 'WORD' }
];

// 状态选项
const statusOptions = [
  { value: 'all', label: '全部' },
  { value: 'uploading', label: '上传中' },
  { value: 'processing', label: '处理中' },
  { value: 'updating', label: '增量更新中' },
  { value: 'resuming', label: '继续处理中' },
  { value: 'pausing', label: '暂停中' },
  { value: 'paused', label: '已暂停' },
  { value: 'completed', label: '已完成' },
  { value: 'interrupted', label: '部分完成' },
  { value: 'error', label: '失败' }
];

// 添加临时筛选状态
const tempFileTypeFilter = ref('all');
const tempStatusFilter = ref('all');

// 添加筛选框显示控制
const filterVisible = ref(false);

// 修改筛选处理函数
const handleFilter = () => {
  let filtered = uploadFileList.value;

  // 应用搜索过滤
  if (searchValue.value) {
    const searchText = searchValue.value.toLowerCase();
    filtered = filtered.filter(file =>
        file.name.toLowerCase().includes(searchText)
    );
  }

  // 应用类型过滤
  if (fileTypeFilter.value !== 'all') {
    filtered = filtered.filter(file => {
      const ext = file.name.split('.').pop().toLowerCase();
      return ext === fileTypeFilter.value;
    });
  }

  // 应用状态过滤
  if (statusFilter.value !== 'all') {
    filtered = filtered.filter(file =>
        file.status === statusFilter.value
    );
  }

  filteredFileList.value = filtered;
};

// 修改确认筛选函数
const confirmFilter = () => {
  fileTypeFilter.value = tempFileTypeFilter.value;
  statusFilter.value = tempStatusFilter.value;
  currentPage.value = 1;
  handleFilter();
  filterVisible.value = false;  // 关闭筛选框
};

// 修改重置筛选函数
const resetFilter = () => {
  tempFileTypeFilter.value = 'all';
  tempStatusFilter.value = 'all';
  fileTypeFilter.value = 'all';
  statusFilter.value = 'all';
  currentPage.value = 1;
  handleFilter();
  filterVisible.value = false;  // 关闭筛选框
};

// 监听筛选条件变化
watch([searchValue, fileTypeFilter, statusFilter], () => {
  currentPage.value = 1;
  handleFilter();
}, { deep: true });

// 监听文件列表变化
watch(uploadFileList, () => {
  handleFilter();
}, { deep: true });

watch(filteredFileList, (files) => {
  const lastPage = Math.max(1, Math.ceil(files.length / pageSize));
  if (currentPage.value > lastPage) currentPage.value = lastPage;
});

// 添加关闭所有视图的处理函数
const handleCloseAll = () => {
  closeResultView();
  fileListExpand.value = false;
};

// 添加当前选中文件的ID
const currentFileId = ref(null);

// 查看文件内容
const viewFile = (file) => {
  if (!file || !file.name || file.status !== 'completed') return;

  currentFile.value = file;
  activeView.value = 'result';
  activeTab.value = 'original';

  // 使用新的函数加载聊天历史
  loadChatHistory(file.name);

  // ...其他代码
};

// 准备文件的聊天状态
const prepareChatState = (file) => {
  // 首先尝试从localStorage加载聊天记录
  const savedChat = localStorage.getItem(`chat_${file.name}`);

  if (savedChat) {
    // 如果localStorage中有聊天记录，使用它
    chatMessages.value = JSON.parse(savedChat);

    // 同时更新fileChatStates中的记录
    if (!fileChatStates.value[file.name]) {
      fileChatStates.value[file.name] = {
        messages: JSON.parse(savedChat),
        lastActive: new Date().getTime()
      };
    } else {
      fileChatStates.value[file.name].messages = JSON.parse(savedChat);
      fileChatStates.value[file.name].lastActive = new Date().getTime();
    }
  } else {
    // 如果localStorage中没有聊天记录，检查fileChatStates
    if (!fileChatStates.value[file.name]) {
      // 如果fileChatStates中也没有，创建新的聊天记录
      fileChatStates.value[file.name] = {
        messages: [
          { role: 'system', content: `我是基于文档《${file.name}》的HybridRAG助手，可以回答与文档相关的问题。` }
        ],
        lastActive: new Date().getTime()
      };

      // 更新聊天消息
      chatMessages.value = [...fileChatStates.value[file.name].messages];
    } else {
      // 如果fileChatStates中有记录，使用它
      fileChatStates.value[file.name].lastActive = new Date().getTime();
      chatMessages.value = [...fileChatStates.value[file.name].messages];
    }
  }

  // 设置当前聊天文件
  currentChatFile.value = file.name;

  // 如果切换到RAG标签，自动滚动到底部
  if (activeTab.value === 'rag') {
    nextTick(() => {
      scrollToBottom();
    });
  }
};

// 加载文件内容
const loadFileContent = async (file) => {
  fileContentLoading.value = true;
  fileContent.value = '';

  try {
    const response = await api.get(`/file-content/${encodePathSegment(file.name)}`);
    if (response.data && response.data.content) {
      fileContent.value = response.data.content;
    }
  } catch (error) {
    console.error('获取文件内容失败:', error);
    ElMessage.warning('获取文件内容失败');
  } finally {
    fileContentLoading.value = false;
  }
};

// 加载知识图谱
const loadKnowledgeGraph = async (file) => {
  if (!file || !file.name) return;
  await fetchKnowledgeGraph(file.name);
};

// 添加历史上下文相关状态
const enableHistoryContext = ref(true);

onUnmounted(() => {
  abortController.value?.abort();
  window.removeEventListener('click', closeFileContextMenu);
  window.removeEventListener('blur', closeFileContextMenu);
  window.removeEventListener('resize', closeFileContextMenu);
  window.removeEventListener('scroll', closeFileContextMenu, true);
  window.removeEventListener('message', handleKnowledgeGraphReadyMessage);
  if (knowledgeGraphReadyTimer) clearTimeout(knowledgeGraphReadyTimer);
  processingTimers.forEach(timer => clearTimeout(timer));
  processingTimers.clear();
  finishResizeSession();
  panelResizeObserver?.disconnect();
  panelResizeObserver = null;
});
</script>

<template>
  <div class="main-container">
    <side-bar
        ref="sideBarRef"
        v-model:fileListExpand="fileListExpand"
        v-model:enableStreamOutput="enableStreamOutput"
        v-model:enableHistoryContext="enableHistoryContext"
        v-model:noteType="noteType"
        v-model:customPrompts="customPrompts"
        v-model:useImg2txt="useImg2txt"
        @update:enableStreamOutput="saveStreamSetting"
        @update:useImg2txt="saveImg2txtSetting"
        @closeAll="handleCloseAll"
    />
    <div class="main-content">
      <el-drawer
          v-model="fileListExpand"
          direction="ltr"
          :modal="false"
          :show-close="false"
          :size="fileListWidth"
      >
        <template #header>
          <div class="drawer-manu-header">
            <div class="header">
              <svg-icon icon-name="file" size="18px"/>
              <span>文件列表</span>
            </div>
            <svg-icon icon-name="close" icon-class="close-icon" size="18px" @click="closeFileList"/>
          </div>
        </template>
        <template #default>
          <div v-if="!isSearch" class="query-button">
            <el-popover
                v-model:visible="filterVisible"
                :show-arrow="false"
                placement="top-end"
                popper-class="custom-popover"
                trigger="click"
                :show-after="200"
                popper-style="width:360px"
            >
              <template #reference>
                <div class="filter">
                  <svg-icon icon-name="filter" size="16px"/>
                  <span>筛选</span>
                </div>
              </template>
              <template #default>
                <div class="filter-content">
                  <div class="filter-section">
                    <div class="filter-title">类型</div>
                    <div class="filter-options">
                      <el-radio-group v-model="tempFileTypeFilter" size="small">
                        <template v-for="option in fileTypeOptions" :key="option.value">
                          <el-radio-button :value="option.value">{{ option.label }}</el-radio-button>
                        </template>
                      </el-radio-group>
                    </div>
                  </div>
                  <div class="filter-section">
                    <div class="filter-title">状态</div>
                    <div class="filter-options">
                      <el-radio-group v-model="tempStatusFilter" size="small">
                        <template v-for="option in statusOptions" :key="option.value">
                          <el-radio-button :value="option.value">{{ option.label }}</el-radio-button>
                        </template>
                      </el-radio-group>
                    </div>
                  </div>
                  <div class="filter-actions">
                    <el-button size="small" @click="resetFilter">重置</el-button>
                    <el-button type="primary" size="small" @click="confirmFilter">确认</el-button>
                  </div>
                </div>
              </template>
            </el-popover>
            <svg-icon icon-name="search" icon-class="search-icon" size="18px" @click="isSearch=true"/>
          </div>
          <div v-else class="search-input">
            <el-input
                v-model="searchValue"
                placeholder="请输入文件名称"
                clearable
                @input="handleSearch"
            />
            <el-button link @click="isSearch=false">取消</el-button>
          </div>
          <div class="file-list">
            <template v-if="filteredFileList.length > 0">
              <div
                  v-for="file in paginatedFileList"
                  :key="file.name"
                  class="file-item"
                  :class="{
                  'can-click': file.status === 'completed' || (['paused', 'interrupted'].includes(file.status) && file.partialAvailable),
                  'active': currentFile?.name === file.name,
                  'expanded': sideBarRef?.expandedFileId === file.name
                }"
                  @contextmenu="openFileContextMenu($event, file)"
              >
                <div class="file-header"
                     @dblclick="viewFileResult(file)"
                     @click="sideBarRef?.toggleFileExpand(file)"
                     @mouseenter="currentFileId = file.name"
                     @mouseleave="currentFileId = null">
                  <div class="file-info">
                    <el-icon class="file-icon" :class="file.status">
                      <component :is="getFileIcon(file.status)" />
                    </el-icon>
                    <div class="file-name-container">
                      <el-tooltip
                          :content="file.name"
                          placement="right"
                          :show-after="500"
                          :hide-after="0"
                      >
                        <div class="file-name">{{ file.name }}</div>
                      </el-tooltip>
                    </div>
                  </div>
                  <div class="file-actions">
                    <div class="file-status" :class="file.status">
                      {{ file.display_status || getStatusText(file.status) }}
                    </div>
                    <transition name="fade">
                      <div
                        v-if="currentFileId === file.name && ['completed', 'paused', 'interrupted', 'error'].includes(file.status)"
                        class="delete-action"
                      >
                        <el-tooltip v-if="file.status === 'completed'" content="清除RAG历史" placement="top">
                          <svg-icon
                              icon-name="clear"
                              icon-class="clear-icon"
                              size="16px"
                              @click.stop="deleteRagHistory(file, $event)"
                          />
                        </el-tooltip>
                        <el-tooltip content="删除文件" placement="top">
                          <svg-icon
                              icon-name="delete"
                              icon-class="delete-icon"
                              size="16px"
                              @click.stop="deleteFile(file)"
                          />
                        </el-tooltip>
                      </div>
                    </transition>
                  </div>
                </div>

                <div v-if="isFileProcessing(file.status)" class="file-progress">
                  <el-progress :percentage="file.percentage" :show-text="false" :stroke-width="2" />
                  <div class="file-progress-detail">
                    <div class="progress-summary">{{ getFileProgressSummary(file) }}</div>
                    <div v-if="getFileEstimatedTime(file)" class="progress-estimate">
                      {{ getFileEstimatedTime(file) }}
                    </div>
                  </div>
                </div>

                <div v-else-if="['paused', 'interrupted', 'error'].includes(file.status)" class="file-recovery">
                  <el-progress
                    v-if="file.totalChunks"
                    :percentage="file.percentage"
                    :show-text="false"
                    :stroke-width="2"
                    status="warning"
                  />
                  <div class="recovery-summary">
                    <span v-if="file.completedChunks">已保留 {{ file.completedChunks }}/{{ file.totalChunks }} 块</span>
                    <span v-else>{{ file.errorMessage || '尚无完成的文本块' }}</span>
                    <el-button
                      v-if="file.resumable"
                      type="warning"
                      link
                      size="small"
                      @click.stop="resumeFileProcessing(file)"
                    >
                      继续处理
                    </el-button>
                  </div>
                </div>

                <!-- 展开的实体卡片 -->
                <div v-if="sideBarRef?.expandedFileId === file.name" class="file-entities-card">
                  <div v-if="sideBarRef?.loadingEntities[file.name]" class="loading-entities">
                    <el-icon class="is-loading"><Loading /></el-icon>
                    <span>加载主要实体中...</span>
                  </div>
                  <div v-else-if="sideBarRef?.fileEntities[file.name]?.errorMessage" class="entities-error">
                    <el-alert
                      :title="sideBarRef?.fileEntities[file.name]?.errorMessage"
                      type="error"
                      :closable="false"
                      size="small"
                      show-icon
                    />
                  </div>
                  <div v-else-if="sideBarRef?.fileEntities[file.name]?.entities?.length" class="entities-list">
                    <div class="entities-title">主要实体</div>
                    <div class="entities-content">
                      <el-tag
                        v-for="entity in sideBarRef?.fileEntities[file.name].entities"
                        :key="entity"
                        class="entity-tag"
                        size="small"
                        effect="plain"
                      >
                        {{ entity }}
                      </el-tag>
                    </div>
                  </div>
                  <div v-else class="no-entities">
                    <el-empty description="暂无实体数据" :image-size="60" />
                  </div>
                </div>
              </div>
            </template>
            <el-empty v-else description="暂无文件" />
          </div>
          <div class="pagination" v-if="filteredFileList.length > pageSize">
            <el-pagination
                v-model:current-page="currentPage"
                :page-size="pageSize"
                :total="filteredFileList.length"
                size="small"
                layout="prev, pager, next"
              background
            />
          </div>
          <div
              class="file-list-resizer"
              role="separator"
              aria-label="调整文件列表宽度"
              aria-orientation="vertical"
              title="拖动调整文件列表宽度"
              @pointerdown.stop="startFileListResize"
          ></div>
        </template>
      </el-drawer>
      <div
          class="content"
          :class="{ 'is-resizing': resizeMode === 'file-list' }"
          :style="contentStyle"
      >
        <div v-if="activeView === 'upload'" class="upload-view">
          <div class="background"></div>
          <div class="upload">
            <h1>智能图谱笔记系统! 🎉</h1>
            <el-upload
                drag
                :action="apiUrl('/upload')"
                :data="() => ({
                  noteType: noteType,
                  use_img2txt: useImg2txt ? 'true' : 'false',
                  ...(noteType === 'custom' ? {
                    entityPrompt: customPrompts.entityExtraction,
                    relationshipPrompt: customPrompts.relationshipExtraction,
                    fusionPrompt: customPrompts.knowledgeFusion
                  } : {})
                })"
                multiple
                :show-file-list="false"
                :before-upload="beforeUpload"
                :on-progress="onUploadProgress"
                :on-success="onUploadSuccess"
                :on-error="onUploadError"
            >
              <svg-icon icon-name="upload" icon-class="upload-icon" size="40px"/>
              <div class="upload-text">
                点击或拖拽上传文件
              </div>
              <p>支持的文件类型：TXT，PDF...</p>
              <p>支持拖拽 .KMN.ZIP 迁移包直接恢复，无需重新处理</p>
              <p>单个txt不超过 5M</p>
              <p>图谱初始构造时间较长，请耐心等待</p>
              <br>
              <br>
              <p>作者：XIK</p>
            </el-upload>
          </div>
        </div>

        <div v-if="activeView === 'result'" class="result-view">
          <!-- 顶部导航标签 -->
          <div class="file-tabs">
            <div class="file-info">
              <div class="file-mark"><Document /></div>
              <div class="file-identity">
                <span class="file-context">当前文档</span>
                <span v-if="currentFile" class="filename">{{ currentFile.name }}</span>
              </div>
            </div>
            <div class="tabs-container">
              <div
                  class="tab-item"
                  :class="{ active: activeTab === 'original', disabled: !panelVisible['original'] }"
                  @click="switchTab('original')"
              >
                <el-icon><Document /></el-icon>
                <span>原文件</span>
                <div class="tab-actions">
                  <el-tooltip :content="panelVisible['original'] ? '隐藏原文件' : '显示原文件'" placement="bottom">
                    <button
                        type="button"
                        class="panel-toggle"
                        :class="{ 'is-active': panelVisible['original'] }"
                        @click.stop="togglePanelVisibility('original')"
                    >
                      <el-icon><View v-if="panelVisible['original']" /><Hide v-else /></el-icon>
                    </button>
                  </el-tooltip>
                </div>
              </div>
              <div
                  class="tab-item"
                  :class="{ active: activeTab === 'knowledge-graph', disabled: !panelVisible['knowledge-graph'] }"
                  @click="switchTab('knowledge-graph')"
              >
                <el-icon><Connection /></el-icon>
                <span>知识图谱</span>
                <div class="tab-actions">
                  <el-tooltip :content="panelVisible['knowledge-graph'] ? '隐藏知识图谱' : '显示知识图谱'" placement="bottom">
                    <button
                        type="button"
                        class="panel-toggle"
                        :class="{ 'is-active': panelVisible['knowledge-graph'] }"
                        @click.stop="togglePanelVisibility('knowledge-graph')"
                    >
                      <el-icon><View v-if="panelVisible['knowledge-graph']" /><Hide v-else /></el-icon>
                    </button>
                  </el-tooltip>
                </div>
              </div>
              <div
                  class="tab-item"
                  :class="{ active: activeTab === 'rag', disabled: !panelVisible['rag'] }"
                  @click="switchTab('rag')"
              >
                <el-icon><ChatDotRound /></el-icon>
                <span>RAG 问答</span>
                <div class="tab-actions">
                  <el-tooltip :content="panelVisible['rag'] ? '隐藏 RAG 问答' : '显示 RAG 问答'" placement="bottom">
                    <button
                        type="button"
                        class="panel-toggle"
                        :class="{ 'is-active': panelVisible['rag'] }"
                        @click.stop="togglePanelVisibility('rag')"
                    >
                      <el-icon><View v-if="panelVisible['rag']" /><Hide v-else /></el-icon>
                    </button>
                  </el-tooltip>
                </div>
              </div>
            </div>
          </div>

          <!-- 内容区域 -->
          <div
              ref="contentPanelsRef"
              class="content-panels"
              :class="{ 'is-resizing': resizeMode === 'panel' }"
          >
            <div
                v-if="panelVisible['original']"
                class="panel original-panel"
                :class="{ active: activeTab === 'original' }"
                :style="getPanelStyle('original')"
                data-panel="original"
            >
              <div class="panel-header">
                <div class="panel-title">
                  <h3>文档内容</h3>
                  <span v-if="fileContentStats" class="content-stats">{{ fileContentStats }}</span>
                </div>
                <div class="document-tools">
                  <el-segmented
                      v-model="contentViewMode"
                      :options="contentViewOptions"
                      size="small"
                  />
                  <el-tooltip content="复制内容" placement="bottom">
                    <el-button
                        :icon="CopyDocument"
                        circle
                        size="small"
                        :disabled="!fileContent"
                        @click="copyFileContent"
                    />
                  </el-tooltip>
                  <el-tooltip content="下载 Markdown" placement="bottom">
                    <el-button
                        :icon="Download"
                        circle
                        size="small"
                        :disabled="!fileContent"
                        @click="downloadFileContent"
                    />
                  </el-tooltip>
                </div>
              </div>
              <div class="panel-content">
                <div v-if="evidenceResults.length" class="evidence-locator">
                  <div class="evidence-locator-header">
                    <strong>{{ evidenceKind === 'edge' ? '关系出处' : '节点出处' }}</strong>
                    <span>{{ activeEvidenceIndex + 1 }} / {{ evidenceResults.length }}</span>
                    <button type="button" @click="jumpToEvidence(activeEvidenceIndex - 1)">上一个</button>
                    <button type="button" @click="jumpToEvidence(activeEvidenceIndex + 1)">下一个</button>
                  </div>
                  <div class="evidence-result-list">
                    <button
                        v-for="(result, index) in evidenceResults"
                        :key="`${result.bid}-${index}`"
                        type="button"
                        class="evidence-result-item"
                        :class="{ active: index === activeEvidenceIndex }"
                        @click="jumpToEvidence(index)"
                    >
                      <span class="evidence-result-title">{{ result.bid }}</span>
                      <span class="evidence-result-preview">{{ result.preview || '文本块内容为空' }}</span>
                    </button>
                  </div>
                </div>
                <div class="original-content">
                  <div v-if="fileContentLoading" class="loading-content">
                    <el-icon class="is-loading"><Loading /></el-icon>
                    <span>加载文件内容中...</span>
                  </div>
                  <div v-else-if="fileContent" class="document-content">
                    <article
                        v-if="contentViewMode === 'preview'"
                        class="markdown-body"
                        v-html="renderedFileContent"
                    ></article>
                    <pre v-else ref="documentContentRef" class="file-text-content">
                      <code v-if="!sourceHighlightHtml">{{ fileContent }}</code>
                      <code v-else v-html="sourceHighlightHtml"></code>
                    </pre>
                  </div>
                  <div v-else class="empty-content">
                    <el-empty description="无法加载文件内容" />
                  </div>
                </div>
              </div>
            </div>

            <div
                v-if="panelVisible['original'] && getNextVisiblePanel('original')"
                class="panel-resizer"
                role="separator"
                aria-label="调整相邻内容面板宽度"
                aria-orientation="vertical"
                title="拖动调整相邻面板宽度"
                @pointerdown="startPanelResize($event, 'original')"
            ></div>

            <div
                v-if="panelVisible['knowledge-graph']"
                class="panel knowledge-graph-panel"
                :class="{ active: activeTab === 'knowledge-graph' }"
                :style="getPanelStyle('knowledge-graph')"
                data-panel="knowledge-graph"
              >
                <div class="panel-header">
                  <h3>知识图谱</h3>
                </div>
                <div class="panel-content" style="overflow: hidden;">
                  <div v-if="knowledgeGraphUrl" class="knowledge-graph-content">
                    <iframe
                        ref="knowledgeGraphFrameRef"
                        :src="knowledgeGraphUrl"
                        sandbox="allow-scripts allow-modals"
                        class="result-iframe"
                        frameborder="0"
                        @load="handleKnowledgeGraphFrameLoad"
                    ></iframe>
                    <div v-if="knowledgeGraphLoading" class="graph-loading-overlay">
                      <el-icon class="is-loading"><Loading /></el-icon>
                      <span>正在加载图谱并计算节点布局...</span>
                    </div>
                  </div>
                  <div v-else-if="knowledgeGraphLoading" class="loading-content">
                    <el-icon class="is-loading"><Loading /></el-icon>
                    <span>正在准备知识图谱...</span>
                  </div>
                  <div v-else class="empty-content">
                    <el-empty description="暂无知识图谱数据" />
                  </div>
                </div>
              </div>

            <div
                v-if="panelVisible['knowledge-graph'] && getNextVisiblePanel('knowledge-graph')"
                class="panel-resizer"
                role="separator"
                aria-label="调整相邻内容面板宽度"
                aria-orientation="vertical"
                title="拖动调整相邻面板宽度"
                @pointerdown="startPanelResize($event, 'knowledge-graph')"
            ></div>

            <div
                v-if="panelVisible['rag']"
                class="panel rag-panel"
                :class="{ active: activeTab === 'rag' }"
                :style="getPanelStyle('rag')"
                data-panel="rag"
            >
              <div class="panel-header">
                <h3>RAG 问答</h3>
              </div>
              <div class="panel-content">
                <div class="chat-container">
                  <div class="chat-messages" ref="chatMessagesContainer" @scroll="handleChatScroll">
                    <div v-for="(message, index) in chatMessages" :key="index"
                         :class="['message', message.role, {'thinking': message.thinking, 'streaming': message.streaming}]">
                      <div v-if="message.role === 'user'" class="avatar user-avatar">
                        <span>U</span>
                      </div>
                      <div v-else-if="message.role === 'assistant'" class="avatar assistant-avatar">
                        <span>AI</span>
                      </div>
                      <div class="message-content" :class="{'thinking': message.thinking, 'streaming': message.streaming}">
                        <div v-if="message.thinking" class="thinking-indicator">
                          <span></span><span></span><span></span>
                        </div>
                        <div v-else-if="message.streaming" class="streaming-content">
                          <div class="answer">{{ formatTextWithLineBreaks(message.content.answer) }}</div>
                          <div class="cursor-blink"></div>
                          <div v-if="streamingStatus" class="streaming-status">{{ streamingStatus }}</div>
                        </div>
                        <div v-else>
                          <template v-if="typeof message.content === 'object'">
                            <div
                                class="answer"
                                @click="handleRagReferenceClick"
                                v-html="renderRagContent(message.content.answer)"
                            ></div>
                            <div v-if="message.content.material && message.content.material.length > 0" class="material">
                              <div class="material-title">参考资料：</div>
                              <div
                                  class="material-content"
                                  @click="handleRagReferenceClick"
                                  v-html="renderRagContent(message.content.material)"
                              ></div>
                            </div>
                          </template>
                          <template v-else>
                            <div class="answer" @click="handleRagReferenceClick" v-html="renderRagContent(message.content)"></div>
                          </template>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div
                      v-if="showScrollButton"
                      class="scroll-to-bottom-btn"
                      @click="scrollToBottom"
                  >
                    <el-icon><ArrowDown /></el-icon>
                  </div>

                  <div class="chat-input">
                    <div class="input-actions">
                      <el-input
                          v-model="userInput"
                          type="textarea"
                          :autosize="{ minRows: 2, maxRows: 4 }"
                          placeholder="输入问题..."
                          :disabled="chatLoading"
                          @keyup.enter.ctrl="sendMessage"
                      />
                      <div class="button-group">
                        <el-button v-if="chatLoading && enableStreamOutput"
                                   type="warning"
                                   @click="stopRagResponse">
                          停止生成
                        </el-button>
                        <el-button type="primary" :disabled="chatLoading" @click="sendMessage">
                          发送
                        </el-button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <el-popover :show-arrow="false" placement="top-end" popper-class="custom-popover" trigger="hover"
                    :show-after="200" popper-style="width:310px">
          <template #reference>
            <svg-icon icon-name="history" icon-class="history-icon" size="20px"/>
          </template>
          <template #default>
            <div class="theme-header">设置</div>
            <div class="theme-content">
              <div class="setting-section">
                <div class="setting-title">主题</div>
                <div
                    v-for="theme in themeOptions"
                    :key="theme.value"
                    class="theme-item"
                    :class="{ active: currentTheme === theme.value }"
                    @click="changeTheme(theme.value)"
                >
                  <div class="theme-preview" :class="theme.value"></div>
                  <span>{{ theme.name }}</span>
                </div>
              </div>
            </div>
          </template>
        </el-popover>
      </div>
    </div>
    <div v-if="resizeMode" class="resize-shield" aria-hidden="true"></div>
    <teleport to="body">
      <div
        v-if="fileContextMenu.visible && fileContextMenu.file"
        class="file-context-menu"
        :style="{ left: `${fileContextMenu.x}px`, top: `${fileContextMenu.y}px` }"
        @click.stop
        @contextmenu.prevent
      >
        <div class="context-menu-title" :title="fileContextMenu.file.name">
          {{ fileContextMenu.file.name }}
        </div>
        <button
          v-if="['uploading', 'processing', 'updating', 'resuming'].includes(fileContextMenu.file.status)"
          type="button"
          class="context-menu-item"
          @click="handleFileContextAction('pause')"
        >暂停处理</button>
        <button
          v-if="['paused', 'interrupted', 'error'].includes(fileContextMenu.file.status) && fileContextMenu.file.resumable"
          type="button"
          class="context-menu-item"
          @click="handleFileContextAction('resume')"
        >继续处理</button>
        <button
          v-if="fileContextMenu.file.status === 'completed' || (['paused', 'interrupted'].includes(fileContextMenu.file.status) && fileContextMenu.file.partialAvailable)"
          type="button"
          class="context-menu-item"
          @click="handleFileContextAction('view')"
        >查看原文与图谱</button>
        <button
          v-if="fileContextMenu.file.status === 'completed'"
          type="button"
          class="context-menu-item"
          @click="handleFileContextAction('redraw')"
        >重新绘制图谱</button>
        <button
          v-if="fileContextMenu.file.status === 'completed'"
          type="button"
          class="context-menu-item"
          @click="handleFileContextAction('download-package')"
        >下载原文与图谱迁移包</button>
        <button
          v-if="fileContextMenu.file.status === 'completed'"
          type="button"
          class="context-menu-item"
          @click="handleFileContextAction('clear-history')"
        >清除 RAG 历史</button>
        <div
          v-if="['completed', 'paused', 'interrupted', 'error'].includes(fileContextMenu.file.status)"
          class="context-menu-divider"
        ></div>
        <button
          v-if="['completed', 'paused', 'interrupted', 'error'].includes(fileContextMenu.file.status)"
          type="button"
          class="context-menu-item danger"
          @click="handleFileContextAction('delete')"
        >删除文件</button>
        <div v-if="fileContextMenu.file.status === 'pausing'" class="context-menu-hint">
          正在保存当前文本块，请稍候…
        </div>
      </div>
    </teleport>
  </div>
</template>

<style lang="scss" scoped>
.file-context-menu {
  position: fixed;
  z-index: 5000;
  box-sizing: border-box;
  width: 176px;
  padding: 6px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-bg-color);
  box-shadow: 0 8px 28px rgb(0 0 0 / 18%);

  .context-menu-title {
    overflow: hidden;
    padding: 7px 9px;
    color: var(--el-text-color-secondary);
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .context-menu-item {
    display: block;
    width: 100%;
    padding: 8px 10px;
    border: 0;
    border-radius: 5px;
    color: var(--el-text-color-primary);
    background: transparent;
    cursor: pointer;
    font: inherit;
    text-align: left;

    &:hover {
      background: var(--el-fill-color-light);
    }

    &.danger {
      color: var(--el-color-danger);
    }
  }

  .context-menu-divider {
    height: 1px;
    margin: 5px 4px;
    background: var(--el-border-color-lighter);
  }

  .context-menu-hint {
    padding: 8px 9px;
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}

.main-container {
  display: flex;
  box-sizing: border-box;
  height: 100vh;
  padding: 0 12px 8px 0;
  background-color: var(--el-fill-color-lighter);

  .main-content {
    position: relative;
    flex: 1;
    min-width: 0;
    height: 100%;
    width: auto;
    background-color: var(--el-bg-color);
    border-radius: 10px;
    box-shadow: 0 0 #0000, 0 0 #0000, 0 1px 2px 0 rgb(0 0 0 / .05);

    :deep(.el-drawer) {
      box-shadow: none;
      border-right: 1px solid var(--el-border-color-lighter);

      .el-drawer__header {
        padding: 12px 16px;
        margin: 0;
        border-bottom: 1px solid var(--el-border-color-lighter);

        .drawer-manu-header {
          color: var(--el-text-color-primary);
          display: flex;
          align-items: center;
          justify-content: space-between;

          .header {
            line-height: 30px;
            display: flex;
            align-items: center;
            font-weight: 600;

            span {
              margin-left: 4px;
            }
          }

          .close-icon {
            cursor: pointer;
            padding: 4px;
            border-radius: 4px;
          }

          .close-icon:hover {
            background-color: var(--el-fill-color-light);
          }
        }
      }

      .el-drawer__body {
        position: relative;
        display: flex;
        flex-direction: column;
        padding: 0;

        .query-button {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin: 12px 16px;

          .filter {
            line-height: 1.5;
            width: 80px;
            box-sizing: border-box;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: space-between;
            background-color: var(--el-fill-color-light);
            margin-right: 8px;
            padding: 4px 12px;
            border-radius: 6px;
            color: var(--el-text-color-primary);
            user-select: none;

            &:hover {
              background-color: var(--el-fill-color-dark);
            }
          }

          .search-icon {
            cursor: pointer;
            padding: 4px;
            border-radius: 4px;
            color: var(--el-text-color-primary);

            &:hover {
              background-color: var(--el-fill-color-light);
            }
          }
        }

        .search-input {
          display: flex;
          margin: 12px 16px;

          .el-input__wrapper {
            box-sizing: border-box;
            box-shadow: none;
            border-radius: 100px;
            padding: 8px 8px 8px 20px;
            height: 32px;
            margin-right: 16px;
            background-color: var(--el-fill-color-light);
          }

          .el-button {
            color: var(--el-color-primary);
            font-size: 16px;
          }

          .el-button:hover {
            color: var(--el-color-danger);
          }
        }

        .file-list {
          flex: 1;
          padding: 0 16px;
          overflow-y: auto;

          .file-item {
            display: flex;
            flex-direction: column;
            border-bottom: 1px solid var(--el-border-color-light);
            margin-bottom: 8px;
            background-color: var(--el-fill-color-lighter);
            transition: all 0.3s ease;
            border-radius: 8px;
            border: 1px solid transparent;

            &.expanded {
              background-color: var(--el-fill-color-light);
            }

            &.active {
              background-color: var(--el-bg-color) !important;
              border-color: var(--el-border-color-light);
            }

            &:hover {
              background-color: var(--el-fill-color-dark);
            }

            &.can-click {
              cursor: pointer;

              &:hover {
                transform: translateY(-1px);
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
              }

              &.active {
                background-color: var(--el-bg-color) !important;
                border-color: var(--el-color-primary-light-3);
              }
            }

            .file-header {
              display: flex;
              align-items: center;
              justify-content: space-between;
              padding: 12px 16px;
              cursor: pointer;
              transition: background-color 0.3s;

              .file-actions {
                display: flex;
                align-items: center;
                gap: 12px;

                .delete-action {
                  display: flex;
                  align-items: center;
                  gap: 8px;

                  .delete-icon, .clear-icon {
                    cursor: pointer;
                    width: 16px;
                    height: 16px;
                    padding: 4px;
                    border-radius: 4px;
                    transition: all 0.3s ease;
                    opacity: 0.6;

                    &:hover {
                      opacity: 1;
                    }
                  }

                  .delete-icon:hover {
                    background-color: var(--el-color-danger-light-9);
                  }

                  .clear-icon:hover {
                    background-color: var(--el-color-warning-light-9);
                  }
                }
              }

              .file-info {
                display: flex;
                align-items: center;
                flex: 1;
                min-width: 0; // 防止子元素溢出

                .file-icon {
                  margin-right: 12px;
                  font-size: 20px;
                  flex-shrink: 0;

                  &.uploading, &.processing, &.updating, &.resuming, &.pausing {
                    color: var(--el-color-primary);
                    animation: spin 1.5s infinite linear;
                  }

                  &.completed {
                    color: var(--el-color-success);
                  }

                  &.error {
                    color: var(--el-color-danger);
                  }

                  &.interrupted {
                    color: var(--el-color-warning);
                  }

                  &.paused {
                    color: var(--el-color-warning);
                  }
                }

                .file-name-container {
                  flex: 1;
                  min-width: 0; // 防止子元素溢出

                  .file-name {
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-bottom: 4px;
                    color: var(--el-text-color-primary);
                    font-weight: 500;
                    max-width: 100%;
                  }
                }
              }

              .file-status {
                font-size: 12px;
                white-space: nowrap;
                flex-shrink: 0;

                &.uploading, &.processing, &.updating, &.resuming, &.pausing {
                  color: var(--el-color-primary);
                }

                &.completed {
                  color: var(--el-color-success);
                }

                &.error {
                  color: var(--el-color-danger);
                }

                &.interrupted {
                  color: var(--el-color-warning);
                }

                &.paused {
                  color: var(--el-color-warning);
                }
              }
            }

            .file-progress {
              margin: -5px 16px 12px;

              .file-progress-detail {
                margin-top: 5px;
                color: var(--el-text-color-secondary);
                font-size: 11px;
                line-height: 1.35;
              }

              .progress-summary,
              .progress-estimate {
                white-space: normal;
                overflow-wrap: anywhere;
              }

              .progress-estimate {
                margin-top: 2px;
                color: var(--el-text-color-placeholder);
              }
            }

            .file-recovery {
              margin: -5px 16px 12px;

              .recovery-summary {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
                margin-top: 5px;
                color: var(--el-color-warning);
                font-size: 11px;
              }
            }

            .file-entities-card {
              padding: 12px 16px;
              border-top: 1px dashed var(--el-border-color-light);
              background-color: var(--el-bg-color-page);
              overflow: hidden;
              transition: max-height 0.3s ease-in-out;

              .loading-entities {
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 12px 0;
                color: var(--el-text-color-secondary);

                .el-icon {
                  margin-right: 8px;
                  font-size: 18px;
                }
              }

              .entities-error {
                padding: 8px 0;
              }

              .entities-title {
                font-size: 14px;
                font-weight: 600;
                margin-bottom: 8px;
                color: var(--el-text-color-primary);
              }

              .entities-content {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;

                .entity-tag {
                  margin-right: 0;
                  cursor: default;
                }
              }

              .no-entities {
                padding: 8px 0;
              }
            }
          }
        }

        .pagination {
          margin: 16px auto;

          .el-pagination.is-background {
            .btn-prev, .btn-next, .el-pager li {
              font-size: 14px;
              margin: 0 2px;
              padding: 0 6px;
              border-radius: 6px;
              background-color: transparent;
            }

            .btn-prev:hover, .btn-next:hover, .el-pager li:hover {
              background-color: var(--el-fill-color-dark);
            }

            .btn-prev[disabled]:hover, .btn-next[disabled]:hover {
              background-color: transparent;
            }

            .btn-prev.is-active, .btn-next.is-active, .el-pager li.is-active {
              font-weight: 400;
              background-color: var(--el-fill-color-darker);
              color: var(--el-color-primary);
            }
          }
        }
      }

      .file-list-resizer {
        position: absolute;
        top: 0;
        right: 0;
        bottom: 0;
        z-index: 3;
        width: 8px;
        cursor: col-resize;
        touch-action: none;

        &::after {
          content: '';
          position: absolute;
          top: 0;
          right: 0;
          bottom: 0;
          width: 1px;
          background-color: var(--el-border-color-lighter);
          transition: width 0.15s ease, background-color 0.15s ease;
        }

        &:hover::after,
        &:active::after {
          width: 3px;
          background-color: var(--el-color-primary);
        }
      }
    }

    .content {
      display: flex;
      justify-content: center;
      align-items: center;
      height: 100%;
      transition: margin-left 0.3s;

      &.is-resizing {
        transition: none;
      }

      .upload-view {
        display: flex;
        justify-content: center;
        align-items: center;
        width: 100%;
        height: 100%;

        .background {
          position: absolute;
          height: 70%;
          width: 70%;
          background-image: url("@/assets/images/bg.png");
          background-size: cover;
          background-repeat: no-repeat;
          // 在暗色主题下隐藏背景
          [data-theme="dark"] & {
            display: none;
          }
        }

        .upload {
          text-align: center;
          width: 50%;
          z-index: 1;

          h1 {
            margin-bottom: 40px;
            color: var(--el-text-color-primary);
          }

          :deep(.el-upload) {
            .el-upload-dragger {
              background-color: var(--el-fill-color-lighter);
              border-color: var(--el-border-color-light);
              box-shadow: 0 4px 40px 2px #12131608;
              border-radius: 24px;
              height: 280px;
            }

            .el-upload-dragger:hover {
              border-color: var(--el-color-primary-light-3);
            }

            .upload-text {
              color: var(--el-text-color-primary);
              font-size: 18px;
              font-weight: 600;
              margin-bottom: 12px;
            }

            p {
              font-size: 12px;
              margin-bottom: 2px;
              color: var(--el-text-color-secondary);
            }

            .el-button {
              height: 36px;
              border-radius: 8px;
              padding: 4px 12px;
              line-height: 20px;
              color: var(--el-text-color-primary);
              margin-top: 24px;
              border: 1px solid var(--el-border-color-lighter);
            }

            .el-button:hover {
              background-color: var(--el-fill-color-light);
            }
          }
        }
      }

      .result-view {
        width: 100%;
        height: 100%;
        display: flex;
        flex-direction: column;
        min-width: 0;
        background-color: var(--el-bg-color-page);

        .file-tabs {
          display: flex;
          align-items: center;
          flex-shrink: 0;
          gap: 18px;
          box-sizing: border-box;
          padding: 0 18px;
          height: 60px;
          border-bottom: 1px solid var(--el-border-color-lighter);
          background-color: var(--el-bg-color);

          .file-info {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 180px;
            max-width: 240px;

            .file-mark {
              display: flex;
              align-items: center;
              justify-content: center;
              width: 32px;
              height: 32px;
              flex: 0 0 32px;
              border-radius: 6px;
              color: #087f5b;
              background-color: #e6fcf5;

              svg {
                width: 17px;
                height: 17px;
              }
            }

            .file-identity {
              display: flex;
              flex-direction: column;
              min-width: 0;
              gap: 2px;
            }

            .file-context {
              color: var(--el-text-color-secondary);
              font-size: 10px;
              line-height: 1.2;
            }

            .filename {
              display: block;
              overflow: hidden;
              text-overflow: ellipsis;
              white-space: nowrap;
              color: var(--el-text-color-primary);
              font-size: 13px;
              font-weight: 600;
            }
          }

          .tabs-container {
            display: flex;
            align-items: center;
            flex: 1;
            height: 100%;
            min-width: 0;
            gap: 4px;
            overflow-x: auto;
            overflow-y: hidden;

            .tab-item {
              display: flex;
              align-items: center;
              box-sizing: border-box;
              height: 38px;
              padding: 0 12px;
              flex-shrink: 0;
              cursor: pointer;
              position: relative;
              border: 1px solid transparent;
              border-radius: 6px;
              color: var(--el-text-color-regular);
              font-size: 13px;
              transition: background-color 0.2s ease, color 0.2s ease, border-color 0.2s ease;

              .el-icon {
                margin-right: 8px;
                font-size: 16px;
              }

              .tab-actions {
                display: flex;
                margin-left: 6px;

                .panel-toggle {
                  display: flex;
                  align-items: center;
                  justify-content: center;
                  box-sizing: border-box;
                  width: 22px;
                  height: 22px;
                  padding: 0;
                  border-radius: 4px;
                  cursor: pointer;
                  border: 0;
                  background-color: transparent;
                  color: var(--el-text-color-secondary);
                  transition: all 0.2s ease;

                  &.is-active {
                    color: var(--el-color-primary);
                  }

                  &:hover {
                    background-color: var(--el-fill-color-dark);
                  }

                  .el-icon {
                    margin: 0;
                    font-size: 14px;
                  }
                }
              }

              &:hover {
                background-color: var(--el-fill-color-light);
              }

              &.active {
                color: var(--el-color-primary);
                border-color: var(--el-color-primary-light-7);
                background-color: var(--el-color-primary-light-9);

                &::after {
                  content: '';
                  position: absolute;
                  bottom: -12px;
                  left: 12px;
                  right: 12px;
                  height: 3px;
                  border-radius: 3px 3px 0 0;
                  background-color: var(--el-color-primary);
                }
              }

              &.disabled {
                opacity: 0.5;
                pointer-events: none;

                .tab-actions {
                  pointer-events: auto;
                  opacity: 1;
                }
              }
            }
          }
        }

        .content-panels {
          position: relative;
          display: flex;
          flex: 1;
          min-height: 0;
          overflow: hidden;
          background-color: var(--el-bg-color-page);

          .panel {
            display: flex;
            flex-direction: column;
            flex: 1;
            min-width: 0;
            background-color: var(--el-bg-color);
            transition: flex 0.15s ease;

            .panel-header {
              display: flex;
              align-items: center;
              justify-content: space-between;
              box-sizing: border-box;
              min-height: 52px;
              padding: 0 16px;
              gap: 12px;
              border-bottom: 1px solid var(--el-border-color-lighter);
              background-color: var(--el-bg-color);

              .panel-title {
                display: flex;
                align-items: baseline;
                gap: 8px;
                min-width: 0;
              }

              h3 {
                margin: 0;
                font-size: 14px;
                font-weight: 600;
                color: var(--el-text-color-primary);
                white-space: nowrap;
              }

              .content-stats {
                color: var(--el-text-color-secondary);
                font-size: 11px;
                white-space: nowrap;
              }

              .document-tools {
                display: flex;
                align-items: center;
                gap: 6px;
                flex-shrink: 0;

                :deep(.el-segmented) {
                  --el-segmented-item-selected-bg-color: var(--el-bg-color);
                  min-width: 108px;
                }

                .el-button + .el-button {
                  margin-left: 0;
                }
              }

              .el-button {
                &.el-button--primary {
                  &:not(.is-disabled) {
                    background-color: var(--el-color-primary);
                    border-color: var(--el-color-primary);
                    color: #ffffff;

                    &:hover {
                      background-color: var(--el-color-primary-light-3);
                      border-color: var(--el-color-primary-light-3);
                    }
                  }
                }

                &.el-button--default {
                  &:not(.is-disabled) {
                    background-color: var(--el-fill-color-light);
                    border-color: var(--el-border-color);
                    color: var(--el-text-color-primary);

                    &:hover {
                      color: var(--el-color-primary);
                      border-color: var(--el-color-primary);
                    }
                  }
                }
              }
            }

            .panel-content {
              flex: 1;
              display: flex;
              flex-direction: column;
              overflow: hidden;
              padding: 0;
              position: relative;

              .evidence-locator {
                flex: none;
                padding: 10px 14px;
                border-bottom: 1px solid var(--el-border-color-lighter);
                background: var(--el-fill-color-light);

                .evidence-locator-header {
                  display: flex;
                  align-items: center;
                  gap: 8px;
                  margin-bottom: 8px;
                  color: var(--el-text-color-secondary);
                  font-size: 12px;

                  strong {
                    color: var(--el-text-color-primary);
                  }

                  span {
                    margin-right: auto;
                  }

                  button {
                    padding: 3px 8px;
                    border: 1px solid var(--el-border-color);
                    border-radius: 4px;
                    background: var(--el-bg-color);
                    color: var(--el-text-color-regular);
                    cursor: pointer;
                  }

                  button:hover {
                    border-color: var(--el-color-primary);
                    color: var(--el-color-primary);
                  }
                }

                .evidence-result-list {
                  display: flex;
                  gap: 6px;
                  max-width: 100%;
                  overflow-x: auto;
                }

                .evidence-result-item {
                  display: flex;
                  flex: 0 0 190px;
                  flex-direction: column;
                  gap: 3px;
                  min-width: 0;
                  padding: 6px 8px;
                  border: 1px solid var(--el-border-color-lighter);
                  border-radius: 5px;
                  background: var(--el-bg-color);
                  color: var(--el-text-color-regular);
                  text-align: left;
                  cursor: pointer;
                }

                .evidence-result-item.active {
                  border-color: var(--el-color-primary);
                  background: var(--el-color-primary-light-9);
                }

                .evidence-result-title {
                  overflow: hidden;
                  color: var(--el-color-primary);
                  font-size: 11px;
                  font-weight: 600;
                  text-overflow: ellipsis;
                  white-space: nowrap;
                }

                .evidence-result-preview {
                  overflow: hidden;
                  color: var(--el-text-color-secondary);
                  font-size: 11px;
                  text-overflow: ellipsis;
                  white-space: nowrap;
                }
              }

              .original-content {
                box-sizing: border-box;
                flex: 1;
                min-height: 0;
                height: 100%;
                container-type: inline-size;
                padding: 24px;
                overflow-y: auto;
                font-family: system-ui, -apple-system, sans-serif;
                background-color: var(--el-bg-color-page);

                .loading-content {
                  display: flex;
                  flex-direction: column;
                  align-items: center;
                  justify-content: center;
                  height: 100%;
                  color: var(--el-text-color-secondary);

                  .el-icon {
                    font-size: 32px;
                    margin-bottom: 12px;
                  }
                }

                .document-content {
                  box-sizing: border-box;
                  width: min(100%, 920px);
                  min-height: 100%;
                  margin: 0 auto;
                  padding: clamp(18px, 4cqw, 40px) clamp(16px, 5cqw, 48px) clamp(32px, 6cqw, 56px);
                  border: 1px solid var(--el-border-color-lighter);
                  border-radius: 6px;
                  background-color: var(--el-bg-color);
                  box-shadow: 0 8px 28px rgb(0 0 0 / 5%);
                }

                .file-text-content {
                  box-sizing: border-box;
                  width: 100%;
                  min-height: 100%;
                  margin: 0;
                  padding: 20px;
                  overflow: auto;
                  white-space: pre-wrap;
                  overflow-wrap: anywhere;
                  word-break: break-word;
                  line-height: 1.7;
                  border: 1px solid var(--el-border-color-lighter);
                  border-radius: 6px;
                  background-color: var(--el-fill-color-lighter);
                  color: var(--el-text-color-primary);
                  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
                  font-size: clamp(10px, 1.35cqw, 13px);

                  :deep(.source-highlight) {
                    padding: 1px 2px;
                    border-radius: 2px;
                    background: #fef08a;
                    color: inherit;
                  }
                }

                :deep(.markdown-body) {
                  color: var(--el-text-color-primary);
                  font-size: clamp(12px, 1.55cqw, 15px);
                  line-height: 1.8;
                  overflow-wrap: anywhere;

                  > :first-child {
                    margin-top: 0;
                  }

                  > :last-child {
                    margin-bottom: 0;
                  }

                  h1,
                  h2,
                  h3,
                  h4,
                  h5,
                  h6 {
                    color: var(--el-text-color-primary);
                    line-height: 1.35;
                    letter-spacing: 0;
                  }

                  h1 {
                    margin: 0 0 24px;
                    padding-bottom: 14px;
                    border-bottom: 1px solid var(--el-border-color-lighter);
                    font-size: 28px;
                    font-weight: 700;
                  }

                  h2 {
                    margin: 36px 0 16px;
                    padding-bottom: 8px;
                    border-bottom: 1px solid var(--el-border-color-lighter);
                    font-size: 22px;
                    font-weight: 650;
                  }

                  h3 {
                    margin: 28px 0 12px;
                    font-size: 18px;
                    font-weight: 650;
                  }

                  h4,
                  h5,
                  h6 {
                    margin: 24px 0 10px;
                    font-size: 15px;
                    font-weight: 650;
                  }

                  p {
                    margin: 0 0 16px;
                  }

                  ul,
                  ol {
                    margin: 0 0 18px;
                    padding-left: 1.6em;
                  }

                  li {
                    margin: 5px 0;
                  }

                  li > ul,
                  li > ol {
                    margin: 4px 0 0;
                  }

                  a {
                    color: var(--el-color-primary);
                    text-decoration: none;
                    border-bottom: 1px solid var(--el-color-primary-light-7);
                  }

                  a:hover {
                    border-bottom-color: var(--el-color-primary);
                  }

                  strong {
                    font-weight: 650;
                  }

                  blockquote {
                    margin: 20px 0;
                    padding: 12px 16px;
                    border-left: 4px solid #20a67a;
                    background-color: var(--el-fill-color-lighter);
                    color: var(--el-text-color-regular);
                  }

                  blockquote > :last-child {
                    margin-bottom: 0;
                  }

                  code {
                    padding: 2px 6px;
                    border-radius: 4px;
                    background-color: var(--el-fill-color-dark);
                    color: #c2415d;
                    font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
                    font-size: 0.9em;
                  }

                  pre {
                    margin: 20px 0;
                    padding: 16px 18px;
                    overflow: auto;
                    border: 1px solid var(--el-border-color-lighter);
                    border-radius: 6px;
                    background-color: #171a21;
                    line-height: 1.65;
                  }

                  pre code {
                    padding: 0;
                    background: transparent;
                    color: #e6edf3;
                    font-size: 13px;
                  }

                  table {
                    display: block;
                    width: 100%;
                    margin: 20px 0;
                    overflow-x: auto;
                    border-collapse: collapse;
                    font-size: 14px;
                  }

                  th,
                  td {
                    padding: 10px 12px;
                    border: 1px solid var(--el-border-color-lighter);
                    text-align: left;
                    white-space: nowrap;
                  }

                  th {
                    background-color: var(--el-fill-color-light);
                    font-weight: 650;
                  }

                  tr:nth-child(even) td {
                    background-color: var(--el-fill-color-lighter);
                  }

                  hr {
                    height: 1px;
                    margin: 32px 0;
                    border: 0;
                    background-color: var(--el-border-color-lighter);
                  }

                  img {
                    display: block;
                    max-width: 100%;
                    height: auto;
                    margin: 22px auto;
                    border-radius: 6px;
                  }

                  input[type="checkbox"] {
                    margin-right: 7px;
                    accent-color: var(--el-color-primary);
                  }
                }
              }

              .result-iframe {
                width: 100%;
                height: 100%;
                border: none;
                display: block;
              }

              .chat-container {
                display: flex;
                flex-direction: column;
                height: 100%;

                .chat-messages {
                  flex: 1;
                  overflow-y: auto;
                  padding: 20px 16px;
                  display: flex;
                  flex-direction: column;
                  gap: 16px;
                  background-color: var(--el-bg-color-page);

                  .message {
                    display: flex;

                    &.user {
                      justify-content: flex-end;

                      .message-content {
                        background-color: var(--chat-user-bubble-bg, var(--el-color-primary-light-9));
                        color: var(--chat-user-bubble-text, var(--el-text-color-primary));
                        border-radius: 12px 12px 0 12px;
                      }
                    }

                    &.assistant {
                      justify-content: flex-start;

                      .message-content {
                        background-color: var(--chat-assistant-bubble-bg, var(--el-bg-color));
                        color: var(--chat-assistant-bubble-text, var(--el-text-color-primary));
                        border: 1px solid var(--el-border-color-lighter);
                        border-radius: 8px;

                        &.thinking {
                          padding: 12px 20px;
                        }
                      }
                    }

                    &.system {
                      display: none;
                    }

                    .avatar {
                      width: 32px;
                      height: 32px;
                      flex: 0 0 32px;
                      border-radius: 7px;
                      display: flex;
                      align-items: center;
                      justify-content: center;
                      margin: 0 8px;

                      &.user-avatar {
                        background-color: var(--el-color-primary);
                        color: white;
                      }

                      &.assistant-avatar {
                        background-color: #087f5b;
                        color: white;
                      }
                    }

                    .message-content {
                      max-width: 70%;
                      padding: 12px 16px;
                      line-height: 1.5;
                      white-space: pre-wrap;
                      word-break: break-word;

                      .thinking-indicator {
                        display: flex;
                        gap: 4px;

                        span {
                          width: 8px;
                          height: 8px;
                          border-radius: 50%;
                          background-color: var(--el-text-color-secondary);
                          animation: pulse 1.5s infinite;

                          &:nth-child(2) {
                            animation-delay: 0.2s;
                          }

                          &:nth-child(3) {
                            animation-delay: 0.4s;
                          }
                        }
                      }

                      .answer {
                        margin-bottom: 8px;
                        line-height: 1.6;

                        :deep(.rag-reference) {
                          padding: 1px 3px;
                          border-bottom: 1px solid var(--el-color-primary);
                          border-radius: 3px;
                          background: var(--el-color-primary-light-9);
                          color: var(--el-color-primary);
                          cursor: pointer;
                          text-decoration: none;
                        }
                      }

                      .material {
                        margin-top: 12px;
                        padding: 8px 12px;
                        background-color: var(--el-fill-color-light);
                        border-radius: 6px;

                        .material-title {
                          font-size: 12px;
                          color: var(--el-text-color-secondary);
                          margin-bottom: 4px;
                        }

                        .material-content {
                          font-size: 13px;
                          color: var(--el-text-color-regular);
                          line-height: 1.5;
                          white-space: pre-wrap;

                          :deep(.rag-reference) {
                            padding: 1px 3px;
                            border-bottom: 1px solid var(--el-color-primary);
                            border-radius: 3px;
                            background: var(--el-color-primary-light-9);
                            color: var(--el-color-primary);
                            cursor: pointer;
                            text-decoration: none;
                          }
                        }
                      }
                    }
                  }
                }

                .chat-input {
                  padding: 16px;
                  border-top: 1px solid var(--el-border-color-lighter);
                  background-color: var(--el-bg-color);

                  .input-actions {
                    display: flex;
                    flex-direction: column;
                    gap: 10px;

                    .button-group {
                      display: flex;
                      justify-content: flex-end;
                      gap: 10px;
                    }
                  }

                  :deep(.el-textarea) {
                    .el-textarea__inner {
                      background-color: var(--el-fill-color-dark);
                      border-color: var(--el-border-color);
                      color: var(--el-text-color-primary);

                      &:hover {
                        border-color: var(--el-border-color-darker);
                      }

                      &:focus {
                        border-color: var(--el-color-primary);
                        background-color: var(--el-fill-color-darker);
                      }

                      &::placeholder {
                        color: var(--el-text-color-secondary);
                      }
                    }
                  }

                  .el-button {
                    align-self: flex-end;
                  }
                }
              }
            }
          }

          .panel-resizer {
            position: relative;
            z-index: 2;
            flex: 0 0 8px;
            align-self: stretch;
            cursor: col-resize;
            background-color: var(--el-bg-color-page);
            touch-action: none;

            &::after {
              content: '';
              position: absolute;
              top: 0;
              bottom: 0;
              left: 50%;
              width: 1px;
              background-color: var(--el-border-color-lighter);
              transform: translateX(-50%);
              transition: width 0.15s ease, background-color 0.15s ease;
            }

            &:hover::after,
            &:active::after {
              width: 3px;
              background-color: var(--el-color-primary);
            }
          }

          &.is-resizing {
            .panel {
              transition: none;
            }

            .panel-resizer::after {
              width: 3px;
              background-color: var(--el-color-primary);
            }
          }
        }
      }

      .history-icon {
        cursor: pointer;
        position: fixed;
        top: 32px;
        right: 48px;
        padding: 8px;
        background-color: var(--el-fill-color-light);
        border-radius: 8px;
      }

      .history-icon:hover {
        background-color: var(--el-fill-color-dark);
      }
    }
  }

  :deep(.main-content > div:first-of-type) {
    position: absolute !important;
    z-index: 0 !important;
  }
}

.resize-shield {
  position: fixed;
  inset: 0;
  z-index: 5000;
  cursor: col-resize;
  touch-action: none;
}

.history-header {
  color: var(--el-text-color-primary);
  font-size: 16px;
  font-weight: 600;
  padding: 0 24px;
  margin: 16px 0;
}

.history-content {
  padding: 0 16px;
  margin-bottom: 16px;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse {
  0%, 100% {
    opacity: 0.5;
    transform: scale(0.8);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}

.tab-item {
  display: flex;
  align-items: center;
  height: 100%;
  padding: 0 16px;
  cursor: pointer;
  position: relative;
  border-right: 1px solid var(--el-border-color-light);

  .el-icon {
    margin-right: 8px;
  }

  .tab-actions {
    margin-left: 8px;

    .panel-toggle {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      border-radius: 50%;
      cursor: pointer;
      border: 1px solid var(--el-border-color);
      background-color: var(--el-fill-color-light);
      color: var(--el-text-color-secondary);
      transition: all 0.2s ease;

      &.is-active {
        background-color: var(--el-color-primary);
        color: white;
        border-color: var(--el-color-primary);
      }

      &:hover {
        opacity: 0.8;
      }
    }
  }

  &:hover {
    background-color: var(--el-fill-color-light);
  }

  &.active {
    color: var(--el-color-primary);

    &::after {
      content: '';
      position: absolute;
      bottom: 0;
      left: 0;
      width: 100%;
      height: 2px;
      background-color: var(--el-color-primary);
    }
  }

  &.disabled {
    opacity: 0.5;
    pointer-events: none;

    .tab-actions {
      pointer-events: auto;
      opacity: 1;
    }
  }
}

.panel-toggle-btn {
  /* 确保按钮始终显示 */
  display: flex !important;
  align-items: center;
  justify-content: center;
}

.knowledge-graph-content {
  position: relative;
  height: 100%;
  overflow: hidden;

  .result-iframe {
    width: 100%;
    height: 100%;
    border: none;
    display: block;
    background-color: white;
  }

  .graph-loading-overlay {
    position: absolute;
    z-index: 5;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    background: var(--el-bg-color);
    color: var(--el-text-color-secondary);
    font-size: 13px;

    .el-icon {
      color: var(--el-color-primary);
      font-size: 28px;
    }
  }
}

.theme-header {
  color: var(--el-text-color-primary);
  font-size: 16px;
  font-weight: 600;
  padding: 0 24px;
  margin: 16px 0;
}

.theme-content {
  padding: 0 16px;
  margin-bottom: 16px;

  .setting-section {
    margin-bottom: 20px;

    .setting-title {
      font-size: 14px;
      font-weight: 500;
      color: var(--el-text-color-primary);
      margin-bottom: 12px;
      border-top: 1px solid var(--el-border-color-lighter);
      padding-top: 16px;

      &:first-child {
        border-top: none;
        padding-top: 0;
      }
    }

    .setting-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 12px;
      margin-bottom: 8px;
      border-radius: 6px;

      &:hover {
        background-color: var(--el-fill-color-light);
      }

      span {
        font-size: 14px;
        color: var(--el-text-color-primary);
      }
    }
  }

  .theme-item {
    display: flex;
    align-items: center;
    padding: 8px 12px;
    cursor: pointer;
    border-radius: 6px;
    margin-bottom: 8px;
    transition: all 0.3s ease;
    color: var(--el-text-color-primary);

    &:hover {
      background-color: var(--el-fill-color-light);
    }

    &.active {
      background-color: var(--el-fill-color-light);
      color: var(--el-color-primary);
    }

    .theme-preview {
      width: 24px;
      height: 24px;
      border-radius: 4px;
      margin-right: 12px;
      border: 1px solid var(--el-border-color);
      flex-shrink: 0;

      &.default {
        background-color: #ffffff;
      }

      &.dark {
        background-color: #1a1a1a;
        border-color: #ffffff;
      }

      &.blue {
        background-color: #409eff;
      }

      &.green {
        background-color: #67c23a;
      }
    }

    span {
      font-size: 14px;
    }
  }
}

// 添加滚动按钮样式
.chat-container {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;

  .scroll-to-bottom-btn {
    position: absolute;
    bottom: 80px;
    right: 16px;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background-color: var(--el-color-primary);
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    z-index: 10;
    transition: all 0.3s ease;

    &:hover {
      background-color: var(--el-color-primary-light-3);
      transform: translateY(-2px);
    }

    .el-icon {
      font-size: 20px;
    }
  }

  .chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    scroll-behavior: smooth;

    .message {
      display: flex;

      &.streaming {
        .message-content {
          .streaming-content {
            display: flex;
            align-items: flex-start;
            flex-direction: column;

            .answer {
              white-space: pre-wrap;
              word-break: break-word;
              width: 100%;
            }

            .cursor-blink {
              display: inline-block;
              width: 2px;
              height: 16px;
              background-color: var(--el-color-primary);
              margin-left: 2px;
              animation: cursor-blink 0.8s infinite;
            }

            .streaming-status {
              font-size: 12px;
              color: var(--el-color-info);
              margin-top: 4px;
              font-style: italic;
            }
          }
        }
      }
    }
  }
}

@keyframes cursor-blink {
  0%, 100% {
    opacity: 0;
  }
  50% {
    opacity: 1;
  }
}

// 自定义弹出框样式
:deep(.el-popover.custom-popover) {
  padding: 0 0 12px 0;
  border-radius: 8px;
  background-color: #fff;
  border: none;

  [data-theme="dark"] & {
    background-color: #2b2b2b;
    border: 1px solid #3a3a3a;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  }
}

// 修改暗色主题下的样式
[data-theme="dark"] {
  .file-item {
    &.active {
      background-color: var(--el-bg-color) !important;
      border-color: var(--el-border-color-light);
    }

    &.can-click.active:hover {
      border-color: var(--el-color-primary-light-3);
    }

    .delete-action {
      .delete-icon {
        filter: invert(1); // 反转SVG颜色
        opacity: 0.4;

        &:hover {
          opacity: 0.8;
          background-color: var(--el-color-danger-light-3);
        }
      }
    }
  }

  // 主题切换界面样式
  .theme-header {
    color: #e5e5e5;
    border-bottom: 1px solid #3a3a3a;
    background-color: #2b2b2b;
    margin: 0;
    padding: 16px 24px;
  }

  .theme-content {
    background-color: #2b2b2b;

    .theme-item {
      color: #b0b0b0;
      transition: all 0.3s ease;

      &:hover {
        background-color: #363636;
        color: #e5e5e5;
      }

      &.active {
        background-color: #363636;
        color: var(--el-color-primary);
      }

      .theme-preview {
        border-color: #4a4a4a;

        &.dark {
          border-color: #5a5a5a;
        }
      }

      span {
        font-size: 14px;
        font-weight: 500;
      }
    }
  }
}

// 添加过渡动画
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@keyframes spin {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}

// 暗色主题适配
[data-theme="dark"] {
  .file-item {
    &.active {
      background-color: var(--el-bg-color) !important;
      border-color: var(--el-border-color-light);
    }

    &.can-click.active:hover {
      border-color: var(--el-color-primary-light-3);
    }
  }
}

// 添加其他主题的适配
[data-theme="blue"], [data-theme="green"] {
  .file-item {
    &.active {
      background-color: var(--el-bg-color) !important;
      border-color: var(--el-border-color);
    }

    &.can-click.active:hover {
      border-color: var(--el-color-primary);
    }
  }
}

.filter-content {
  padding: 16px;

  .filter-section {
    margin-bottom: 20px;

    .filter-title {
      font-size: 14px;
      font-weight: 500;
      color: var(--el-text-color-primary);
      margin-bottom: 12px;
    }

    .filter-options {
      .el-radio-group {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
    }
  }

  .filter-actions {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid var(--el-border-color-light);
  }
}

.message {
  &.streaming {
    .message-content {
      .streaming-content {
        display: flex;
        align-items: flex-start;
        flex-direction: column;

        .answer {
          white-space: pre-wrap;
          word-break: break-word;
          width: 100%;
        }

        .cursor-blink {
          display: inline-block;
          width: 2px;
          height: 16px;
          background-color: var(--el-color-primary);
          margin-left: 2px;
          animation: cursor-blink 0.8s infinite;
        }
      }
    }
  }
}

@keyframes cursor-blink {
  0%, 100% {
    opacity: 0;
  }
  50% {
    opacity: 1;
  }
}

// 添加流式输出状态提示样式
.streaming-status {
  font-size: 12px;
  color: var(--el-color-info);
  margin-top: 4px;
  font-style: italic;
}

// 优化聊天内容区域滚动
.chat-messages {
  height: calc(100% - 100px);
  overflow-y: auto;
  scroll-behavior: smooth;
}

// 添加以下代码到样式部分的末尾：
.answer {
  white-space: pre-wrap !important;
  word-break: break-word;
  line-height: 1.6;
  width: 100%;
}

@media (max-width: 1100px) {
  .main-container .main-content .content .result-view {
    .file-tabs {
      gap: 10px;

      .file-info {
        min-width: 150px;
        max-width: 180px;
      }
    }

    .content-panels .panel .panel-content .original-content {
      padding: 16px;

      .document-content {
        padding: 30px 28px 42px;
      }
    }
  }
}

@media (max-width: 820px) {
  .main-container {
    padding-right: 0;

    .main-content {
      border-radius: 0;

      :deep(.el-drawer) {
        width: min(86vw, 320px) !important;

        .file-list-resizer {
          display: none;
        }
      }

      .content {
        margin-left: 0 !important;

        .result-view {
        .file-tabs {
          align-items: stretch;
          flex-direction: column;
          gap: 0;
          height: auto;
          padding: 8px 12px 0;

          .file-info {
            min-width: 0;
            max-width: 100%;
            height: 38px;
          }

          .tabs-container {
            height: 44px;

            .tab-item.active::after {
              bottom: 0;
            }
          }
        }

        .content-panels {
          .panel-resizer {
            display: none;
          }

          .panel {
            display: none;
            min-width: 0 !important;
            border-right: 0;

            &.active {
              display: flex;
            }

            .panel-header {
              flex-wrap: wrap;
              min-height: 58px;
              height: auto;
              padding: 8px 12px;

              .content-stats {
                display: none;
              }
            }

            .panel-content .original-content {
              padding: 0;

              .document-content {
                width: 100%;
                min-height: 100%;
                padding: 26px 20px 40px;
                border: 0;
                border-radius: 0;
                box-shadow: none;
              }
            }
          }
        }
      }
      }
    }
  }

  .history-icon {
    top: auto !important;
    right: 16px !important;
    bottom: 16px;
    z-index: 20;
    border: 1px solid var(--el-border-color-lighter);
    box-shadow: 0 4px 16px rgb(0 0 0 / 10%);
  }
}
</style>
