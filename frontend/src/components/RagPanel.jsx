import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ArrowDown, Bot, FileText, LoaderCircle, Network, Send, Square, UserRound } from 'lucide-react';
import DOMPurify from 'dompurify';
import MarkdownIt from 'markdown-it';
import api, { apiUrl, getApiErrorMessage } from '../api/client.js';

const markdown = new MarkdownIt({ breaks: true, html: false, linkify: true });
const cleanMessages = (messages) => messages.filter((message) => !message.thinking && !message.streaming);

const messageTimestamp = () => new Date().toISOString();

export default function RagPanel({ file, streamOutput, historyContext, onCitation, toast, resizing = false }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streamStatus, setStreamStatus] = useState('');
  const [showBottom, setShowBottom] = useState(false);
  const abortRef = useRef(null);
  const listRef = useRef(null);
  const fileRef = useRef(file.name);

  useEffect(() => {
    abortRef.current?.abort(); fileRef.current = file.name; setLoading(false);
    try { setMessages(JSON.parse(localStorage.getItem(`chat_${file.name}`) || '[]')); } catch { setMessages([]); }
    return () => abortRef.current?.abort();
  }, [file.name]);
  useEffect(() => { if (!showBottom) listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' }); }, [messages, showBottom]);
  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    if (resizing) {
      const bounds = list.getBoundingClientRect();
      list.style.width = `${bounds.width}px`;
      list.style.height = `${bounds.height}px`;
      list.style.maxWidth = 'none';
      return;
    }
    list.style.removeProperty('width');
    list.style.removeProperty('height');
    list.style.removeProperty('max-width');
  }, [resizing]);
  const persist = (next) => localStorage.setItem(`chat_${fileRef.current}`, JSON.stringify(cleanMessages(next)));
  const stop = () => { abortRef.current?.abort(); abortRef.current = null; setLoading(false); setMessages((current) => { const next = cleanMessages(current); persist(next); return next; }); setStreamStatus(''); toast('已停止生成'); };

  const send = async () => {
    const question = input.trim(); if (!question || loading) return;
    const userMessage = { role: 'user', content: question, createdAt: messageTimestamp() };
    const history = cleanMessages([...messages, userMessage]).map((message) => ({ role: message.role, content: typeof message.content === 'object' ? message.content.answer : message.content }));
    setInput(''); setLoading(true); setShowBottom(false);
    const controller = new AbortController(); abortRef.current = controller;
    if (streamOutput) {
      const assistant = { role: 'assistant', content: { answer: '', material: '', citations: [] }, streaming: true, createdAt: messageTimestamp() };
      setMessages((current) => [...current, userMessage, assistant]);
      try {
        const response = await fetch(apiUrl('/hybridrag/stream'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request: question, flow: true, filename: file.name, messages: historyContext ? history : null }), signal: controller.signal });
        if (!response.ok) throw new Error(await response.text() || `HTTP ${response.status}`);
        await readSse(response, (event) => {
          if (event.type === 'status') setStreamStatus(event.content || '');
          if (event.type === 'content') setMessages((current) => current.map((message, index) => index === current.length - 1 ? { ...message, content: { ...message.content, answer: event.full ?? `${message.content.answer}${event.content || ''}` } } : message));
          if (event.type === 'final') setMessages((current) => { const next = current.map((message, index) => index === current.length - 1 ? { role: 'assistant', content: normalizeAnswer(event.answer, event.material, event.citations), createdAt: message.createdAt || messageTimestamp() } : message); persist(next); return next; });
          if (event.type === 'error') throw new Error(event.content || '生成失败');
        });
        setMessages((current) => { const next = current.map((message) => message.streaming ? { ...message, streaming: false } : message); persist(next); return next; });
      } catch (error) {
        if (error.name !== 'AbortError') { setMessages((current) => cleanMessages(current)); toast(error.message || '流式回答中断', 'error'); }
      } finally { setLoading(false); setStreamStatus(''); abortRef.current = null; }
    } else {
      setMessages((current) => [...current, userMessage, { role: 'assistant', content: '', thinking: true, createdAt: messageTimestamp() }]);
      try {
        const { data } = await api.post('/hybridrag', { request: question, flow: false, filename: file.name, messages: historyContext ? history : null }, { signal: controller.signal });
        if (!data?.result) throw new Error(data?.message || '服务器未返回结果');
        setMessages((current) => { const next = current.map((message) => message.thinking ? { role: 'assistant', content: normalizeAnswer(data.result.answer, data.result.material, data.result.citations), createdAt: message.createdAt || messageTimestamp() } : message); persist(next); return next; });
      } catch (error) {
        if (error.name !== 'CanceledError' && error.name !== 'AbortError') toast(getApiErrorMessage(error, '获取回答失败'), 'error');
        setMessages((current) => cleanMessages(current));
      } finally { setLoading(false); abortRef.current = null; }
    }
  };

  return <section className="panel rag-panel"><header className="panel-header"><div><h3><Bot size={17} /> RAG 问答</h3><span className="panel-subtitle">{historyContext ? '已携带对话上下文' : '单轮检索模式'}</span></div><span className="stream-pill"><i />{streamOutput ? '流式' : '完整回答'}</span></header><div ref={listRef} className="chat-list" onScroll={(event) => { const element = event.currentTarget; setShowBottom(element.scrollHeight - element.scrollTop - element.clientHeight > 80); }}>
    {!messages.length && <div className="chat-empty"><div className="assistant-orb"><Bot size={24} /></div><h4>向这份文档提问</h4><p>回答会结合原文片段和图谱中的实体关系。</p><div className="suggestions">{['概括核心观点', '哪些概念关系最紧密？', '列出最重要的三个结论'].map((text) => <button key={text} onClick={() => setInput(text)}>{text}</button>)}</div></div>}
    {messages.map((message, index) => <Message key={`${message.role}-${index}`} message={message} status={index === messages.length - 1 ? streamStatus : ''} onCitation={onCitation} />)}
  </div>{showBottom && <button className="scroll-bottom" onClick={() => { setShowBottom(false); listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' }); }}><ArrowDown size={16} /></button>}<div className="chat-composer glass"><textarea rows="2" value={input} disabled={loading} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) send(); }} placeholder="输入与当前文档相关的问题…" /><div className="composer-footer"><span>{input.length}/2000</span>{loading && streamOutput ? <button className="button warning small" onClick={stop}><Square size={13} /> 停止</button> : <button className="icon-button primary-icon" onClick={send} disabled={!input.trim() || loading} aria-label="发送"><Send size={17} /></button>}</div></div>{resizing && <div className="rag-resize-overlay" role="status" aria-live="polite"><LoaderCircle size={24} /><strong>正在调整问答区域</strong><span>松开后重新排版</span></div>}</section>;
}

function Message({ message, status, onCitation }) {
  const isUser = message.role === 'user';
  const content = typeof message.content === 'object' ? message.content : { answer: message.content, material: '', citations: [] };
  const citations = Array.isArray(content.citations) ? content.citations : [];
  const answer = useMemo(() => DOMPurify.sanitize(markdown.render(String(content.answer || ''))), [content.answer]);
  const material = useMemo(() => DOMPurify.sanitize(markdown.render(String(content.material || ''))), [content.material]);
  return <div className={`chat-message ${message.role}`}><div className="chat-avatar">{isUser ? <UserRound size={15} /> : <Bot size={15} />}</div><div className="chat-message-body"><div className="chat-bubble">{message.thinking ? <div className="thinking"><span /><span /><span /><small>正在检索原文和图谱</small></div> : <><div className="message-markdown" dangerouslySetInnerHTML={{ __html: answer }} />{message.streaming && <span className="typing-cursor" />}{status && <small className="stream-status"><LoaderCircle className="spin" size={12} />{status}</small>}{(content.material || citations.length > 0) && <details className="material"><summary>参考资料 <span>{citations.length || ''}</span></summary>{content.material && <div className="material-copy" dangerouslySetInnerHTML={{ __html: material }} />}{citations.length > 0 && <div className="citation-list">{citations.map((citation, index) => { const CitationIcon = citation.type === 'graph' ? Network : FileText; const citationKind = citation.type === 'graph' ? (citation.graphKind === 'edge' ? '图谱关系' : '图谱实体') : '原文'; return <article className={`citation-card ${citation.type}`} key={citation.id || index}><span className="citation-kind">{citationKind}</span><button className="citation-index" onClick={() => onCitation?.(citation)} title={citation.type === 'graph' ? '定位到知识图谱' : '定位到原文'}>{index + 1}</button><CitationIcon size={14} /><div><strong>{citation.label || `引用 ${index + 1}`}</strong><small>{citation.preview || '点击编号定位出处'}</small></div></article>; })}</div>}</details>}</>}</div>{message.createdAt && <time className="message-time" dateTime={message.createdAt}>{formatMessageTime(message.createdAt)}</time>}</div></div>;
}

function normalizeAnswer(answer, material, citations = []) {
  let resolvedAnswer = Array.isArray(answer) ? answer.join('\n') : (answer || '');
  let resolvedMaterial = Array.isArray(material) ? material.join('\n') : (material || '');
  if (typeof resolvedAnswer === 'string') {
    const candidate = resolvedAnswer.replace(/^```json\s*/, '').replace(/\s*```$/, '').trim();
    if (candidate.startsWith('{')) try { const parsed = JSON.parse(candidate); resolvedAnswer = Array.isArray(parsed.answer) ? parsed.answer.join('\n') : parsed.answer || resolvedAnswer; resolvedMaterial = Array.isArray(parsed.material) ? parsed.material.join('\n') : parsed.material || resolvedMaterial; } catch { /* Keep the original model text. */ }
  }
  return { answer: resolvedAnswer, material: resolvedMaterial, citations: Array.isArray(citations) ? citations : [] };
}

function formatMessageTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const time = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
  return date.toDateString() === now.toDateString()
    ? time
    : `${date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })} ${time}`;
}

async function readSse(response, onEvent) {
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
  while (true) {
    const { done, value } = await reader.read(); if (done) break;
    buffer += decoder.decode(value, { stream: true }); const chunks = buffer.split(/\r?\n\r?\n/); buffer = chunks.pop() || '';
    for (const chunk of chunks) { const payload = chunk.split(/\r?\n/).filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n'); if (!payload) continue; try { onEvent(JSON.parse(payload)); } catch (error) { if (error instanceof SyntaxError) continue; throw error; } }
  }
}
