import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Bold, Check, ChevronLeft, ChevronRight, Clipboard, Code2, Download,
  Highlighter, History, Italic, LoaderCircle, List, Quote, RotateCcw, Underline, X,
} from 'lucide-react';
import DOMPurify from 'dompurify';
import MarkdownIt from 'markdown-it';
import api, { encodePathSegment, getApiErrorMessage } from '../api/client.js';

const markdown = new MarkdownIt({ breaks: true, html: false, linkify: true, typographer: true });
const LAZY_DOCUMENT_THRESHOLD = 180000;
const LAZY_CHUNK_TARGET = 24576;
const LAZY_INITIAL_CHUNKS = 2;
const defaultLinkOpen = markdown.renderer.rules.link_open
  || ((tokens, index, options, env, self) => self.renderToken(tokens, index, options));
markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index].attrSet('target', '_blank');
  tokens[index].attrSet('rel', 'noopener noreferrer');
  return defaultLinkOpen(tokens, index, options, env, self);
};

function renderMarkdown(value) {
  return DOMPurify.sanitize(markdown.render(String(value || '')), { ADD_ATTR: ['target', 'rel'] });
}

function renderLazyMarkdownChunk(value, index) {
  return `<section class="markdown-lazy-chunk" data-chunk-index="${index}">${renderMarkdown(value)}</section>`;
}

function splitMarkdownDocument(value) {
  const text = String(value || '');
  if (text.length <= LAZY_DOCUMENT_THRESHOLD) return [{ text, start: 0, end: text.length }];
  const chunks = [];
  let start = 0;
  while (start < text.length) {
    const remaining = text.length - start;
    if (remaining <= LAZY_CHUNK_TARGET * 1.35) {
      chunks.push({ text: text.slice(start), start, end: text.length });
      break;
    }
    const minimum = start + Math.floor(LAZY_CHUNK_TARGET * 0.65);
    const ideal = start + LAZY_CHUNK_TARGET;
    const maximum = Math.min(text.length, start + Math.floor(LAZY_CHUNK_TARGET * 1.4));
    let boundary = text.lastIndexOf('\n\n', maximum);
    if (boundary < minimum) boundary = text.indexOf('\n\n', ideal);
    if (boundary >= minimum && boundary <= maximum) {
      boundary += 2;
    } else {
      boundary = text.lastIndexOf('\n', maximum);
      if (boundary < minimum) boundary = maximum;
      else boundary += 1;
    }
    if (boundary <= start) boundary = Math.min(text.length, start + LAZY_CHUNK_TARGET);
    chunks.push({ text: text.slice(start, boundary), start, end: boundary });
    start = boundary;
  }
  return chunks;
}

function scheduleLazyDocumentWork(callback) {
  if (typeof window.requestIdleCallback === 'function') {
    return { kind: 'idle', id: window.requestIdleCallback(callback, { timeout: 180 }) };
  }
  return { kind: 'timeout', id: window.setTimeout(callback, 16) };
}

function cancelLazyDocumentWork(task) {
  if (!task) return;
  if (task.kind === 'idle') window.cancelIdleCallback?.(task.id);
  else window.clearTimeout(task.id);
}

function normalizeText(value) {
  const raw = String(value || '');
  let text = '';
  const rawMap = [];
  let previousWasSpace = false;
  for (let rawIndex = 0; rawIndex < raw.length; rawIndex += 1) {
    const character = raw[rawIndex];
    const isSpace = /\s/.test(character);
    if (isSpace) {
      if (text && !previousWasSpace) {
        text += ' ';
        rawMap.push(rawIndex);
      }
      previousWasSpace = true;
    } else {
      text += character.toLocaleLowerCase();
      rawMap.push(rawIndex);
      previousWasSpace = false;
    }
  }
  if (text.endsWith(' ')) {
    text = text.slice(0, -1);
    rawMap.pop();
  }
  return { text, rawMap };
}

function collectTextIndex(root) {
  const nodes = [];
  let text = '';
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => node.nodeValue
      ? NodeFilter.FILTER_ACCEPT
      : NodeFilter.FILTER_REJECT,
  });
  let node = walker.nextNode();
  while (node) {
    const start = text.length;
    text += node.nodeValue;
    nodes.push({ node, start, end: text.length });
    node = walker.nextNode();
  }
  return { text, nodes, normalized: normalizeText(text) };
}

function markdownToPlainText(value) {
  const container = document.createElement('div');
  container.innerHTML = DOMPurify.sanitize(markdown.render(String(value || '')));
  return container.textContent || '';
}

function findNormalizedRange(index, query, from = 0, to = Infinity, occurrence = 0) {
  const normalizedQuery = normalizeText(query).text;
  if (!normalizedQuery) return null;
  let position = index.normalized.text.indexOf(normalizedQuery);
  while (position >= 0) {
    const rawStart = index.normalized.rawMap[position];
    const rawEndIndex = position + normalizedQuery.length - 1;
    const rawEnd = (index.normalized.rawMap[rawEndIndex] ?? rawStart) + 1;
    if (rawStart >= from && rawEnd <= to) {
      if (occurrence <= 0) return { start: rawStart, end: rawEnd };
      occurrence -= 1;
    }
    position = index.normalized.text.indexOf(normalizedQuery, position + 1);
  }
  return null;
}

