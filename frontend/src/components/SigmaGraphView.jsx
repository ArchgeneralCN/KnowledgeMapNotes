import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { CheckCheck, ChevronDown, ChevronRight, CircleOff, LocateFixed, Minus, Network, Plus, RefreshCw, Search, X } from 'lucide-react';
import { createNodeImageProgram } from '@sigma/node-image';
import { MultiDirectedGraph } from 'graphology';
import louvain from 'graphology-communities-louvain';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import betweennessCentrality from 'graphology-metrics/centrality/betweenness';
import { createUnweightedIndexedBrandes } from 'graphology-shortest-path/indexed-brandes';
import Sigma from 'sigma';
import api, { encodePathSegment, getApiErrorMessage } from '../api/client.js';

const NODE_COLORS = ['#e22653', '#3478c5', '#5c9f68', '#d58d37', '#8b61a8', '#258c9a', '#ad6274', '#767c3b', '#5b78ac', '#b05c51'];
const NodeTypeImageProgram = createNodeImageProgram({
  size: { mode: 'force', value: 256 },
  objectFit: 'contain',
  padding: 0.14,
  keepWithinCircle: true,
});
const TYPE_ICON_ALIASES = {
  'chart type': 'charttype', '图表类型': 'charttype', '图表': 'charttype',
  company: 'company', '公司': 'company', '企业': 'company',
  concept: 'concept', '概念': 'concept',
  field: 'field', '领域': 'field', '学科': 'field',
  list: 'list', '列表': 'list',
  method: 'method', '方法': 'method',
  organization: 'organization', '组织': 'organization', '机构': 'organization',
  person: 'person', '人物': 'person', '人名': 'person',
  technology: 'technology', '技术': 'technology',
  tool: 'tool', '工具': 'tool',
  unknown: 'unknown', '未知': 'unknown', '未分类': 'unknown',
};

const normalize = (value) => String(value ?? '').trim();
const isEdgeKind = (kind) => ['edge', 'relation', 'relationship'].includes(String(kind || '').toLowerCase());

function seededUnit(value, salt) {
  let hash = 2166136261 ^ salt;
  const input = String(value);
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  hash += hash << 13;
  hash ^= hash >>> 7;
  hash += hash << 3;
  hash ^= hash >>> 17;
  hash += hash << 5;
  return (hash >>> 0) / 4294967296;
}

function initialPosition(key, index, count) {
  if (count <= 1) return { x: 0, y: 0 };
  const spread = Math.max(24, Math.sqrt(count) * 4.5);
  return {
    x: (seededUnit(`${key}:${index}`, 0x9e3779b9) - 0.5) * spread * 1.25,
    y: (seededUnit(`${key}:${index}`, 0x85ebca6b) - 0.5) * spread,
  };
}

function iconNameOf(type) {
  const token = normalize(type).toLocaleLowerCase();
  if (TYPE_ICON_ALIASES[token]) return TYPE_ICON_ALIASES[token];
  if (/person|人物|人名|作者|角色/.test(token)) return 'person';
  if (/organ|机构|组织|单位|协会/.test(token)) return 'organization';
  if (/company|公司|企业|品牌/.test(token)) return 'company';
  if (/concept|概念|理论|定义/.test(token)) return 'concept';
  if (/field|领域|学科|行业/.test(token)) return 'field';
  if (/method|方法|流程|算法/.test(token)) return 'method';
  if (/technolog|技术|系统/.test(token)) return 'technology';
  if (/tool|工具|软件|平台/.test(token)) return 'tool';
  if (/chart|图表|图形/.test(token)) return 'charttype';
  if (/list|列表|清单/.test(token)) return 'list';
  return 'unknown';
}

function iconUrlOf(type) {
  return `${import.meta.env.BASE_URL}svgs/${iconNameOf(type)}.svg`;
}

