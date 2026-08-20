import { useMemo, useRef, useState } from 'react';
import {
  ChevronDown, ChevronLeft, ChevronRight, CirclePause, Download, FilePenLine, FileText,
  Filter, LoaderCircle, MoreHorizontal, Play, RefreshCw, Search, Sparkles, Trash2, X,
} from 'lucide-react';
import api, { apiUrl, encodePathSegment, getApiErrorMessage } from '../api/client.js';
import { canViewFile, fileExtension, formatRemainingTime, PROCESSING_STATUSES, statusMeta } from '../lib/file.js';

const PAGE_SIZE = 10;
const PRIMARY_ENTITY_COUNT = 6;
const GRAPH_PROCESSING_STATUSES = ['processing', 'updating', 'resuming', 'pausing'];
const PROCESSING_STAGES = [
  ['entity_extraction', '实体提取'],
  ['relationship_extraction', '关系抽取'],
  ['knowledge_fusion', '知识融合'],
];
const statusOptions = [
  ['', '全部状态'], ['uploading', '上传中'], ['processing', '处理中'], ['updating', '增量更新中'],
  ['resuming', '继续处理中'], ['pausing', '暂停中'], ['paused', '已暂停'], ['completed', '已完成'],
  ['interrupted', '部分完成'], ['error', '失败'],
];

const entityName = (entity) => {
  if (Array.isArray(entity)) return String(entity[0] || '');
  if (entity && typeof entity === 'object') return String(entity.name || entity.id || '');
  return String(entity || '');
};

const formatEditedAt = (value) => {
  if (!value) return '时间未记录';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
    });
};

const formatRate = (value, unit) => {
  const rate = Number(value);
  if (!Number.isFinite(rate) || rate <= 0) return '';
  const formatted = rate < 10 ? rate.toFixed(1) : Math.round(rate);
  return unit === '%' ? `${formatted}%/分` : `${formatted} ${unit}/分`;
};