function findBlockRange(index, blockText, occurrence = 0) {
  const plainText = markdownToPlainText(blockText);
  const exact = findNormalizedRange(index, plainText, 0, Infinity, occurrence);
  if (exact) return exact;

  const candidates = plainText
    .split(/\n+|(?<=[。！？.!?])\s+/)
    .map((value) => value.trim())
    .filter((value) => value.length >= 16)
    .sort((left, right) => right.length - left.length);
  for (const candidate of candidates) {
    const range = findNormalizedRange(index, candidate);
    if (range) return range;
  }
  return null;
}

function wrapRawRange(index, range, className) {
  const marks = [];
  [...index.nodes].reverse().forEach(({ node, start, end }) => {
    const overlapStart = Math.max(start, range.start);
    const overlapEnd = Math.min(end, range.end);
    if (overlapStart >= overlapEnd) return;
    const localStart = overlapStart - start;
    const localEnd = overlapEnd - start;
    if (!node.nodeValue.slice(localStart, localEnd).trim()) return;
    const selection = document.createRange();
    selection.setStart(node, localStart);
    selection.setEnd(node, localEnd);
    const mark = document.createElement('mark');
    mark.className = className;
    try {
      selection.surroundContents(mark);
      marks.unshift(mark);
    } catch {
      // A single text node should always be surroundable; ignore malformed browser ranges.
    }
  });
  return marks;
}

function collectTermMatches(index, terms, blockRange) {
  const matches = [];
  const occupied = [];
  const lowerBound = (target) => {
    let left = 0;
    let right = index.normalized.rawMap.length;
    while (left < right) {
      const middle = Math.floor((left + right) / 2);
      if (index.normalized.rawMap[middle] < target) left = middle + 1;
      else right = middle;
    }
    return left;
  };
  const normalizedStart = lowerBound(blockRange.start);
  const normalizedEnd = lowerBound(blockRange.end);
  const addUncoveredRanges = (start, end, className) => {
    let uncovered = [{ start, end }];
    occupied.forEach((existing) => {
      uncovered = uncovered.flatMap((range) => {
        if (range.end <= existing.start || range.start >= existing.end) return [range];
        const pieces = [];
        if (range.start < existing.start) pieces.push({ start: range.start, end: existing.start });
        if (range.end > existing.end) pieces.push({ start: existing.end, end: range.end });
        return pieces;
      });
    });
    uncovered.forEach((range) => {
      if (range.end <= range.start) return;
      const match = { ...range, className };
      matches.push(match);
      occupied.push(match);
    });
  };
  terms
    .filter((item) => item.term)
    .sort((left, right) => right.priority - left.priority || right.term.length - left.term.length)
    .forEach((item) => {
      const normalizedTerm = normalizeText(item.term).text;
      if (!normalizedTerm) return;
      let position = index.normalized.text.indexOf(normalizedTerm, normalizedStart);
      while (position >= 0 && position < normalizedEnd) {
        const rawStart = index.normalized.rawMap[position];
        const rawEnd = (index.normalized.rawMap[position + normalizedTerm.length - 1] ?? rawStart) + 1;
        const insideBlock = rawStart >= blockRange.start && rawEnd <= blockRange.end;
        if (insideBlock) addUncoveredRanges(rawStart, rawEnd, item.className);
        position = index.normalized.text.indexOf(normalizedTerm, position + normalizedTerm.length);
      }
    });
  return matches.sort((left, right) => right.start - left.start);
}

function collectIndexedDocumentMatches(index, blocks) {
  const matches = [];
  let normalizedCursor = 0;
  (Array.isArray(blocks) ? blocks : []).forEach((block) => {
    const blockText = normalizeText(markdownToPlainText(block.text || '')).text;
    if (!blockText) return;
    let position = index.normalized.text.indexOf(blockText, normalizedCursor);
    if (position < 0) position = index.normalized.text.indexOf(blockText);
    if (position < 0) return;
    const rawStart = index.normalized.rawMap[position];
    const rawEndIndex = position + blockText.length - 1;
    const rawEnd = (index.normalized.rawMap[rawEndIndex] ?? rawStart) + 1;
    normalizedCursor = position + blockText.length;
    const terms = block.highlight_terms || {};
    matches.push(...collectTermMatches(index, [
      ...(terms.entityTerms || []).map((term) => ({
        term, className: 'km-highlight-entity', priority: 3,
      })),
      ...(terms.relationTerms || []).map((term) => ({
        term, className: 'km-highlight-relation', priority: 2,
      })),
    ], { start: rawStart, end: rawEnd }));
  });
  return matches;
}

