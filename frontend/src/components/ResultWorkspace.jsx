import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Bot, ChevronLeft, Eye, EyeOff, FileText, Network,
  PanelLeftClose, PanelLeftOpen, X,
} from 'lucide-react';
import api, { encodePathSegment, getApiErrorMessage } from '../api/client.js';
import { blockId, inferIndexedHighlightTerms } from '../lib/evidence.js';
import OriginalDocumentPanel from './OriginalDocumentPanel.jsx';
import GraphPanel from './GraphPanel.jsx';
import RagPanel from './RagPanel.jsx';

const PANEL_MIN_WIDTH = 280;
const panelOrder = ['original', 'graph', 'rag'];
const panelInfo = {
  original: { label: '原文', icon: FileText },
  graph: { label: '知识图谱', icon: Network },
  rag: { label: 'RAG 问答', icon: Bot },
};
const emptyEvidence = () => ({ kind: 'node', results: [], terms: {}, requestId: 0, fullDocument: false });

export default function ResultWorkspace({
  file, files, libraryOpen, onLibraryToggle, onClose, onSwitchFile,
  settings, onSettings, toast, onDirtyChange, onDocumentSaved, layoutResizing = false,
}) {
  const [active, setActive] = useState(() => window.innerWidth <= 820 ? 'original' : 'rag');
  const [visible, setVisible] = useState({ original: true, graph: true, rag: true });
  const [panelSizes, setPanelSizes] = useState({});
  const [resizing, setResizing] = useState(false);
  const [evidence, setEvidence] = useState(emptyEvidence);
  const [graphHighlight, setGraphHighlight] = useState(null);
  const [locatingCitation, setLocatingCitation] = useState(false);
  const containerRef = useRef(null);
  const evidenceRequestRef = useRef(0);
  const sourceCacheRef = useRef({ filename: '', data: null, promise: null });
  const resizeCleanupRef = useRef(null);
  const [highlightIndexVersion, setHighlightIndexVersion] = useState(0);
  const previousFileStatusRef = useRef({ name: file.name, status: file.status });

  const available = files.filter((item) => item.status === 'completed'
    || (['paused', 'interrupted'].includes(item.status) && item.partialAvailable));
  const shown = useMemo(() => panelOrder.filter((key) => visible[key]), [visible]);

  useEffect(() => {
    setEvidence(emptyEvidence());
    setGraphHighlight(null);
    setPanelSizes({});
    setActive(window.innerWidth <= 820 ? 'original' : 'rag');
    sourceCacheRef.current = { filename: '', data: null, promise: null };
  }, [file.name]);

  useEffect(() => () => resizeCleanupRef.current?.(), []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (window.innerWidth <= 820 || resizing) return;
      const count = panelOrder.filter((key) => visible[key]).length;
      if (count <= 1 || entry.contentRect.width >= count * PANEL_MIN_WIDTH + (count - 1) * 7) return;
      const candidate = [...panelOrder].reverse().find((key) => visible[key] && key !== active);
      if (candidate) {
        setPanelSizes({});
        setVisible((current) => ({ ...current, [candidate]: false }));
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [active, resizing, visible]);

  const toggle = (key) => setVisible((current) => {
    if (current[key] && Object.values(current).filter(Boolean).length === 1) {
      toast('至少保留一个内容面板');
      return current;
    }
    const next = { ...current, [key]: !current[key] };
    setPanelSizes({});
    if (!next[active]) setActive(panelOrder.find((item) => next[item]));
    return next;
  });

  const loadHighlightIndex = useCallback(async () => {
    const cacheKey = `${file.name}:${highlightIndexVersion}`;
    if (sourceCacheRef.current.filename === cacheKey && sourceCacheRef.current.data) {
      return sourceCacheRef.current.data;
    }
    if (sourceCacheRef.current.filename === cacheKey && sourceCacheRef.current.promise) {
      return sourceCacheRef.current.promise;
    }
    const promise = api.get(`/graph-sources/${encodePathSegment(file.name)}`)
      .then((response) => response.data);
    sourceCacheRef.current = { filename: cacheKey, data: null, promise };
    try {
      const data = await promise;
      sourceCacheRef.current = { filename: cacheKey, data, promise: null };
      return data;
    } catch (error) {
      sourceCacheRef.current = { filename: cacheKey, data: null, promise: null };
      throw error;
    }
  }, [file.name, highlightIndexVersion]);

  useEffect(() => {
    loadHighlightIndex().catch(() => {
      // Legacy or still-processing files fall back to loading on first locate.
    });
  }, [loadHighlightIndex]);

  const refreshHighlightIndex = useCallback(() => {
    sourceCacheRef.current = { filename: '', data: null, promise: null };
    setEvidence(emptyEvidence());
    setHighlightIndexVersion((value) => value + 1);
  }, []);

  useEffect(() => {
    const previous = previousFileStatusRef.current;
    if (previous.name !== file.name) {
      previousFileStatusRef.current = { name: file.name, status: file.status };
      return;
    }
    if (previous.status !== 'completed' && file.status === 'completed') {
      refreshHighlightIndex();
    }
    previousFileStatusRef.current = { name: file.name, status: file.status };
  }, [file.name, file.status, refreshHighlightIndex]);

  const handleEvidence = useCallback(async (message) => {
    const requestId = ++evidenceRequestRef.current;
    const references = Array.isArray(message.sourceBlocks) ? message.sourceBlocks : [];
    setLocatingCitation(true);
    onSettings?.({ showAllEvidence: false });
    setVisible((value) => ({ ...value, original: true }));
    setActive('original');

    if (!references.length) {
      setEvidence({ ...emptyEvidence(), kind: message.kind || 'node', requestId });
      setLocatingCitation(false);
      toast('该节点或关系暂无可定位的原文文本块');
      return;
    }

    try {
      setEvidence({ ...emptyEvidence(), kind: message.kind || 'node', requestId });
      const sourceData = await loadHighlightIndex();
      if (requestId !== evidenceRequestRef.current) return;

      const referenceById = new Map(references.map((reference) => [blockId(reference), reference]));
      const occurrenceCounts = new Map();
      const sourceBlocks = (sourceData?.blocks || []).map((block) => {
        const textKey = String(block.text || '').replace(/\s+/g, ' ').trim();
        const occurrence = occurrenceCounts.get(textKey) || 0;
        occurrenceCounts.set(textKey, occurrence + 1);
        return { ...block, occurrence };
      });
      const results = sourceBlocks
        .filter((block) => referenceById.has(String(block.bid)))
        .map((block) => {
          const reference = referenceById.get(String(block.bid));
          return {
            ...block,
            evidence: typeof reference === 'object' ? reference.evidence || '' : '',
            score: typeof reference === 'object' ? reference.score : null,
            preview: String(block.text || '').replace(/\s+/g, ' ').trim().slice(0, 180),
          };
        })
        .sort((left, right) => Number(left.index || 0) - Number(right.index || 0));

      setEvidence({
        kind: message.kind === 'edge' ? 'edge' : message.kind === 'source' ? 'source' : 'node',
        results,
        terms: inferIndexedHighlightTerms(message, sourceBlocks, references),
        requestId,
      });
      setLocatingCitation(false);
      if (!results.length) toast('已收到出处信息，但未在当前文档中找到对应文本块');
    } catch (error) {
      if (requestId !== evidenceRequestRef.current) return;
      setEvidence({
        kind: message.kind || 'node',
        results: references.map((item) => typeof item === 'object' ? item : { bid: String(item) }),
        terms: {
          selectedEntityTerms: message.entityTerms || [],
          selectedRelationTerms: message.relationTerms || [],
        },
        requestId,
      });
      setLocatingCitation(false);
      toast(getApiErrorMessage(error, '出处文本块加载失败'), 'error');
    }
  }, [loadHighlightIndex, onSettings, toast]);

  const clearEvidence = useCallback(() => {
    evidenceRequestRef.current += 1;
    setEvidence(emptyEvidence());
    setLocatingCitation(false);
    onSettings?.({ showAllEvidence: false });
  }, [onSettings]);

  const showAllDocumentHighlights = useCallback(async () => {
    const requestId = ++evidenceRequestRef.current;
    try {
      const sourceData = await loadHighlightIndex();
      if (requestId !== evidenceRequestRef.current) return;
      setEvidence({
        kind: 'document',
        results: [],
        terms: {},
        allBlocks: Array.isArray(sourceData?.blocks) ? sourceData.blocks : [],
        requestId,
        fullDocument: true,
      });
    } catch (error) {
      if (requestId !== evidenceRequestRef.current) return;
      toast(getApiErrorMessage(error, '全文高亮索引加载失败'), 'error');
    }
  }, [loadHighlightIndex, toast]);

  const toggleHighlights = useCallback(() => {
    if (evidence.results?.length) {
      const requestId = ++evidenceRequestRef.current;
      onSettings?.({ showAllEvidence: !settings.showAllEvidence });
      setEvidence((current) => ({ ...current, requestId }));
      return;
    }
    if (evidence.fullDocument) clearEvidence();
    else showAllDocumentHighlights();
  }, [clearEvidence, evidence.fullDocument, evidence.results, onSettings, settings.showAllEvidence, showAllDocumentHighlights]);

  const closeEvidenceLocator = useCallback(() => {
    clearEvidence();
  }, [clearEvidence]);

  const handleCitation = useCallback((citation) => {
    if (!citation) return;
    if (citation.type === 'graph' && citation.graphId) {
      setLocatingCitation(true);
      setVisible((value) => ({ ...value, graph: true }));
      setActive('graph');
      setGraphHighlight({
        kind: citation.graphKind || 'node',
        id: citation.graphId,
        citation,
        requestId: Date.now(),
      });
      window.setTimeout(() => setLocatingCitation(false), 450);
      return;
    }
    handleEvidence({
      kind: 'source',
      id: citation.id,
      sourceBlocks: citation.sourceBlocks || [],
      entityTerms: citation.entityTerms || [],
      relationTerms: citation.relationTerms || [],
    });
  }, [handleEvidence]);

  const handleGraphHighlightMissing = useCallback(() => {
    const citation = graphHighlight?.citation;
    if (!citation?.sourceBlocks?.length) {
      toast('当前图谱页未包含该引用目标', 'error');
      return;
    }
    toast('当前社区页未包含该目标，已定位到原文');
    handleEvidence({
      kind: citation.graphKind || 'node',
      id: citation.graphId,
      sourceBlocks: citation.sourceBlocks,
      entityTerms: citation.entityTerms || [],
      relationTerms: citation.relationTerms || [],
    });
  }, [graphHighlight, handleEvidence, toast]);

  const startResize = (event, leftKey) => {
    if (window.innerWidth <= 820) return;
    const rightKey = shown[shown.indexOf(leftKey) + 1];
    const container = containerRef.current;
    if (!rightKey || !container) return;

    const elements = Object.fromEntries(shown.map((key) => [
      key,
      container.querySelector(`[data-panel-key="${key}"]`),
    ]));
    if (!elements[leftKey] || !elements[rightKey]) return;

    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    resizeCleanupRef.current?.();
    const initialSizes = Object.fromEntries(shown.map((key) => [
      key,
      elements[key].getBoundingClientRect().width,
    ]));
    const startX = event.clientX;
    const pairWidth = initialSizes[leftKey] + initialSizes[rightKey];
    let animationFrame = null;
    let lastLeft = initialSizes[leftKey];
    let lastRight = initialSizes[rightKey];
    setPanelSizes(initialSizes);
    setResizing(true);
    document.body.classList.add('is-resizing');

    const move = (moveEvent) => {
      const delta = moveEvent.clientX - startX;
      const nextLeft = Math.max(
        PANEL_MIN_WIDTH,
        Math.min(pairWidth - PANEL_MIN_WIDTH, initialSizes[leftKey] + delta),
      );
      const nextRight = pairWidth - nextLeft;
      lastLeft = nextLeft;
      lastRight = nextRight;
      if (animationFrame) cancelAnimationFrame(animationFrame);
      animationFrame = requestAnimationFrame(() => {
        animationFrame = null;
        elements[leftKey].style.flex = `${nextLeft} 1 0px`;
        elements[rightKey].style.flex = `${nextRight} 1 0px`;
      });
    };
    const stop = () => {
      if (animationFrame) cancelAnimationFrame(animationFrame);
      setPanelSizes((current) => ({
        ...current,
        [leftKey]: lastLeft,
        [rightKey]: lastRight,
      }));
      setResizing(false);
      document.body.classList.remove('is-resizing');
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', stop, true);
      window.removeEventListener('pointercancel', stop, true);
      window.removeEventListener('blur', stop);
      resizeCleanupRef.current = null;
    };
    resizeCleanupRef.current = stop;
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', stop, true);
    window.addEventListener('pointercancel', stop, true);
    window.addEventListener('blur', stop);
  };

  return (
    <main className="result-view">
      <header className="result-topbar glass">
        <div className="result-file-nav">
          <button className="icon-button" onClick={onClose} aria-label="返回首页"><ChevronLeft size={18} /></button>
          <button className="icon-button" onClick={onLibraryToggle} aria-label="切换文件">
            {libraryOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
          </button>
          <div className="current-file">
            <span className="file-glyph"><FileText size={16} /></span>
            <select value={file.name} onChange={(event) => onSwitchFile(available.find((item) => item.name === event.target.value))}>
              {available.map((item) => <option key={item.name}>{item.name}</option>)}
            </select>
            <small>{file.documentModified ? '有待应用草稿' : '已同步'}</small>
          </div>
        </div>
        <nav className="result-tabs">
          {panelOrder.map((key) => {
            const Icon = panelInfo[key].icon;
            return (
              <button
                key={key}
                className={`${active === key ? 'active' : ''} ${!visible[key] ? 'hidden-panel' : ''}`}
                onClick={() => { setPanelSizes({}); setVisible((value) => ({ ...value, [key]: true })); setActive(key); }}
              >
                <Icon size={15} />{panelInfo[key].label}
                <span className="panel-visibility" onClick={(event) => { event.stopPropagation(); toggle(key); }}>
                  {visible[key] ? <Eye size={13} /> : <EyeOff size={13} />}
                </span>
              </button>
            );
          })}
        </nav>
        <button className="icon-button" onClick={onClose} aria-label="关闭结果视图"><X size={18} /></button>
      </header>

      <div ref={containerRef} className="result-panels">
        {shown.map((key, index) => (
          <div
            key={key}
            data-panel-key={key}
            className={`panel-slot panel-${key} ${active === key ? 'mobile-active' : ''}`}
            style={{ flex: `${panelSizes[key] || 1} 1 0px`, minWidth: 0 }}
          >
            {key === 'original' && (
              <OriginalDocumentPanel
                file={file}
                refreshToken={highlightIndexVersion}
                toast={toast}
                evidence={evidence}
                showAllEvidence={settings.showAllEvidence}
                onShowAllEvidence={(value) => onSettings?.({ showAllEvidence: value })}
                onHighlightAll={toggleHighlights}
                onClearEvidence={closeEvidenceLocator}
                locating={locatingCitation}
                resizing={resizing || layoutResizing}
                onDirtyChange={onDirtyChange}
                onDraftSaved={onDocumentSaved}
              />
            )}
            {key === 'graph' && (
              <GraphPanel
                file={file}
                layoutResizing={layoutResizing || resizing}
                renderer={settings.graphRenderer}
                sigmaViewMode={settings.sigmaViewMode}
                theme={settings.theme}
                toast={toast}
                onEvidence={handleEvidence}
                onGraphUpdated={refreshHighlightIndex}
                onHighlightMissing={handleGraphHighlightMissing}
                highlight={graphHighlight}
                locating={locatingCitation}
              />
            )}
            {key === 'rag' && (
              <RagPanel
                file={file}
                streamOutput={settings.streamOutput}
                historyContext={settings.historyContext}
                resizing={resizing || layoutResizing}
                onCitation={handleCitation}
                toast={toast}
              />
            )}
            {index < shown.length - 1 && (
              <div className="panel-resizer" onPointerDown={(event) => startResize(event, key)} />
            )}
          </div>
        ))}
      </div>
      {resizing && <div className="resize-shield" aria-hidden="true" />}
    </main>
  );
}
