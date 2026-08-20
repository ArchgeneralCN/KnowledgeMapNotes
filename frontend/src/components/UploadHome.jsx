import { useRef, useState } from 'react';
import { ArrowRight, FileText, FolderOpen, Plus, Sparkles, UploadCloud } from 'lucide-react';
import { canViewFile, fileExtension } from '../lib/file.js';

export default function UploadHome({ files, uploading, onUpload, onLibrary, onOpen }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const completed = files.filter(canViewFile);
  const recent = completed.slice(0, 6);

  const acceptDrop = (event) => {
    event.preventDefault();
    setDragging(false);
    onUpload(event.dataTransfer.files);
  };

  return (
    <main className="home-view">
      <header className="topbar">
        <div className="wordmark"><span className="wordmark-dot" />Mapnote</div>
        <div className="topbar-status"><span className="live-dot" /> 本地知识工作台</div>
      </header>

      <section className="home-hero">
        <div className="hero-copy">
          <span className="eyebrow"><Sparkles size={14} /> 从资料到关联知识</span>
          <h1>让每份文档，<br />长成一张知识地图。</h1>
          <p>导入原始资料，同时阅读原文、探索概念关系，并用 HybridRAG 追问其中的细节。</p>
          <div className="hero-actions">
            <button className="button primary large" onClick={() => inputRef.current?.click()} disabled={uploading}>
              <Plus size={18} /> {uploading ? '正在导入' : '导入新文件'}
            </button>
            <button className="button secondary large" onClick={onLibrary}><FolderOpen size={18} /> 浏览文件库</button>
          </div>
        </div>

        <div className="orbit-stage" aria-label={`${completed.length} 个可查看文件`}>
          <div className="orbit-ring orbit-ring-outer" />
          <div className="orbit-ring orbit-ring-inner" />
          <div className="orbit-core glass">
            <span>{completed.length}</span>
            <small>已建图谱</small>
          </div>
          {recent.map((file, index) => (
            <button
              key={file.name}
              className={`orbit-file orbit-file-${index + 1} glass`}
              onClick={() => onOpen(file)}
              title={file.name}
            >
              <FileText size={17} />
              <span>{file.name}</span>
              <small>{fileExtension(file.name)}</small>
            </button>
          ))}
          {!recent.length && <div className="orbit-empty"><FileText size={20} /><span>导入第一份资料</span></div>}
        </div>
      </section>

      <section
        className={`drop-zone glass ${dragging ? 'dragging' : ''}`}
        onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => event.currentTarget === event.target && setDragging(false)}
        onDrop={acceptDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input ref={inputRef} hidden multiple type="file" accept=".txt,.md,.pdf,.zip" onChange={(event) => { onUpload(event.target.files); event.target.value = ''; }} />
        <div className="drop-icon"><UploadCloud size={22} /></div>
        <div><strong>将文件拖到这里</strong><span>支持 TXT、Markdown、PDF 和 .kmn.zip 迁移包</span></div>
        <ArrowRight size={18} />
      </section>
    </main>
  );
}