function wrapRawRanges(index, ranges) {
  const ordered = [...ranges].sort((left, right) => left.start - right.start);
  index.nodes.forEach(({ node, start, end }) => {
    const overlaps = ordered.filter((range) => range.end > start && range.start < end);
    if (!overlaps.length || !node.parentNode) return;
    const fragment = document.createDocumentFragment();
    let cursor = 0;
    overlaps.forEach((range) => {
      const localStart = Math.max(0, range.start - start);
      const localEnd = Math.min(node.nodeValue.length, range.end - start);
      if (localStart > cursor) {
        fragment.appendChild(document.createTextNode(node.nodeValue.slice(cursor, localStart)));
      }
      if (localEnd > localStart) {
        const mark = document.createElement('mark');
        mark.className = range.className;
        mark.textContent = node.nodeValue.slice(localStart, localEnd);
        fragment.appendChild(mark);
      }
      cursor = Math.max(cursor, localEnd);
    });
    if (cursor < node.nodeValue.length) {
      fragment.appendChild(document.createTextNode(node.nodeValue.slice(cursor)));
    }
    node.parentNode.replaceChild(fragment, node);
  });
}

function renderHighlightedMarkdown(value, terms) {
  const container = document.createElement('div');
  container.innerHTML = renderMarkdown(value);
  const index = collectTextIndex(container);
  const matches = collectTermMatches(index, [
    ...[...(terms?.entityTerms || [])].map((term) => ({
      term, className: 'km-highlight-entity', priority: 3,
    })),
    ...[...(terms?.relationTerms || [])].map((term) => ({
      term, className: 'km-highlight-relation', priority: 2,
    })),
  ], { start: 0, end: index.text.length });
  wrapRawRanges(index, matches);
  return container.innerHTML;
}

