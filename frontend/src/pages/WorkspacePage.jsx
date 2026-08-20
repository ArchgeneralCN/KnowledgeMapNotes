import { useCallback, useEffect, useMemo, useState } from 'react';
import AppSidebar from '../components/AppSidebar.jsx';
import FileLibraryDrawer from '../components/FileLibraryDrawer.jsx';
import ResultWorkspace from '../components/ResultWorkspace.jsx';
import SettingsDialog from '../components/SettingsDialog.jsx';
import UploadHome from '../components/UploadHome.jsx';
import ConfirmDialog from '../components/ui/ConfirmDialog.jsx';
import { useToast } from '../components/ui/Toast.jsx';
import useFileLibrary from '../hooks/useFileLibrary.js';
import { canViewFile } from '../lib/file.js';

const readBoolean = (key, fallback) => { const value = localStorage.getItem(key); return value === null ? fallback : value === 'true'; };
const readInteger = (key, fallback) => { const value = Number(localStorage.getItem(key)); return Number.isInteger(value) && value > 0 ? value : fallback; };
const readPrompts = () => { try { return JSON.parse(localStorage.getItem('custom-processing-prompts')) || {}; } catch { return {}; } };
const readChunkSettings = () => {
  const chunkMaxTokens = Math.max(128, Math.min(32768, readInteger('kg-chunk-max-tokens', 1024)));
  return {
    chunkMaxTokens,
    chunkMinTokens: Math.max(1, Math.min(chunkMaxTokens - 1, readInteger('kg-chunk-min-tokens', 384))),
  };
};
const ACTIVE_FILE_KEY = 'workspace-active-file';
const readActiveFile = () => { try { return sessionStorage.getItem(ACTIVE_FILE_KEY) || ''; } catch { return ''; } };
const rememberActiveFile = (filename) => {
  try {
    if (filename) sessionStorage.setItem(ACTIVE_FILE_KEY, filename);
    else sessionStorage.removeItem(ACTIVE_FILE_KEY);
  } catch {
    // Storage can be disabled without preventing the workspace from working.
  }
};