function layoutGraph(graph) {
  if (graph.order < 2 || !graph.size) return;
  const order = graph.order;
  const iterations = order > 5000 ? 18 : order > 2500 ? 28 : order > 1200 ? 42 : order > 500 ? 62 : 90;
  forceAtlas2.assign(graph, {
    iterations,
    getEdgeWeight: 'weight',
    settings: {
      ...forceAtlas2.inferSettings(graph),
      barnesHutOptimize: order > 80,
      barnesHutTheta: 0.55,
      gravity: 0.18,
      scalingRatio: order > 2500 ? 18 : order > 1000 ? 14 : 11,
      slowDown: order > 1200 ? 4 : 3,
      linLogMode: true,
      outboundAttractionDistribution: true,
      edgeWeightInfluence: 0.35,
      adjustSizes: true,
    },
  });
}

function constrainCommunitySpans(graph) {
  if (graph.order < 16 || graph.size < 12) return;
  let randomState = 0x6d2b79f5;
  const communities = louvain(graph, {
    getEdgeWeight: null,
    rng: () => {
      randomState = Math.imul(randomState, 1664525) + 1013904223;
      return (randomState >>> 0) / 4294967296;
    },
  });
  const bounds = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
  const centers = new Map();
  const members = new Map();
  graph.forEachNode((node, attributes) => {
    bounds.minX = Math.min(bounds.minX, attributes.x); bounds.maxX = Math.max(bounds.maxX, attributes.x);
    bounds.minY = Math.min(bounds.minY, attributes.y); bounds.maxY = Math.max(bounds.maxY, attributes.y);
    const community = communities[node];
    if (!members.has(community)) members.set(community, []);
    members.get(community).push(node);
    const center = centers.get(community) || { x: 0, y: 0 };
    center.x += attributes.x; center.y += attributes.y;
    centers.set(community, center);
  });
  const limit = Math.max(40, Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY) * 0.58);
  const longestEdges = new Map();
  graph.forEachEdge((edge, attributes, source, target) => {
    if (communities[source] !== communities[target]) return;
    const sourceData = graph.getNodeAttributes(source); const targetData = graph.getNodeAttributes(target);
    const distance = Math.hypot(targetData.x - sourceData.x, targetData.y - sourceData.y);
    longestEdges.set(communities[source], Math.max(longestEdges.get(communities[source]) || 0, distance));
  });
  members.forEach((nodes, community) => {
    const longest = longestEdges.get(community) || 0;
    if (longest <= limit) return;
    const center = centers.get(community);
    center.x /= nodes.length; center.y /= nodes.length;
    const ratio = Math.max(0.28, limit / longest);
    nodes.forEach((node) => {
      const attributes = graph.getNodeAttributes(node);
      graph.mergeNodeAttributes(node, {
        x: center.x + (attributes.x - center.x) * ratio,
        y: center.y + (attributes.y - center.y) * ratio,
      });
    });
  });
}

function computeBetweennessCentrality(graph) {
  if (graph.order <= 900) return betweennessCentrality(graph, { getEdgeWeight: null, normalized: true });

  // Brandes is exact for small maps. For large maps, sample deterministic sources
  // so the UI remains responsive while preserving the centrality ranking.
  const brandes = createUnweightedIndexedBrandes(graph);
  const nodes = brandes.index.nodes;
  const sampleCount = Math.min(128, Math.max(48, Math.round(Math.sqrt(graph.order) * 1.45)));
  const sources = nodes.map((node, index) => ({ index, rank: seededUnit(node, 0x27d4eb2d) }))
    .sort((a, b) => a.rank - b.rank).slice(0, sampleCount).map(({ index }) => index);
  const values = new Float64Array(graph.order);
  sources.forEach((source) => {
    const [stack, predecessors, paths] = brandes(source);
    const dependency = new Float64Array(graph.order);
    while (stack.size) {
      const node = stack.pop();
      const coefficient = (1 + dependency[node]) / paths[node];
      predecessors[node].forEach((predecessor) => {
        dependency[predecessor] += paths[predecessor] * coefficient;
      });
      if (node !== source) values[node] += dependency[node];
    }
  });
  const scale = graph.order > 2 ? graph.order / sources.length / ((graph.order - 1) * (graph.order - 2)) : 0;
  return nodes.reduce((result, node, index) => {
    result[node] = values[index] * scale;
    return result;
  }, {});
}