export default function OriginalDocumentPanel({
  file, refreshToken, toast, onDirtyChange, onDraftSaved, evidence, showAllEvidence,
  onShowAllEvidence, onHighlightAll, onClearEvidence, locating, resizing,
}) {
  const [content, setContent] = useState('');
  const [rich, setRich] = useState('');
  const [mode, setMode] = useState('preview');
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [restoringRevision, setRestoringRevision] = useState(null);
  const [activeEvidenceIndex, setActiveEvidenceIndex] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [lazyLoading, setLazyLoading] = useState(false);
  const editorRef = useRef(null);
  const articleRef = useRef(null);
  const scrollRef = useRef(null);
  const historyButtonRef = useRef(null);
  const highlightHtmlCacheRef = useRef(new Map());
  const highlightCacheRequestRef = useRef(0);
  const highlightCacheDocumentRef = useRef('');
  const lastScrolledEvidenceRef = useRef('');

  const evidenceResults = Array.isArray(evidence?.results) ? evidence.results : [];
  const contentChunks = useMemo(() => splitMarkdownDocument(content), [content]);
  const lazyDocument = content.length > LAZY_DOCUMENT_THRESHOLD;
  const requiresCompleteDocument = evidenceResults.length > 0;
  const documentHighlightTermsByChunk = useMemo(() => {
    const buckets = contentChunks.map(() => ({ entityTerms: new Set(), relationTerms: new Set() }));
    const blocks = Array.isArray(evidence?.allBlocks) ? evidence.allBlocks : [];
    if (!lazyDocument || !evidence?.fullDocument || !blocks.length) return buckets;
    let cursor = 0;
    blocks.forEach((block, blockIndex) => {
      const blockText = String(block?.text || '');
      const terms = block?.highlight_terms || {};
      const entityTerms = Array.isArray(terms.entityTerms) ? terms.entityTerms : [];
      const relationTerms = Array.isArray(terms.relationTerms) ? terms.relationTerms : [];
      let position = blockText ? content.indexOf(blockText, cursor) : -1;
      if (position < 0 && blockText) position = content.indexOf(blockText);
      let chunkIndexes = [];
      if (position >= 0) {
        const blockEnd = position + blockText.length;
        cursor = blockEnd;
        contentChunks.forEach((chunk, chunkIndex) => {
          if (chunk.end > position && chunk.start < blockEnd) chunkIndexes.push(chunkIndex);
        });
      } else {
        const anchor = [...entityTerms, ...relationTerms]
          .map((term) => String(term || '').trim())
          .find((term) => term && content.includes(term));
        const anchorPosition = anchor ? content.indexOf(anchor) : -1;
        const fallbackIndex = anchorPosition >= 0
          ? contentChunks.findIndex((chunk) => chunk.start <= anchorPosition && chunk.end > anchorPosition)
          : Math.floor((blockIndex / Math.max(1, blocks.length)) * contentChunks.length);
        chunkIndexes = [Math.max(0, Math.min(contentChunks.length - 1, fallbackIndex))];
      }
      chunkIndexes.forEach((chunkIndex) => {
        entityTerms.forEach((term) => {
          const value = String(term || '').trim();
          if (value) buckets[chunkIndex].entityTerms.add(value);
        });
        relationTerms.forEach((term) => {
          const value = String(term || '').trim();
          if (value) buckets[chunkIndex].relationTerms.add(value);
        });
      });
    });
    return buckets;
  }, [content, contentChunks, evidence?.allBlocks, evidence?.fullDocument, lazyDocument]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setDirty(false);
    setHistoryOpen(false);
    setActiveEvidenceIndex(0);
    onDirtyChange?.(false);
    setMode('preview');
    api.get(`/file-content/${encodePathSegment(file.name)}`)
      .then(({ data }) => {
        if (!alive) return;
        setContent(data.content || '');
        setRich(DOMPurify.sanitize(data.rich_content || ''));
      })
      .catch((error) => toast(getApiErrorMessage(error, '无法加载原文'), 'error'))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [file.name, onDirtyChange, refreshToken, toast]);

  useEffect(() => {
    if (mode === 'edit' && editorRef.current) {
      editorRef.current.innerHTML = rich || markdown.render(content);
    }
  }, [file.name, loading, mode]);

  useEffect(() => {
    if (!evidence?.requestId) return;
    setActiveEvidenceIndex(0);
    setMode('preview');
  }, [evidence?.requestId]);

  useLayoutEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    if (resizing) {
      const bounds = scroller.getBoundingClientRect();
      scroller.style.width = `${bounds.width}px`;
      scroller.style.height = `${bounds.height}px`;
      scroller.style.maxWidth = 'none';
      return;
    }
    scroller.style.removeProperty('width');
    scroller.style.removeProperty('height');
    scroller.style.removeProperty('max-width');
  }, [resizing]);

  const rendered = useMemo(() => {
    if (!lazyDocument || requiresCompleteDocument) return renderMarkdown(content);
    return contentChunks
      .slice(0, LAZY_INITIAL_CHUNKS)
      .map((chunk, index) => renderLazyMarkdownChunk(chunk.text, index))
      .join('');
  }, [content, contentChunks, lazyDocument, requiresCompleteDocument]);

  useLayoutEffect(() => {
    const article = articleRef.current;
    const scroller = scrollRef.current;
    const result = evidenceResults[activeEvidenceIndex];
    const fullDocument = Boolean(evidence?.fullDocument);
    if (mode !== 'preview' || !article || !scroller) return undefined;
    if (resizing) return undefined;
    if (!fullDocument && !result?.text) {
      if (!lazyDocument || !article.querySelector('.markdown-lazy-chunk')) article.innerHTML = rendered;
      return undefined;
    }
    if (lazyDocument && fullDocument) {
      if (!article.querySelector('.markdown-lazy-chunk')) article.innerHTML = rendered;
      return undefined;
    }

    const cacheKey = [
      evidence?.requestId || 0,
      activeEvidenceIndex,
      fullDocument ? 'full-document' : result.bid,
      fullDocument ? '' : result.signature || '',
      showAllEvidence ? 'all' : 'current',
    ].join(':');
    if (highlightCacheDocumentRef.current !== rendered) {
      highlightHtmlCacheRef.current.clear();
      highlightCacheDocumentRef.current = rendered;
    }
    if (highlightCacheRequestRef.current !== (evidence?.requestId || 0)) {
      highlightHtmlCacheRef.current.clear();
      highlightCacheRequestRef.current = evidence?.requestId || 0;
    }
    const cachedHtml = highlightHtmlCacheRef.current.get(cacheKey);
    if (cachedHtml) {
      article.innerHTML = cachedHtml;
    } else {
      article.innerHTML = rendered;
      const initialIndex = collectTextIndex(article);
      const blockRange = fullDocument
        ? { start: 0, end: initialIndex.text.length }
        : findBlockRange(initialIndex, result.text, result.occurrence || 0);
      if (!blockRange) {
        toast(`未能在预览中定位文本块 ${result.bid}`, 'error');
        return undefined;
      }

      if (!fullDocument) wrapRawRange(initialIndex, blockRange, 'km-highlight-block');
      const termIndex = collectTextIndex(article);
      const terms = evidence?.terms || {};
      const includeAllTerms = fullDocument || showAllEvidence;
      const matches = fullDocument ? collectIndexedDocumentMatches(
        termIndex,
        evidence?.allBlocks,
      ) : collectTermMatches(termIndex, [
        ...(terms.selectedEntityTerms || []).map((term) => ({
          term, className: 'km-highlight-selected-entity', priority: 5,
        })),
        ...(terms.selectedRelationTerms || []).map((term) => ({
          term, className: 'km-highlight-selected-relation', priority: 5,
        })),
        ...(terms.selectedEvidenceTerms || []).map((term) => ({
          term, className: 'km-highlight-evidence-current', priority: 4,
        })),
        ...(includeAllTerms ? terms.entityTerms || [] : [])
          .map((term) => ({ term, className: 'km-highlight-entity', priority: 3 })),
        ...(includeAllTerms ? terms.relationTerms || [] : [])
          .map((term) => ({ term, className: 'km-highlight-relation', priority: 2 })),
        ...(includeAllTerms ? terms.evidenceTerms || [] : [])
          .map((term) => ({ term, className: 'km-highlight-evidence', priority: 1 })),
      ], blockRange);
      wrapRawRanges(termIndex, matches);
      highlightHtmlCacheRef.current.set(cacheKey, article.innerHTML);
      if (highlightHtmlCacheRef.current.size > 4) {
        const oldestKey = highlightHtmlCacheRef.current.keys().next().value;
        highlightHtmlCacheRef.current.delete(oldestKey);
      }
    }

    const marker = fullDocument ? null : evidence?.kind === 'edge'
      ? article.querySelector('mark.km-highlight-selected-relation')
        || article.querySelector('mark.km-highlight-evidence-current')
        || article.querySelector('mark.km-highlight-selected-entity')
      : article.querySelector('mark.km-highlight-selected-entity');
    const scrollMarker = marker || article.querySelector('mark.km-highlight-block');
    const scrollKey = `${evidence?.requestId || 0}:${activeEvidenceIndex}`;
    if (scrollMarker && lastScrolledEvidenceRef.current !== scrollKey) {
      lastScrolledEvidenceRef.current = scrollKey;
      requestAnimationFrame(() => {
        const markerRect = scrollMarker.getBoundingClientRect();
        const scrollerRect = scroller.getBoundingClientRect();
        scroller.scrollTo({
          top: Math.max(0, scroller.scrollTop + markerRect.top - scrollerRect.top - scroller.clientHeight / 2),
          behavior: 'smooth',
        });
      });
    }
  }, [activeEvidenceIndex, evidence, evidenceResults, lazyDocument, mode, rendered, resizing, showAllEvidence, toast]);

  useEffect(() => {
    const article = articleRef.current;
    const scroller = scrollRef.current;
    if (mode !== 'preview' || !article || !scroller || resizing
      || !lazyDocument || requiresCompleteDocument
      || contentChunks.length <= LAZY_INITIAL_CHUNKS) return undefined;

    let cancelled = false;
    let task = null;
    let frame = null;
    const loadedIndexes = [...article.querySelectorAll('.markdown-lazy-chunk')]
      .map((section) => Number(section.dataset.chunkIndex))
      .filter(Number.isFinite);
    let nextIndex = Math.min(
      contentChunks.length,
      loadedIndexes.length ? Math.max(...loadedIndexes) + 1 : LAZY_INITIAL_CHUNKS,
    );
    const isNearLoadedEnd = () => (
      scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight
      <= Math.max(900, scroller.clientHeight * 1.25)
    );
    const scheduleNext = () => {
      if (cancelled || task || nextIndex >= contentChunks.length) return;
      setLazyLoading(true);
      task = scheduleLazyDocumentWork(() => {
        task = null;
        if (cancelled || !article.isConnected || nextIndex >= contentChunks.length) {
          if (!cancelled) setLazyLoading(false);
          return;
        }
        article.insertAdjacentHTML(
          'beforeend',
          renderLazyMarkdownChunk(contentChunks[nextIndex].text, nextIndex),
        );
        nextIndex += 1;
        if (nextIndex < contentChunks.length && isNearLoadedEnd()) scheduleNext();
        else setLazyLoading(false);
      });
    };
    const checkPosition = () => {
      if (isNearLoadedEnd()) scheduleNext();
    };

    scroller.addEventListener('scroll', checkPosition, { passive: true });
    frame = window.requestAnimationFrame(checkPosition);
    return () => {
      cancelled = true;
      scroller.removeEventListener('scroll', checkPosition);
      if (frame !== null) window.cancelAnimationFrame(frame);
      cancelLazyDocumentWork(task);
      setLazyLoading(false);
    };
  }, [contentChunks, evidence?.fullDocument, lazyDocument, mode, rendered, requiresCompleteDocument, resizing]);

  useEffect(() => {
    const article = articleRef.current;
    const scroller = scrollRef.current;
    if (mode !== 'preview' || !article || !scroller || resizing
      || !lazyDocument || !evidence?.fullDocument) return undefined;

    let cancelled = false;
    let frame = null;
    let highlightTask = null;
    const htmlCache = new Map();
    const highlightQueue = [];
    const queuedChunks = new Set();
    const rememberHtml = (index, value) => {
      htmlCache.delete(index);
      htmlCache.set(index, value);
      while (htmlCache.size > 8) htmlCache.delete(htmlCache.keys().next().value);
    };
    const isSectionInWindow = (section) => {
      const scrollerRect = scroller.getBoundingClientRect();
      const rect = section.getBoundingClientRect();
      const margin = Math.max(360, scroller.clientHeight * 0.5);
      return rect.bottom >= scrollerRect.top - margin
        && rect.top <= scrollerRect.bottom + margin;
    };
    const scheduleHighlight = () => {
      if (cancelled || highlightTask || !highlightQueue.length) return;
      highlightTask = scheduleLazyDocumentWork(() => {
        highlightTask = null;
        const item = highlightQueue.shift();
        if (!item) return;
        queuedChunks.delete(item.chunkIndex);
        const { section, chunkIndex } = item;
        const chunk = contentChunks[chunkIndex];
        if (!cancelled && chunk && section.isConnected
          && section.dataset.highlighted !== 'true' && isSectionInWindow(section)) {
          let cached = htmlCache.get(chunkIndex);
          if (!cached) {
            cached = {
              plain: section.innerHTML,
              highlighted: renderHighlightedMarkdown(
                chunk.text,
                documentHighlightTermsByChunk[chunkIndex],
              ),
            };
            rememberHtml(chunkIndex, cached);
          }
          section.innerHTML = cached.highlighted;
          section.dataset.highlighted = 'true';
        }
        scheduleHighlight();
      });
    };
    const refreshWindow = () => {
      frame = null;
      if (cancelled) return;
      article.querySelectorAll('.markdown-lazy-chunk').forEach((section) => {
        const chunkIndex = Number(section.dataset.chunkIndex);
        const chunk = contentChunks[chunkIndex];
        if (!chunk) return;
        const inWindow = isSectionInWindow(section);
        const highlighted = section.dataset.highlighted === 'true';
        if (inWindow && !highlighted && !queuedChunks.has(chunkIndex)) {
          queuedChunks.add(chunkIndex);
          highlightQueue.push({ section, chunkIndex });
          scheduleHighlight();
        } else if (!inWindow && highlighted) {
          const cached = htmlCache.get(chunkIndex);
          section.innerHTML = cached?.plain || renderMarkdown(chunk.text);
          delete section.dataset.highlighted;
        }
      });
    };
    const scheduleRefresh = () => {
      if (frame === null) frame = window.requestAnimationFrame(refreshWindow);
    };
    const observer = typeof MutationObserver === 'function'
      ? new MutationObserver(scheduleRefresh)
      : null;

    scroller.addEventListener('scroll', scheduleRefresh, { passive: true });
    observer?.observe(article, { childList: true });
    scheduleRefresh();
    return () => {
      cancelled = true;
      scroller.removeEventListener('scroll', scheduleRefresh);
      observer?.disconnect();
      if (frame !== null) window.cancelAnimationFrame(frame);
      cancelLazyDocumentWork(highlightTask);
      article.querySelectorAll('.markdown-lazy-chunk[data-highlighted="true"]').forEach((section) => {
        const chunkIndex = Number(section.dataset.chunkIndex);
        const chunk = contentChunks[chunkIndex];
        if (!chunk) return;
        section.innerHTML = htmlCache.get(chunkIndex)?.plain || renderMarkdown(chunk.text);
        delete section.dataset.highlighted;
      });
    };
  }, [contentChunks, documentHighlightTermsByChunk, evidence?.fullDocument, lazyDocument, mode, resizing]);

  const markDirty = () => {
    setDirty(true);
    onDirtyChange?.(true);
  };
  const editInput = () => {
    if (!editorRef.current) return;
    setRich(editorRef.current.innerHTML);
    setContent(editorRef.current.innerText);
    markDirty();
  };
  const save = async () => {
    if (!content.trim()) return toast('文档不能为空', 'error');
    setSaving(true);
    try {
      await api.post(`/file-content/${encodePathSegment(file.name)}`, {
        content,
        rich_content: rich || editorRef.current?.innerHTML || '',
      });
      setDirty(false);
      onDirtyChange?.(false);
      onDraftSaved?.();
      toast('文档草稿已保存', 'success');
    } catch (error) {
      toast(getApiErrorMessage(error, '保存草稿失败'), 'error');
    } finally {
      setSaving(false);
    }
  };
  const toggleHistory = async () => {
    if (historyOpen) {
      setHistoryOpen(false);
      return;
    }
    setHistoryOpen(true);
    setHistoryLoading(true);
    setHistoryError('');
    try {
      const { data } = await api.get(`/document-history/${encodePathSegment(file.name)}`);
      setHistory(data.versions || []);
    } catch (error) {
      const message = getApiErrorMessage(error, '文档历史加载失败');
      setHistoryError(message);
      toast(message, 'error');
    } finally {
      setHistoryLoading(false);
    }
  };
  const restore = async (revision) => {
    if (!window.confirm(`还原到版本 ${revision}？当前未保存的修改会被覆盖。`)) return;
    setRestoringRevision(revision);
    try {
      await api.post(`/document-restore/${encodePathSegment(file.name)}/${revision}`);
      const { data } = await api.get(`/file-content/${encodePathSegment(file.name)}`);
      setContent(data.content || '');
      setRich(DOMPurify.sanitize(data.rich_content || ''));
      setDirty(false);
      setMode('preview');
      setHistoryOpen(false);
      onDirtyChange?.(false);
      onDraftSaved?.();
      toast('文档已还原为草稿', 'success');
    } catch (error) {
      toast(getApiErrorMessage(error, '还原文档失败'), 'error');
    } finally {
      setRestoringRevision(null);
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      toast('原文已复制', 'success');
    } catch {
      toast('复制失败', 'error');
    }
  };
  const download = () => {
    const extension = file.name.split('.').pop()?.toLowerCase();
    const name = ['md', 'markdown', 'txt'].includes(extension) ? file.name : `${file.name}.md`;
    const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
  };
  const command = (name, value) => {
    document.execCommand(name, false, value);
    editInput();
    editorRef.current?.focus();
  };

  return (
    <section className="panel document-panel">
      <header className="panel-header">
        <div>
          <h3>原文</h3>
          <span className="panel-subtitle">{content ? `${content.length.toLocaleString()} 字` : '等待内容'}</span>
          {dirty && <span className="draft-tag"><span aria-hidden="true">·</span> 有未保存修改</span>}
        </div>
        <div className="panel-actions">
          <div className="segmented compact">
            {[[`preview`, '预览'], ['edit', '编辑'], ['source', '源码']].map(([value, label]) => (
              <button key={value} className={mode === value ? 'active' : ''} onClick={() => setMode(value)}>{label}</button>
            ))}
          </div>
          <button className="icon-button" onClick={copy} disabled={!content} aria-label="复制"><Clipboard size={16} /></button>
          <button className="icon-button" onClick={download} disabled={!content} aria-label="下载"><Download size={16} /></button>
          <button
            className={`icon-button highlight-all-button ${evidenceResults.length > 0 ? (showAllEvidence ? 'active' : '') : (evidence?.fullDocument ? 'active' : '')}`}
            onClick={onHighlightAll}
            disabled={!content || loading}
            aria-label={evidenceResults.length > 0 ? '高亮当前文本块中的实体和关系' : '高亮全文实体和关系'}
            aria-pressed={Boolean(evidenceResults.length > 0 ? showAllEvidence : evidence?.fullDocument)}
            title={evidenceResults.length > 0 ? '高亮当前文本块中的实体和关系' : '高亮全文实体和关系'}
          ><Highlighter size={16} /></button>
          {mode === 'edit' && (
            <>
              <button className="button primary small" onClick={save} disabled={!dirty || saving}>
                {saving ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />} 保存草稿
              </button>
              <button
                ref={historyButtonRef}
                className={`icon-button history-button ${historyOpen ? 'active' : ''}`}
                onClick={toggleHistory}
                aria-label="文档历史"
                title="文档历史"
              ><History size={16} /></button>
            </>
          )}
        </div>
      </header>

      <div className={`panel-content document-frame-wrap ${resizing ? 'is-layout-resizing' : ''}`}>
        <div ref={scrollRef} className="document-content-shell">
        {evidenceResults.length > 0 && (
          <EvidenceLocator
            kind={evidence.kind}
            results={evidenceResults}
            activeIndex={activeEvidenceIndex}
            onSelect={setActiveEvidenceIndex}
            showAllEvidence={showAllEvidence}
            onShowAllEvidence={onShowAllEvidence}
            onClear={onClearEvidence}
          />
        )}
        {locating && <div className="locating-skeleton" aria-label="正在定位出处"><span /><span /><span /></div>}
        {loading ? (
          <div className="empty-state"><LoaderCircle className="spin" /><span>正在读取原文…</span></div>
        ) : !content ? (
          <div className="empty-state"><Code2 size={20} /><span>无法加载原文</span></div>
        ) : mode === 'preview' ? (
          <article
            ref={articleRef}
            className="markdown-body"
            style={{ fontSize: `${zoom}em` }}
            dangerouslySetInnerHTML={{ __html: rendered }}
            onWheel={(event) => {
              if (event.ctrlKey || event.metaKey) {
                event.preventDefault();
                setZoom((value) => Math.max(.7, Math.min(2, value + (event.deltaY < 0 ? .1 : -.1))));
              }
            }}
          />
        ) : mode === 'edit' ? (
          <div className="editor-shell">
            <div className="editor-toolbar">
              <button onMouseDown={(event) => event.preventDefault()} onClick={() => command('bold')} aria-label="粗体"><Bold size={15} /></button>
              <button onMouseDown={(event) => event.preventDefault()} onClick={() => command('italic')} aria-label="斜体"><Italic size={15} /></button>
              <button onMouseDown={(event) => event.preventDefault()} onClick={() => command('underline')} aria-label="下划线"><Underline size={15} /></button>
              <button onMouseDown={(event) => event.preventDefault()} onClick={() => command('insertUnorderedList')} aria-label="无序列表"><List size={15} /></button>
              <button onMouseDown={(event) => event.preventDefault()} onClick={() => command('formatBlock', 'blockquote')} aria-label="引用"><Quote size={15} /></button>
              <button onMouseDown={(event) => event.preventDefault()} onClick={() => command('removeFormat')} aria-label="清除格式"><RotateCcw size={15} /></button>
            </div>
            <div ref={editorRef} className="rich-editor markdown-body" contentEditable suppressContentEditableWarning onInput={editInput} />
          </div>
        ) : (
          <pre className="source-view"><code>{content}</code></pre>
        )}
        {mode === 'preview' && lazyLoading && (
          <div className="document-lazy-loader" role="status" aria-live="polite">
            <LoaderCircle className="spin" size={17} />
            <span>正在加载后续内容…</span>
          </div>
        )}
        </div>
        {resizing && (
          <div className="document-resize-overlay" role="status" aria-live="polite">
            <LoaderCircle size={24} />
            <strong>正在调整原文区域</strong>
            <span>松开后重新排版</span>
          </div>
        )}
      </div>

      <HistoryPopover
        open={historyOpen}
        anchorRef={historyButtonRef}
        versions={history}
        loading={historyLoading}
        error={historyError}
        restoringRevision={restoringRevision}
        onRestore={restore}
        onClose={() => setHistoryOpen(false)}
      />
    </section>
  );
}