export default function FileLibraryDrawer({ open, files, loading, width, onWidth, onResizeState, onClose, onOpen, actions, toast }) {
  const [search, setSearch] = useState('');
  const [type, setType] = useState('');
  const [status, setStatus] = useState('');
  const [tempFilters, setTempFilters] = useState({ type: '', status: '' });
  const [filterOpen, setFilterOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState('');
  const [entities, setEntities] = useState({});
  const [menu, setMenu] = useState(null);
  const startResize = useRef(null);
  const drawerRef = useRef(null);

  const filtered = useMemo(() => files.filter((file) => {
    const queryMatch = file.name.toLowerCase().includes(search.trim().toLowerCase());
    const typeMatch = !type || fileExtension(file.name) === type;
    const statusMatch = !status || file.status === status;
    return queryMatch && typeMatch && statusMatch;
  }), [files, search, status, type]);
  const maxPage = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visible = filtered.slice((Math.min(page, maxPage) - 1) * PAGE_SIZE, Math.min(page, maxPage) * PAGE_SIZE);

  const toggleFile = async (file) => {
    if (!canViewFile(file)) return;
    if (expanded === file.name) { setExpanded(''); return; }
    setExpanded(file.name);
    if (entities[file.name]) return;
    setEntities((current) => ({ ...current, [file.name]: { loading: true, items: [] } }));
    try {
      const { data } = await api.get(`/file-entities/${encodePathSegment(file.name)}`, {
        params: { count: PRIMARY_ENTITY_COUNT },
      });
      setEntities((current) => ({ ...current, [file.name]: { loading: false, items: data.entities || [] } }));
    } catch (error) {
      setEntities((current) => ({ ...current, [file.name]: { loading: false, items: [] } }));
      toast(getApiErrorMessage(error, '主要实体加载失败'), 'error');
    }
  };

  const run = (action, file) => {
    setMenu(null);
    if (action === 'export') {
      const link = document.createElement('a');
      link.href = apiUrl(`/export-package/${encodePathSegment(file.name)}`);
      link.click();
      return;
    }
    actions[action]?.(file);
  };

  const beginResize = (event) => {
    if (window.innerWidth <= 820) return;
    event.preventDefault();
    onResizeState?.(true);
    startResize.current = { x: event.clientX, width };
    const shell = drawerRef.current?.parentElement;
    let frame = 0;
    let latestWidth = width;
    const applyWidth = (nextWidth) => {
      shell?.style.setProperty('--drawer-width', `${nextWidth}px`);
      if (open) shell?.style.setProperty('--library-offset', `${nextWidth}px`);
    };
    const move = (moveEvent) => {
      latestWidth = Math.max(
        260,
        Math.min(560, startResize.current.width + moveEvent.clientX - startResize.current.x),
      );
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        applyWidth(latestWidth);
      });
    };
    const stop = () => {
      if (!startResize.current) return;
      if (frame) window.cancelAnimationFrame(frame);
      applyWidth(latestWidth);
      onWidth(latestWidth);
      onResizeState?.(false);
      localStorage.setItem('file-list-width', String(Math.round(latestWidth)));
      document.body.classList.remove('is-resizing');
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', stop, true);
      window.removeEventListener('pointercancel', stop, true);
      window.removeEventListener('blur', stop);
      startResize.current = null;
    };
    document.body.classList.add('is-resizing');
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', stop, true);
    window.addEventListener('pointercancel', stop, true);
    window.addEventListener('blur', stop);
  };

  return (
    <aside ref={drawerRef} className={`file-drawer glass ${open ? 'open' : ''}`}>
      <header className="drawer-header">
        <div><span className="eyebrow">知识资产</span><h2>文件库</h2></div>
        <button className="icon-button" onClick={onClose} aria-label="关闭文件库"><X size={18} /></button>
      </header>
      <div className="library-tools">
        <label className="search-field"><Search size={16} /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="搜索文件名" /></label>
        <button className={`icon-button ${type || status ? 'active' : ''}`} onClick={() => { setTempFilters({ type, status }); setFilterOpen(!filterOpen); }} aria-label="筛选"><Filter size={17} /></button>
        {filterOpen && (
          <div className="filter-popover glass">
            <label>文件类型<select value={tempFilters.type} onChange={(event) => setTempFilters((value) => ({ ...value, type: event.target.value }))}><option value="">全部类型</option><option value="TXT">TXT</option><option value="MD">Markdown</option><option value="PDF">PDF</option><option value="KMN">KMN 迁移包</option></select></label>
            <label>处理状态<select value={tempFilters.status} onChange={(event) => setTempFilters((value) => ({ ...value, status: event.target.value }))}>{statusOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <div className="filter-actions"><button className="button text" onClick={() => setTempFilters({ type: '', status: '' })}>重置</button><button className="button primary small" onClick={() => { setType(tempFilters.type); setStatus(tempFilters.status); setPage(1); setFilterOpen(false); }}>应用</button></div>
          </div>
        )}
      </div>

      <div className="file-list">
        {loading && <div className="empty-state"><LoaderCircle className="spin" /><span>正在同步文件库</span></div>}
        {!loading && !visible.length && <div className="empty-state"><FileText /><strong>没有匹配的文件</strong><span>调整搜索或筛选条件</span></div>}
        {visible.map((file) => {
          const progress = Math.max(0, Math.min(100, file.percentage));
          const overallProgress = Math.max(0, Math.min(100, file.overallPercentage));
          const meta = statusMeta[file.status] || { tone: 'info' };
          const showStageProgress = GRAPH_PROCESSING_STATUSES.includes(file.status)
            && Object.values(file.stageProgress || {}).some((stage) => stage.totalKnown);
          return (
            <article key={file.name} className={`file-item ${expanded === file.name ? 'expanded' : ''}`} onClick={() => toggleFile(file)} onDoubleClick={() => canViewFile(file) && onOpen(file)} onContextMenu={(event) => { event.preventDefault(); setMenu({ file, x: event.clientX, y: event.clientY }); }}>
              <div className="file-row">
                <div className={`file-type-icon tone-${meta.tone}`}><FileText size={19} /><small>{fileExtension(file.name)}</small></div>
                <div className="file-main"><strong title={file.name}>{file.name}</strong><div className="file-meta"><span className={`status-dot tone-${meta.tone}`} />{file.displayStatus}{file.documentModified && <span className="draft-tag"><FilePenLine size={11} /> 有草稿</span>}</div></div>
                <button className="icon-button quiet" onClick={(event) => { event.stopPropagation(); const rect = event.currentTarget.getBoundingClientRect(); setMenu({ file, x: rect.right - 190, y: rect.bottom + 4 }); }} aria-label="文件操作"><MoreHorizontal size={18} /></button>
              </div>
              {showStageProgress ? (
                <div className="stage-progress-list">
                  <div className="overall-progress">
                    <strong>总进度 {overallProgress.toFixed(1)}%</strong>
                    <span>{formatRate(file.overallSpeedPercentPerMinute, '%')}</span>
                    <span>{file.estimatedTotalRemainingSeconds == null ? '总剩余估算中' : `总剩余 ${formatRemainingTime(file.estimatedTotalRemainingSeconds)}`}</span>
                  </div>
                  {PROCESSING_STAGES.map(([key, label]) => (
                    <StageProgress
                      key={key}
                      label={label}
                      stage={file.stageProgress[key]}
                      active={file.processingStage === key}
                    />
                  ))}
                  {file.errorMessage && <div className="progress-error">{file.errorMessage}</div>}
                </div>
              ) : (
                <>
                  {PROCESSING_STATUSES.includes(file.status) && <div className="progress-wrap"><div className="progress-track"><span style={{ width: `${progress}%` }} /></div><span>{progress}%</span></div>}
                  {PROCESSING_STATUSES.includes(file.status) && (file.totalChunks > 0 || file.errorMessage) && <div className="progress-detail"><span>{file.completedChunks}/{file.totalChunks || '?'} 文本块</span>{file.latestChunkSeconds && <span>最近 {Number(file.latestChunkSeconds).toFixed(1)}s</span>}{file.estimatedRemainingSeconds != null && <span>{formatRemainingTime(file.estimatedRemainingSeconds)}</span>}{file.errorMessage && <span className="error-copy">{file.errorMessage}</span>}</div>}
                </>
              )}
              {canViewFile(file) && <div className="file-content-meta"><span>{file.characterCount.toLocaleString()} 字</span><span>编辑于 {formatEditedAt(file.lastEditedAt)}</span></div>}
              {expanded === file.name && <div className="entity-list"><span className="entity-caption"><Sparkles size={13} /> 主要实体</span>{entities[file.name]?.loading ? <LoaderCircle className="spin" size={15} /> : entities[file.name]?.items?.length ? entities[file.name].items.map((entity, index) => <span key={`${entityName(entity)}-${index}`}>{entityName(entity)}</span>) : <small>暂无实体</small>}</div>}
            </article>
          );
        })}
      </div>

      <footer className="drawer-footer"><span>{filtered.length} 份文件</span><div className="pager"><button className="icon-button quiet" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><ChevronLeft size={16} /></button><span>{Math.min(page, maxPage)} / {maxPage}</span><button className="icon-button quiet" disabled={page >= maxPage} onClick={() => setPage((value) => value + 1)}><ChevronRight size={16} /></button></div></footer>
      <div className="drawer-resizer" onPointerDown={beginResize} />

      {menu && <ContextMenu menu={menu} onClose={() => setMenu(null)} onRun={run} />}
    </aside>
  );
}