function scaleNodeSizes(graph) {
  const centralities = computeBetweennessCentrality(graph);
  const nodes = graph.nodes();
  const scores = nodes.map((node) => Math.max(0, Number(centralities[node]) || 0));
  const minScore = Math.min(...scores);
  const maxScore = Math.max(...scores);
  nodes.forEach((node, index) => {
    const ratio = maxScore === minScore ? 0 : (scores[index] - minScore) / (maxScore - minScore);
    graph.mergeNodeAttributes(node, { degree: graph.degree(node), centrality: scores[index], size: 3 + ratio * 27 });
  });
}

function focusNodes(renderer, nodeKeys) {
  const positions = nodeKeys.map((key) => renderer.getNodeDisplayData(key)).filter(Boolean);
  if (!positions.length) return;
  const position = positions.reduce((result, item) => ({ x: result.x + item.x, y: result.y + item.y }), { x: 0, y: 0 });
  renderer.getCamera().animate({
    x: position.x / positions.length,
    y: position.y / positions.length,
    ratio: positions.length > 1 ? Math.min(0.52, 0.22 + positions.length * 0.008) : 0.13,
  }, { duration: 500 });
}

function drawRoundRect(context, x, y, width, height, radius) {
  context.beginPath();
  context.moveTo(x + radius, y);
  context.lineTo(x + width - radius, y);
  context.quadraticCurveTo(x + width, y, x + width, y + radius);
  context.lineTo(x + width, y + height - radius);
  context.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  context.lineTo(x + radius, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - radius);
  context.lineTo(x, y + radius);
  context.quadraticCurveTo(x, y, x + radius, y);
  context.closePath();
}

function drawNodeLabel(context, data, settings) {
  if (!data.label) return;
  const fontSize = settings.labelSize;
  context.font = `${settings.labelWeight} ${fontSize}px ${settings.labelFont}`;
  const width = context.measureText(data.label).width + 8;
  context.fillStyle = 'rgba(255, 255, 255, .82)';
  context.fillRect(data.x + data.size, data.y + fontSize / 3 - 15, width, 20);
  context.fillStyle = '#111';
  context.fillText(data.label, data.x + data.size + 3, data.y + fontSize / 3);
}

function drawNodeHover(context, data, settings) {
  const fontSize = settings.labelSize;
  const subSize = Math.max(9, fontSize - 2);
  const type = normalize(data.entityType) || '未分类';
  context.font = `${settings.labelWeight} ${fontSize}px ${settings.labelFont}`;
  const labelWidth = context.measureText(data.label || '').width;
  context.font = `${settings.labelWeight} ${subSize}px ${settings.labelFont}`;
  const typeWidth = context.measureText(type).width;
  const width = Math.max(labelWidth, typeWidth) + data.size + 20;
  const height = fontSize + subSize + 18;
  const x = data.x;
  const y = data.y - height + 6;
  context.save();
  context.shadowOffsetY = 2;
  context.shadowBlur = 8;
  context.shadowColor = 'rgba(0, 0, 0, .35)';
  context.fillStyle = '#fff';
  drawRoundRect(context, x, y, width, height, 4);
  context.fill();
  context.restore();
  context.font = `${settings.labelWeight} ${subSize}px ${settings.labelFont}`;
  context.fillStyle = data.color;
  context.fillText(type, data.x + data.size + 5, data.y - fontSize - 2);
  context.font = `${settings.labelWeight} ${fontSize}px ${settings.labelFont}`;
  context.fillStyle = '#111';
  context.fillText(data.label || '', data.x + data.size + 5, data.y + fontSize / 3);
}