function EvidenceLocator({
  kind, results, activeIndex, onSelect, showAllEvidence, onShowAllEvidence, onClear,
}) {
  const previous = () => onSelect((activeIndex - 1 + results.length) % results.length);
  const next = () => onSelect((activeIndex + 1) % results.length);
  return (
    <div className="evidence-locator">
      <div className="evidence-locator-header">
        <strong>{kind === 'edge' ? '关系出处' : kind === 'source' ? '原文出处' : '节点出处'}</strong>
        <span>{activeIndex + 1} / {results.length}</span>
        <div className="evidence-scope" aria-label="高亮范围">
          <button className={!showAllEvidence ? 'active' : ''} onClick={() => onShowAllEvidence?.(false)}>仅当前</button>
          <button className={showAllEvidence ? 'active' : ''} onClick={() => onShowAllEvidence?.(true)}>全部实体与关系</button>
        </div>
        <button className="icon-button quiet" onClick={previous} aria-label="上一个出处"><ChevronLeft size={14} /></button>
        <button className="icon-button quiet" onClick={next} aria-label="下一个出处"><ChevronRight size={14} /></button>
        <button className="icon-button quiet" onClick={onClear} aria-label="关闭出处定位" title="关闭出处定位"><X size={14} /></button>
      </div>
      <div className="evidence-result-list">
        {results.map((result, index) => (
          <button
            key={`${result.bid}-${index}`}
            className={index === activeIndex ? 'active' : ''}
            onClick={() => onSelect(index)}
          >
            <span>{result.bid}</span>
            <small>{result.preview || '文本块内容为空'}</small>
          </button>
        ))}
      </div>
    </div>
  );
}