function StageProgress({ label, stage, active }) {
  const percentage = Math.max(0, Math.min(100, Number(stage?.percentage || 0)));
  const unit = stage?.unit || '项';
  const average = Number(stage?.averageItemSeconds);
  const speed = formatRate(stage?.itemsPerMinute, unit);
  return (
    <div className={`stage-progress ${active ? 'active' : ''}`}>
      <div className="stage-progress-head">
        <strong>{label}</strong>
        <span>{stage?.totalKnown ? `${stage.completed}/${stage.total} ${unit}` : '等待统计'}</span>
      </div>
      <div className="stage-progress-bar"><span style={{ width: `${percentage}%` }} /></div>
      <div className="stage-progress-meta">
        {Number.isFinite(average) && average > 0 && <span>均 {average.toFixed(1)}s/{unit}</span>}
        {speed && <span>{speed}</span>}
        {stage?.totalKnown && <span>剩余 {stage.remaining ?? 0} {unit}</span>}
        {stage?.estimatedRemainingSeconds != null && Number(stage.estimatedRemainingSeconds) > 0 && <span>{formatRemainingTime(stage.estimatedRemainingSeconds)}</span>}
      </div>
    </div>
  );
}

function ContextMenu({ menu, onClose, onRun }) {
  const { file } = menu;
  const working = ['uploading', 'processing', 'updating', 'resuming'].includes(file.status);
  const resumable = ['paused', 'interrupted', 'error'].includes(file.status) && file.resumable;
  const terminal = ['completed', 'paused', 'interrupted', 'error'].includes(file.status);
  const item = (action, label, Icon, danger = false) => <button className={`context-item ${danger ? 'danger' : ''}`} onClick={() => onRun(action, file)}><Icon size={15} />{label}</button>;
  return (
    <><div className="context-dismiss" onClick={onClose} /><div className="context-menu glass" style={{ left: Math.min(menu.x, window.innerWidth - 210), top: Math.min(menu.y, window.innerHeight - 370) }}>
      <strong title={file.name}>{file.name}</strong>
      {working && item('pause', '暂停处理', CirclePause)}
      {resumable && item('resume', '继续处理', Play)}
      {canViewFile(file) && item('open', '查看原文与图谱', FileText)}
      {file.status === 'completed' && item('redraw', '重新绘制图谱', RefreshCw)}
      {file.status === 'completed' && file.documentModified && item('applyDocument', '应用文档修改', FilePenLine)}
      {file.status === 'completed' && item('export', '下载迁移包', Download)}
      {file.status === 'completed' && item('clearHistory', '清除 RAG 历史', X)}
      {terminal && <div className="context-divider" />}
      {terminal && item('remove', '删除文件', Trash2, true)}
      {file.status === 'pausing' && <small>正在完成并保存当前文本块…</small>}
    </div></>
  );
}