const SigmaGraphView = forwardRef(function SigmaGraphView({ file, highlight, onEvidence, onHighlightMissing, locating, theme }, ref) {
  const containerRef = useRef(null);
  const rendererRef = useRef(null);
  const graphRef = useRef(null);
  const selectionRef = useRef({ nodes: new Set(), edge: '' });
  const hoverRef = useRef({ node: '', neighbors: new Set() });
  const activeTypesRef = useRef(new Set());
  const handlersRef = useRef({ onEvidence, onHighlightMissing });
  const [reloadToken, setReloadToken] = useState(0);
  const [readyVersion, setReadyVersion] = useState(0);
  const [legend, setLegend] = useState([]);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [mapStats, setMapStats] = useState({ nodes: 0, edges: 0, totalNodes: 0, totalEdges: 0 });
  const [search, setSearch] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [status, setStatus] = useState({ loading: true, error: '' });

  useEffect(() => { handlersRef.current = { onEvidence, onHighlightMissing }; }, [onEvidence, onHighlightMissing]);

  const refreshSelection = (nodes, edge = '') => {
    selectionRef.current = { nodes: new Set(nodes), edge };
    rendererRef.current?.refresh();
  };
  const fit = () => rendererRef.current?.getCamera().animatedReset({ duration: 350 });
  const zoomIn = () => rendererRef.current?.getCamera().animatedZoom({ duration: 220 });
  const zoomOut = () => rendererRef.current?.getCamera().animatedUnzoom({ duration: 220 });

  const applyTypeFilters = (nextTypes) => {
    const graph = graphRef.current;
    const renderer = rendererRef.current;
    if (!graph || !renderer) return;
    activeTypesRef.current = nextTypes;
    let visibleNodes = 0;
    let visibleEdges = 0;
    graph.forEachNode((node, attributes) => {
      const hidden = !nextTypes.has(attributes.entityType);
      graph.setNodeAttribute(node, 'hidden', hidden);
      if (!hidden) visibleNodes += 1;
    });
    graph.forEachEdge((edge, attributes, source, target) => {
      const hidden = graph.getNodeAttribute(source, 'hidden') || graph.getNodeAttribute(target, 'hidden');
      graph.setEdgeAttribute(edge, 'hidden', hidden);
      if (!hidden) visibleEdges += 1;
    });
    setLegend((items) => items.map((item) => ({ ...item, active: nextTypes.has(item.type) })));
    setMapStats((stats) => ({ ...stats, nodes: visibleNodes, edges: visibleEdges }));
    updateSearch(search);
    renderer.refresh();
  };

  const toggleType = (type) => {
    const next = new Set(activeTypesRef.current);
    if (next.has(type)) next.delete(type); else next.add(type);
    applyTypeFilters(next);
  };

  const updateSearch = (value) => {
    const query = normalize(value).toLocaleLowerCase();
    setSearch(value);
    const graph = graphRef.current;
    if (query.length < 2 || !graph) {
      setSearchResults([]);
      return;
    }
    setSearchResults(graph.filterNodes((key, attributes) => !attributes.hidden && normalize(attributes.label).toLocaleLowerCase().startsWith(query))
      .slice(0, 8).map((key) => ({ key, label: graph.getNodeAttribute(key, 'label') })));
  };

  const focusSearchResult = (key) => {
    const graph = graphRef.current;
    const renderer = rendererRef.current;
    if (!graph || !renderer) return;
    graph.setNodeAttribute(key, 'highlighted', true);
    refreshSelection([key]);
    focusNodes(renderer, [key]);
    window.setTimeout(() => graph.setNodeAttribute(key, 'highlighted', false), 700);
    setSearch('');
    setSearchResults([]);
  };

  useImperativeHandle(ref, () => ({ reload: () => setReloadToken((value) => value + 1), fit, zoomIn, zoomOut }), []);

  useEffect(() => {
    let disposed = false;
    let hoverTimer = 0;
    const controller = new AbortController();
    setStatus({ loading: true, error: '' });
    setReadyVersion(0);
    setLegend([]);
    setFiltersOpen(false);
    setMapStats({ nodes: 0, edges: 0, totalNodes: 0, totalEdges: 0 });
    setSearch('');
    setSearchResults([]);
    selectionRef.current = { nodes: new Set(), edge: '' };
    hoverRef.current = { node: '', neighbors: new Set() };

    const render = async () => {
      try {
        const { data } = await api.get(`/graph-data/${encodePathSegment(file.name)}`, { signal: controller.signal });
        if (disposed || !containerRef.current) return;
        const graph = new MultiDirectedGraph();
        const nodes = Array.isArray(data.nodes) ? data.nodes : [];
        const links = Array.isArray(data.links) ? data.links : [];
        const typeGroups = new Map();
        nodes.forEach((node) => {
          const type = normalize(node.entityType) || '未分类';
          if (!typeGroups.has(type)) typeGroups.set(type, []);
          typeGroups.get(type).push(node);
        });
        const sortedGroups = [...typeGroups].map(([type, groupNodes]) => ({ type, nodes: groupNodes }))
          .sort((a, b) => b.nodes.length - a.nodes.length || a.type.localeCompare(b.type, 'zh-CN'));
        const typeColors = new Map(sortedGroups.map(({ type }, index) => [type, NODE_COLORS[index % NODE_COLORS.length]]));
        nodes.forEach((node, index) => {
          const key = normalize(node.id || node.name);
          if (!key || graph.hasNode(key)) return;
          const entityType = normalize(node.entityType) || '未分类';
          graph.addNode(key, {
            ...initialPosition(key, index, nodes.length), label: normalize(node.name || node.id),
            color: typeColors.get(entityType), entityType, image: iconUrlOf(entityType), raw: node,
            size: 5, type: 'image', zIndex: 1, hidden: false,
          });
        });
        links.forEach((link, index) => {
          const source = normalize(link.source);
          const target = normalize(link.target);
          if (!graph.hasNode(source) || !graph.hasNode(target)) return;
          const originalId = normalize(link.id);
          let key = `edge:${originalId || index}`;
          while (graph.hasEdge(key)) key = `${key}:${index}`;
          graph.addDirectedEdgeWithKey(key, source, target, {
            label: normalize(link.relation), color: '#ccc', size: 1,
            weight: Math.max(0.25, Math.min(2, Number(link.weight || link.score || 1) || 1)), originalId, raw: link, hidden: false,
          });
        });
        scaleNodeSizes(graph);
        layoutGraph(graph);
        constrainCommunitySpans(graph);
        const groupedKeys = new Map(sortedGroups.map(({ type }) => [type, graph.filterNodes((key, attributes) => attributes.entityType === type)]));
        const activeTypes = new Set(sortedGroups.map(({ type }) => type));
        activeTypesRef.current = activeTypes;
        setLegend(sortedGroups.map(({ type, nodes: groupNodes }) => ({ type, count: groupNodes.length, color: typeColors.get(type), image: iconUrlOf(type), active: true })));
        setMapStats({ nodes: graph.order, edges: graph.size, totalNodes: graph.order, totalEdges: graph.size });

        const styles = getComputedStyle(document.documentElement);
        const renderer = new Sigma(graph, containerRef.current, {
          allowInvalidContainer: true, enableEdgeEvents: graph.size <= 1400, renderEdgeLabels: false, zIndex: true,
          nodeProgramClasses: { image: NodeTypeImageProgram }, defaultNodeType: 'image', defaultEdgeType: 'arrow',
          hideEdgesOnMove: graph.size > 350, hideLabelsOnMove: true,
          labelColor: { color: '#111' }, edgeLabelColor: { color: styles.getPropertyValue('--muted').trim() || '#666' },
          labelFont: 'Lato, "Noto Sans SC", sans-serif', labelSize: 14, labelWeight: '400',
          edgeLabelSize: 9, edgeLabelWeight: '400', labelRenderedSizeThreshold: 15,
          labelDensity: 0.07, labelGridCellSize: 60,
          stagePadding: 30, minCameraRatio: 0.035, maxCameraRatio: 10,
          defaultDrawNodeLabel: drawNodeLabel, defaultDrawNodeHover: drawNodeHover,
          nodeReducer: (node, attributes) => {
            const selection = selectionRef.current;
            if (selection.nodes.size) return selection.nodes.has(node)
              ? { ...attributes, zIndex: 2, highlighted: true }
              : { ...attributes, label: '', color: '#bbb', image: null, zIndex: 0 };
            const hover = hoverRef.current;
            if (!hover.node) return attributes;
            return node === hover.node || hover.neighbors.has(node)
              ? { ...attributes, zIndex: 1 }
              : { ...attributes, label: '', color: '#bbb', image: null, zIndex: 0, highlighted: false };
          },
          edgeReducer: (edge, attributes) => {
            const selection = selectionRef.current;
            if (selection.nodes.size) return selection.edge === edge || (selection.nodes.has(graph.source(edge)) && selection.nodes.has(graph.target(edge)))
              ? { ...attributes, color: '#e22653', size: Math.max(2.5, attributes.size * 1.8), forceLabel: true }
              : { ...attributes, hidden: true };
            const hovered = hoverRef.current.node;
            if (!hovered) return attributes;
            return graph.hasExtremity(edge, hovered)
              ? { ...attributes, color: graph.getNodeAttribute(hovered, 'color'), size: 3.5 }
              : { ...attributes, hidden: true };
          },
        });
        graphRef.current = graph;
        rendererRef.current = renderer;

        const setHovered = (node = '') => {
          window.clearTimeout(hoverTimer);
          hoverTimer = window.setTimeout(() => {
            if (disposed) return;
            hoverRef.current = node ? { node, neighbors: new Set(graph.neighbors(node)) } : { node: '', neighbors: new Set() };
            renderer.refresh();
          }, 40);
        };
        renderer.on('enterNode', ({ node }) => setHovered(node));
        renderer.on('leaveNode', () => setHovered());
        renderer.on('clickNode', ({ node }) => {
          refreshSelection([node]);
          focusNodes(renderer, [node]);
          const raw = graph.getNodeAttribute(node, 'raw') || {};
          handlersRef.current.onEvidence?.({ kind: 'node', id: normalize(raw.id || node), sourceBlocks: raw.source_blocks || [], entityTerms: [normalize(raw.name || raw.id || node)].filter(Boolean), relationTerms: [] });
        });
        renderer.on('clickEdge', ({ edge }) => {
          const source = graph.source(edge);
          const target = graph.target(edge);
          refreshSelection([source, target], edge);
          focusNodes(renderer, [source, target]);
          const raw = graph.getEdgeAttribute(edge, 'raw') || {};
          handlersRef.current.onEvidence?.({ kind: 'edge', id: normalize(raw.id), sourceBlocks: raw.evidence_blocks || (raw.source_block ? [raw.source_block] : []), entityTerms: [normalize(raw.source), normalize(raw.target)].filter(Boolean), relationTerms: [normalize(raw.relation)].filter(Boolean) });
        });
        renderer.on('clickStage', () => refreshSelection([]));
        setStatus({ loading: false, error: '' });
        setReadyVersion((value) => value + 1);
      } catch (error) {
        if (disposed || error?.code === 'ERR_CANCELED') return;
        setStatus({ loading: false, error: getApiErrorMessage(error, 'Sigma.js 图谱加载失败') });
      }
    };
    render();
    return () => {
      disposed = true;
      controller.abort();
      window.clearTimeout(hoverTimer);
      rendererRef.current?.kill();
      rendererRef.current = null;
      graphRef.current = null;
    };
  }, [file.name, reloadToken, theme]);

  useEffect(() => {
    const graph = graphRef.current;
    const renderer = rendererRef.current;
    if (!readyVersion || !graph || !renderer || !highlight?.id) return;
    const requestedId = normalize(highlight.id);
    const entityTerms = (highlight.citation?.entityTerms || []).map(normalize).filter(Boolean);
    if (!isEdgeKind(highlight.kind)) {
      const node = graph.hasNode(requestedId) ? requestedId : graph.findNode((key, attributes) => entityTerms.includes(normalize(attributes.label))) || '';
      if (!node) return handlersRef.current.onHighlightMissing?.();
      refreshSelection([node]);
      focusNodes(renderer, [node]);
      return;
    }
    const relationTerms = (highlight.citation?.relationTerms || []).map(normalize).filter(Boolean);
    let edge = graph.findEdge((key, attributes) => normalize(attributes.originalId) === requestedId) || '';
    if (!edge) {
      const [sourceHint, targetHint] = entityTerms;
      edge = graph.findEdge((key, attributes, source, target) => (
        (!sourceHint || source === sourceHint || target === sourceHint) && (!targetHint || source === targetHint || target === targetHint)
        && (!relationTerms[0] || normalize(attributes.label) === relationTerms[0])
      )) || '';
    }
    if (!edge) return handlersRef.current.onHighlightMissing?.();
    const source = graph.source(edge);
    const target = graph.target(edge);
    refreshSelection([source, target], edge);
    focusNodes(renderer, [source, target]);
  }, [highlight, readyVersion]);

  const baseName = file.name.replace(/\.[^.]+$/, '');
  return <div className="sigma-graph-view sigma-demo-view">
    <div ref={containerRef} className="sigma-canvas" />
    <header className="sigma-demo-title">
      <h1>A cartography of {baseName}</h1>
      <h2><i>{mapStats.nodes}{mapStats.nodes !== mapStats.totalNodes ? ` / ${mapStats.totalNodes}` : ''} nodes, {mapStats.edges}{mapStats.edges !== mapStats.totalEdges ? ` / ${mapStats.totalEdges}` : ''} edges</i></h2>
    </header>
    <aside className="sigma-demo-panels" aria-label="图谱筛选">
      <div className="sigma-demo-search">
        <Search size={15} />
        <input value={search} onChange={(event) => updateSearch(event.target.value)} placeholder="Search in nodes..." aria-label="搜索节点" />
        {search && <button type="button" onClick={() => updateSearch('')} title="清除搜索" aria-label="清除搜索"><X size={13} /></button>}
        {!!searchResults.length && <div className="sigma-demo-search-results">{searchResults.map((item) => <button type="button" key={item.key} onClick={() => focusSearchResult(item.key)}>{item.label}</button>)}</div>}
      </div>
      <section className={`sigma-demo-panel ${filtersOpen ? 'is-open' : 'is-collapsed'}`}>
        <header><h3>Categories <small>({[...activeTypesRef.current].length} / {legend.length})</small></h3><span><button type="button" onClick={() => setFiltersOpen((value) => !value)} title={filtersOpen ? '收起分类' : '展开分类'} aria-label={filtersOpen ? '收起分类' : '展开分类'} aria-expanded={filtersOpen}>{filtersOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button>{filtersOpen && <><button type="button" onClick={() => applyTypeFilters(new Set(legend.map((item) => item.type)))} title="显示全部类型" aria-label="显示全部类型"><CheckCheck size={14} /></button><button type="button" onClick={() => applyTypeFilters(new Set())} title="隐藏全部类型" aria-label="隐藏全部类型"><CircleOff size={14} /></button></>}</span></header>
        {filtersOpen && <><p>Click a category to show or hide related entities.</p><ul>{legend.map((item) => <li key={item.type}><label><input type="checkbox" checked={item.active} onChange={() => toggleType(item.type)} /><span className="sigma-demo-type-icon" style={{ backgroundColor: item.color, backgroundImage: `url(${item.image})` }} /><span className="sigma-demo-type-label">{item.type}<i><b style={{ width: `${Math.max(4, (item.count / Math.max(...legend.map((entry) => entry.count))) * 100)}%` }} /></i></span><small>{item.count}</small></label></li>)}</ul></>}
      </section>
    </aside>
    <div className="sigma-controls sigma-demo-controls" aria-label="Sigma 图谱控制">
      <button type="button" className="icon-button" onClick={zoomIn} title="放大" aria-label="放大"><Plus size={16} /></button>
      <button type="button" className="icon-button" onClick={zoomOut} title="缩小" aria-label="缩小"><Minus size={16} /></button>
      <button type="button" className="icon-button" onClick={fit} title="适应视图" aria-label="适应视图"><LocateFixed size={16} /></button>
    </div>
    {locating && <div className="locating-skeleton graph-locating-skeleton" aria-label="正在定位图谱引用"><span /><span /><span /></div>}
    {status.loading && <div className="graph-loading"><Network size={28} /><strong>正在绘制知识图谱</strong><span>Sigma.js 正在计算网络布局</span></div>}
    {status.error && <div className="sigma-error"><Network size={25} /><strong>{status.error}</strong><button type="button" className="button secondary" onClick={() => setReloadToken((value) => value + 1)}><RefreshCw size={14} />重试</button></div>}
  </div>;
});

export default SigmaGraphView;