function HistoryPopover({
  open, anchorRef, versions, loading, error, restoringRevision, onRestore, onClose,
}) {
  const [position, setPosition] = useState({ left: 12, top: 12 });
  useLayoutEffect(() => {
    if (!open || !anchorRef.current) return undefined;
    const update = () => {
      const rect = anchorRef.current.getBoundingClientRect();
      const width = Math.min(310, window.innerWidth - 24);
      setPosition({
        left: Math.max(12, Math.min(window.innerWidth - width - 12, rect.right - width)),
        top: Math.max(12, Math.min(Math.max(12, window.innerHeight - 372), rect.bottom + 7)),
      });
    };
    update();
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [anchorRef, open]);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, open]);
  if (!open) return null;

  return createPortal(
    <>
      <div className="popover-dismiss" onMouseDown={onClose} />
      <section className="document-history-popover glass" style={position} aria-label="文档历史版本">
        <header>
          <div><strong>文档历史</strong><small>还原后会生成新草稿</small></div>
          <button className="icon-button quiet" onClick={onClose} aria-label="关闭"><X size={15} /></button>
        </header>
        <div className="document-history-list">
          {loading && <div className="history-state"><LoaderCircle className="spin" size={17} />正在读取历史…</div>}
          {!loading && error && <div className="history-state error">{error}</div>}
          {!loading && !error && !versions.length && <div className="history-state">暂无可还原的文档版本</div>}
          {!loading && !error && versions.slice().reverse().map((version) => (
            <button
              key={version.revision}
              className="document-history-item"
              disabled={restoringRevision !== null}
              onClick={() => onRestore(version.revision)}
            >
              <span className="history-revision">v{version.revision}</span>
              <span><strong>{version.description || '文档修改'}</strong><small>{formatHistoryDate(version.created_at)}</small></span>
              {restoringRevision === version.revision
                ? <LoaderCircle className="spin" size={15} />
                : <RotateCcw size={14} />}
            </button>
          ))}
        </div>
      </section>
    </>,
    document.body,
  );
}

function formatHistoryDate(value) {
  if (!value) return '时间未记录';
  const timestamp = typeof value === 'number' && value < 10_000_000_000 ? value * 1000 : value;
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString('zh-CN', { hour12: false });
}