export default function WorkspacePage() {
  const toast = useToast();
  const [view, setView] = useState('home');
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [currentFile, setCurrentFile] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [drawerResizing, setDrawerResizing] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [restoreFilename] = useState(readActiveFile);
  const [drawerWidth, setDrawerWidth] = useState(() => Math.max(260, Math.min(560, Number(localStorage.getItem('file-list-width')) || 340)));
  const [settings, setSettings] = useState(() => ({
    noteType: localStorage.getItem('note-type') || 'general', useImg2txt: readBoolean('use-img2txt', false),
    ...readChunkSettings(),
    graphRenderer: localStorage.getItem('graph-renderer') === 'sigma' ? 'sigma' : 'pyvis',
    sigmaViewMode: localStorage.getItem('sigma-view-mode') === 'communities' ? 'communities' : 'full',
    communityMinSizeMode: localStorage.getItem('community-min-size-mode') === 'auto' ? 'auto' : 'custom',
    communityMinSize: Math.max(1, readInteger('community-min-size', 20)),
    communityAutoPercent: Math.max(1, Math.min(100, readInteger('community-auto-percent', 5))),
    streamOutput: readBoolean('rag-stream-output', true), historyContext: readBoolean('rag-history-context', true),
    showAllEvidence: readBoolean('show-all-evidence-highlights', false), theme: localStorage.getItem('app-theme') || 'default',
    customPrompts: { entityExtraction: '', relationshipExtraction: '', knowledgeFusion: '', ...readPrompts() },
  }));
  const updateSettings = useCallback((patch) => setSettings((current) => ({ ...current, ...patch })), []);
  useEffect(() => {
    document.documentElement.dataset.theme = settings.theme;
    localStorage.setItem('app-theme', settings.theme); localStorage.setItem('note-type', settings.noteType);
    localStorage.setItem('graph-renderer', settings.graphRenderer);
    localStorage.setItem('sigma-view-mode', settings.sigmaViewMode);
    localStorage.setItem('community-min-size-mode', settings.communityMinSizeMode);
    localStorage.setItem('community-min-size', String(settings.communityMinSize));
    localStorage.setItem('community-auto-percent', String(settings.communityAutoPercent));
    localStorage.setItem('use-img2txt', String(settings.useImg2txt)); localStorage.setItem('rag-stream-output', String(settings.streamOutput));
    localStorage.setItem('kg-chunk-max-tokens', String(settings.chunkMaxTokens)); localStorage.setItem('kg-chunk-min-tokens', String(settings.chunkMinTokens));
    localStorage.setItem('rag-history-context', String(settings.historyContext)); localStorage.setItem('show-all-evidence-highlights', String(settings.showAllEvidence));
    localStorage.setItem('custom-processing-prompts', JSON.stringify(settings.customPrompts));
  }, [settings]);
  const library = useFileLibrary({
    noteType: settings.noteType,
    useImg2txt: settings.useImg2txt,
    chunkMaxTokens: settings.chunkMaxTokens,
    chunkMinTokens: settings.chunkMinTokens,
    communityMinSizeMode: settings.communityMinSizeMode,
    communityMinSize: settings.communityMinSize,
    communityAutoPercent: settings.communityAutoPercent,
    customPrompts: settings.customPrompts,
    toast,
  });
  const completed = useMemo(() => library.files.filter(canViewFile), [library.files]);
  useEffect(() => {
    if (library.loading || currentFile || !restoreFilename) return;
    const restored = library.files.find((file) => file.name === restoreFilename);
    if (restored && canViewFile(restored)) {
      setCurrentFile(restored);
      setView('result');
    }
  }, [currentFile, library.files, library.loading, restoreFilename]);
  useEffect(() => {
    if (!currentFile) return;
    const latest = library.files.find((file) => file.name === currentFile.name);
    if (latest && latest !== currentFile) setCurrentFile(latest);
  }, [currentFile, library.files]);

  const openFile = useCallback((file) => {
    if (!file || !canViewFile(file)) return;
    const proceed = () => { rememberActiveFile(file.name); setCurrentFile(file); setView('result'); setDirty(false); if (window.innerWidth <= 820) setLibraryOpen(false); };
    if (dirty && currentFile?.name !== file.name) setConfirm({ title: '未保存的文档修改', message: '切换文件将放弃当前编辑器中未保存的内容。已保存的草稿不受影响。', confirmLabel: '放弃并切换', danger: true, onConfirm: proceed }); else proceed();
  }, [currentFile?.name, dirty]);
  const closeResult = () => { const proceed = () => { rememberActiveFile(''); setView('home'); setCurrentFile(null); setDirty(false); }; if (dirty) setConfirm({ title: '关闭结果视图？', message: '编辑器中还有未保存的修改。', confirmLabel: '放弃修改', danger: true, onConfirm: proceed }); else proceed(); };
  useEffect(() => {
    if (!library.uploading && !dirty) return undefined;
    const protectPendingWork = (event) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', protectPendingWork);
    return () => window.removeEventListener('beforeunload', protectPendingWork);
  }, [dirty, library.uploading]);
  const actionMap = { pause: library.pause, resume: library.resume, remove: (file) => setConfirm({ title: '删除文件？', message: `“${file.name}”的原文、图谱、草稿与历史数据都将删除。`, confirmLabel: '确认删除', danger: true, onConfirm: () => { library.remove(file); if (currentFile?.name === file.name) closeResult(); } }), clearHistory: library.clearHistory, redraw: (file) => library.redraw(file, settings.graphRenderer), applyDocument: library.applyDocument, open: openFile };
  return <div
    className={`app-shell ${libraryOpen ? 'library-visible' : ''}`}
    style={{
      '--drawer-width': `${drawerWidth}px`,
      '--library-offset': libraryOpen ? `${drawerWidth}px` : '0px',
    }}
  >
    <AppSidebar active={libraryOpen ? 'library' : 'home'} onHome={() => { setLibraryOpen(false); if (view === 'result') closeResult(); }} onLibrary={() => setLibraryOpen((value) => !value)} onSettings={() => setSettingsOpen(true)} />
    <FileLibraryDrawer open={libraryOpen} files={library.files} loading={library.loading} width={drawerWidth} onWidth={setDrawerWidth} onResizeState={setDrawerResizing} onClose={() => setLibraryOpen(false)} onOpen={openFile} actions={actionMap} toast={toast} />
    <div className="app-content">
      {view === 'home' || !currentFile ? <UploadHome files={completed} uploading={library.uploading} onUpload={(files) => { setLibraryOpen(true); library.upload(files); }} onLibrary={() => setLibraryOpen(true)} onOpen={openFile} /> : <ResultWorkspace file={currentFile} files={library.files} libraryOpen={libraryOpen} layoutResizing={drawerResizing} onLibraryToggle={() => setLibraryOpen((value) => !value)} onClose={closeResult} onSwitchFile={openFile} settings={settings} onSettings={updateSettings} toast={toast} onDirtyChange={setDirty} onDocumentSaved={() => library.patchFile(currentFile.name, { documentModified: true })} />}
    </div>
    <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} settings={settings} onSettings={updateSettings} toast={toast} />
    <ConfirmDialog state={confirm} onCancel={() => setConfirm(null)} />
  </div>;
}
