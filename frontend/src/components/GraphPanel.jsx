import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react';
import { Maximize2, Network, RefreshCw, SlidersHorizontal } from 'lucide-react';
import { apiUrl } from '../api/client.js';
import { graphNameOf } from '../lib/file.js';

export default function GraphPanel({ file, renderer = 'pyvis', sigmaViewMode = 'full', layoutResizing = false, theme, onEvidence, onGraphUpdated, onHighlightMissing, highlight, toast, locating }) {
  const graphViewRef = useRef(null);
  const graphFrameWrapRef = useRef(null);
  const [immersive, setImmersive] = useState(false);
  const graphName = graphNameOf(file.name);
  const useSigma = renderer === 'sigma';

  useLayoutEffect(() => {
    const frame = graphFrameWrapRef.current?.querySelector('iframe');
    if (!frame) return;
    if (layoutResizing) {
      const bounds = frame.getBoundingClientRect();
      frame.style.width = `${bounds.width}px`;
      frame.style.height = `${bounds.height}px`;
      frame.style.maxWidth = 'none';
      return;
    }
    frame.style.removeProperty('width');
    frame.style.removeProperty('height');
    frame.style.removeProperty('max-width');
  }, [layoutResizing]);

  const toggleImmersive = () => setImmersive((value) => {
    if (value) {
      window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
        graphViewRef.current?.exitImmersive?.();
      }));
    }
    return !value;
  });

  return (
    <section className={`panel graph-panel ${immersive ? 'immersive' : ''}`}>
      <header className="panel-header">
        <div>
          <h3><Network size={17} /> 知识图谱</h3>
          <span className="panel-subtitle">{useSigma ? `Sigma.js ${sigmaViewMode === 'communities' ? '社区总览' : '神经网络全量图'}` : 'PyVis 可编辑交互视图'}</span>
        </div>
        <div className="panel-actions">
          <button className={`icon-button ${immersive ? 'active' : ''}`} onClick={toggleImmersive} aria-label="沉浸模式" title="沉浸模式"><Maximize2 size={16} /></button>
          <button className="icon-button" onClick={() => graphViewRef.current?.reload?.()} aria-label="重新加载" title="重新加载"><RefreshCw size={16} /></button>
        </div>
      </header>
      <div className="graph-toolbar">
        <span><SlidersHorizontal size={14} /> {useSigma ? '支持缩放、拖动、社区导航与引用定位' : '图谱交互功能由后端图谱页面提供'}</span>
        <span className="graph-hint">{useSigma ? '全量图·社区总览·社区详情' : '可搜索·聚焦·右键编辑'}</span>
      </div>
      <div ref={graphFrameWrapRef} className={`graph-frame-wrap ${layoutResizing ? 'is-layout-resizing' : ''}`}>
        {useSigma ? (
          <PersistedGraphView
            ref={graphViewRef}
            file={file}
            graphName={graphName}
            pageName={sigmaViewMode === 'communities' ? `${graphName}.sigma-communities.html` : `${graphName}.sigma.html`}
            onEvidence={onEvidence}
            onGraphUpdated={onGraphUpdated}
            onHighlightMissing={onHighlightMissing}
            highlight={highlight}
            toast={toast}
            locating={locating}
            loadingLabel="正在加载 Sigma.js 静态图谱"
          />
        ) : (
          <PersistedGraphView
            ref={graphViewRef}
            file={file}
            graphName={graphName}
            pageName={`${graphName}.html`}
            onEvidence={onEvidence}
            onGraphUpdated={onGraphUpdated}
            onHighlightMissing={onHighlightMissing}
            highlight={highlight}
            toast={toast}
            locating={locating}
            loadingLabel="正在加载 PyVis 图谱页面"
          />
        )}
        {layoutResizing && (
          <div className="graph-resize-overlay" role="status" aria-live="polite">
            <RefreshCw size={24} />
            <strong>正在调整图谱区域</strong>
            <span>松开后重新绘制</span>
          </div>
        )}
      </div>
    </section>
  );
}

const PersistedGraphView = forwardRef(function PersistedGraphView({ file, graphName, pageName, onEvidence, onGraphUpdated, onHighlightMissing, highlight, toast, locating, loadingLabel }, ref) {
  const frameRef = useRef(null);
  const handlersRef = useRef({ onEvidence, onGraphUpdated, onHighlightMissing, toast });
  const [ready, setReady] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useImperativeHandle(ref, () => ({
    reload: () => { setReady(false); setReloadToken((value) => value + 1); },
    exitImmersive: () => frameRef.current?.contentWindow?.postMessage({ type: 'knowledge-graph-exit-immersive', graphName }, '*'),
  }), [graphName]);

  useEffect(() => {
    handlersRef.current = { onEvidence, onGraphUpdated, onHighlightMissing, toast };
  }, [onEvidence, onGraphUpdated, onHighlightMissing, toast]);

  useEffect(() => {
    setReady(false);
    const listener = (event) => {
      if (event.source !== frameRef.current?.contentWindow) return;
      if (event.data?.type === 'knowledge-graph-ready') setReady(true);
      if (event.data?.type === 'knowledge-graph-highlighted') setReady(true);
      if (event.data?.type === 'knowledge-graph-evidence') handlersRef.current.onEvidence?.(event.data);
      if (event.data?.type === 'knowledge-graph-highlight-missing') {
        setReady(true);
        handlersRef.current.onHighlightMissing?.();
      }
      if (['knowledge-graph-updated', 'knowledge-graph-restored'].includes(event.data?.type)) {
        handlersRef.current.onGraphUpdated?.();
        handlersRef.current.toast?.('图谱已更新', 'success');
      }
    };
    window.addEventListener('message', listener);
    const timer = window.setTimeout(() => setReady(true), 10000);
    return () => { window.removeEventListener('message', listener); window.clearTimeout(timer); };
  }, [file.name, file.graphRedrawnAt, pageName, reloadToken]);

  useEffect(() => {
    if (!ready || !highlight?.id) return;
    frameRef.current?.contentWindow?.postMessage({
      type: 'knowledge-graph-highlight',
      graphName,
      kind: highlight.kind,
      id: highlight.id,
      locateSource: false,
      source: highlight.citation?.entityTerms?.[0] || '',
      target: highlight.citation?.entityTerms?.[1] || '',
      relation: highlight.citation?.relationTerms?.[0] || '',
    }, '*');
  }, [graphName, highlight, ready]);

  const frameUrl = apiUrl(`/result-page/${encodeURIComponent(graphName)}/${encodeURIComponent(pageName)}?graph-editor=1&reload=${reloadToken}&redrawn=${file.graphRedrawnAt || 0}`);
  return <>
    <iframe ref={frameRef} title={`${file.name} 知识图谱`} src={frameUrl} sandbox="allow-scripts allow-modals" />
    {locating && <div className="locating-skeleton graph-locating-skeleton" aria-label="正在定位图谱引用"><span /><span /><span /></div>}
    <div className={`graph-loading ${ready ? 'hidden' : ''}`}>
      <Network size={28} />
      <strong>{loadingLabel}</strong>
      <span>读取已保存的布局与图谱数据</span>
    </div>
  </>;
});
