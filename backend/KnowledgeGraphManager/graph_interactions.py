"""Reusable interaction layer injected into every generated graph page."""

import re
from functools import lru_cache
from html import escape
from pathlib import Path

import pyvis


GRAPH_INTERACTION_TEMPLATE = r"""
<style>
  div.vis-configuration-wrapper,
  div.vis-network div.vis-manipulation,
  div.vis-network div.vis-edit-mode-btn,
  div.vis-network div.vis-close-btn { display: none !important; }

  .graph-floating-panel {
    position: absolute; z-index: 2000; box-sizing: border-box;
    border: 1px solid #e5e7eb; border-radius: 10px;
    background: rgba(255,255,255,.96); box-shadow: 0 5px 20px rgba(15,23,42,.12);
    color: #334155; backdrop-filter: blur(10px); overflow: hidden;
  }
  .graph-panel-header {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    min-height: 34px; padding: 0 8px 0 10px; font-size: 12px; font-weight: 700;
    border-bottom: 1px solid #eef2f7; cursor: default;
  }
  .graph-panel-collapse {
    width: 24px; height: 24px; padding: 0; border: 0; border-radius: 5px;
    background: transparent; color: #64748b; cursor: pointer; font-size: 16px;
  }
  .graph-panel-collapse:hover { background: #f1f5f9; color: #2563eb; }
  .graph-panel-body { padding: 8px; }
  .graph-floating-panel.is-collapsed { width: auto !important; min-width: 112px; }
  .graph-floating-panel.is-collapsed .graph-panel-body { display: none; }
  .graph-floating-panel.is-collapsed .graph-panel-header { border-bottom: 0; }

  .search-panel { top: 8px; left: 8px; width: 268px; }
  .control-panel { top: 8px; right: 8px; width: 250px; }
  .filter-panel { bottom: 8px; left: 8px; width: 268px; }
  .community-directory { right: 8px; bottom: 8px; width: 310px; max-height: min(58vh, 440px); }
  .community-directory .graph-panel-body { overflow: hidden; }

  .graph-text-input, .graph-select {
    box-sizing: border-box; width: 100%; height: 30px; margin-bottom: 6px;
    padding: 4px 8px; border: 1px solid #dbe2ea; border-radius: 6px;
    outline: none; background: #fff; color: #334155; font-size: 11px;
  }
  .graph-text-input:focus, .graph-select:focus { border-color: #3b82f6; box-shadow: 0 0 0 2px #dbeafe; }
  .search-results {
    display: block; max-height: min(38vh, 270px); overflow-y: auto;
    border: 1px solid #eef2f7; border-radius: 6px; background: #fff;
  }
  .search-result-item {
    display: flex; align-items: center; gap: 6px; padding: 6px 7px;
    border-bottom: 1px solid #f1f5f9; cursor: pointer; font-size: 10px;
  }
  .search-result-item:last-child { border-bottom: 0; }
  .search-result-item:hover { background: #eff6ff; color: #1d4ed8; }
  .result-main { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .result-meta { color: #94a3b8; flex: none; }
  .type-badge {
    max-width: 84px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    padding: 2px 5px; border-radius: 10px; background: #dbeafe; color: #1d4ed8; font-size: 9px;
  }
  .type-badge.edge { background: #f3e8ff; color: #7e22ce; }
  .graph-empty-state { padding: 12px 8px; color: #94a3b8; text-align: center; font-size: 11px; }
  .status-bar { margin-top: 6px; color: #94a3b8; font-size: 10px; }
  .status-bar strong { color: #2563eb; }

  .control-actions { display: grid; grid-template-columns: repeat(3, 1fr); gap: 5px; }
  .control-btn, .small-action-btn {
    min-height: 28px; padding: 4px 6px; border: 1px solid #dbe2ea; border-radius: 6px;
    background: #f8fafc; color: #475569; cursor: pointer; font-size: 10px;
  }
  .control-btn:hover, .small-action-btn:hover { border-color: #3b82f6; color: #2563eb; }
  .control-btn.active { border-color: #2563eb; background: #2563eb; color: #fff; }

  .filter-label { display: flex; justify-content: space-between; margin: 2px 0 4px; color: #64748b; font-size: 10px; }
  .filter-slider { width: 100%; accent-color: #2563eb; }
  .filter-section + .filter-section { margin-top: 9px; padding-top: 8px; border-top: 1px solid #eef2f7; }
  .entity-type-actions { display: flex; gap: 5px; margin-bottom: 5px; }
  .entity-type-options { max-height: 142px; overflow-y: auto; border: 1px solid #eef2f7; border-radius: 6px; }
  .entity-type-option {
    display: flex; align-items: center; gap: 6px; padding: 5px 7px;
    border-bottom: 1px solid #f5f7fa; cursor: pointer; color: #475569; font-size: 10px;
  }
  .entity-type-option:last-child { border-bottom: 0; }
  .entity-type-option:hover { background: #f8fafc; }
  .entity-type-option input { accent-color: #2563eb; }
  .entity-type-count { margin-left: auto; color: #94a3b8; }

  .community-list { max-height: min(39vh, 300px); overflow-y: auto; }
  .community-list-item {
    display: block; padding: 8px; border: 1px solid #eef2f7; border-radius: 7px;
    margin-bottom: 6px; color: #334155; text-decoration: none;
  }
  .community-list-item:hover { border-color: #93c5fd; background: #eff6ff; }
  .community-item-name { display: block; font-size: 11px; font-weight: 700; }
  .community-item-meta {
    display: block; overflow: hidden; margin-top: 3px; color: #64748b;
    font-size: 9px; text-overflow: ellipsis; white-space: nowrap;
  }
  .community-back-bar {
    position: fixed; z-index: 1900; right: 10px; bottom: 10px; display: flex; gap: 10px;
    padding: 7px 10px; border: 1px solid #e5e7eb; border-radius: 18px;
    background: rgba(255,255,255,.94); box-shadow: 0 3px 12px rgba(15,23,42,.12);
    color: #64748b; font-size: 10px;
  }
  .community-back-bar a { color: #2563eb; text-decoration: none; }

  .immersive-toggle {
    position: absolute; z-index: 2100; top: 8px; left: 50%; transform: translateX(-50%);
    height: 30px; padding: 0 11px; border: 1px solid #dbe2ea; border-radius: 16px;
    background: rgba(255,255,255,.92); color: #475569; cursor: pointer; font-size: 10px;
    box-shadow: 0 2px 8px rgba(15,23,42,.08);
  }
  .immersive-toggle:hover { border-color: #3b82f6; color: #2563eb; }
  #edge-tooltip, #node-tooltip {
    position: fixed; z-index: 10000; display: none; max-width: 310px;
    padding: 8px 10px; border: 1px solid #e2e8f0; border-radius: 7px;
    background: rgba(255,255,255,.98); color: #334155; font-size: 10px;
    box-shadow: 0 5px 18px rgba(15,23,42,.16);
  }
  #edge-tooltip { pointer-events: none; }
  #node-tooltip { max-height: 260px; overflow-y: auto; pointer-events: auto; }
  #node-tooltip .edge-item { padding: 4px 0; border-bottom: 1px dashed #e5e7eb; }
  #node-tooltip .edge-label { color: #2563eb; font-weight: 600; }
  #node-tooltip .edge-meta { color: #94a3b8; font-size: 9px; }

  @media (max-width: 720px) {
    .search-panel, .filter-panel { width: 230px; }
    .control-panel { width: 220px; }
    .community-directory { width: min(280px, calc(100vw - 16px)); }
  }
</style>
<script>
(function () {
  const NODE_COUNT = __NODE_COUNT__;
  const EDGE_COUNT = __EDGE_COUNT__;
  let searchTimer = null;
  let minimumWeight = 0.5;
  let focusKeepNodes = null;
  let hubsCollapsed = false;
  let immersive = false;
  const activeEntityTypes = new Set();
  const collapsedEdgeIds = new Set();
  const edgeStates = {};
  const edgeOriginalWidths = {};
  const nodeDegrees = {};
  const hubNodes = new Set();

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    })[char]);
  }

  function entityTypeOf(node) {
    return String(node.entityType || node.group || '未分类');
  }

  function initializeGraphMetadata() {
    network.body.data.nodes.get().forEach(node => {
      nodeDegrees[node.id] = network.getConnectedNodes(node.id).length;
    });
    const degrees = Object.values(nodeDegrees).sort((a, b) => b - a);
    const threshold = degrees[Math.floor(degrees.length * 0.2)] || 0;
    Object.entries(nodeDegrees).forEach(([id, degree]) => {
      if (degree >= threshold && degree > 3) hubNodes.add(id);
    });
    network.body.data.edges.get().forEach(edge => {
      edgeStates[edge.id] = { clicked: false, labelVisible: false };
      edgeOriginalWidths[edge.id] = edge.width || 1;
    });
  }

  function nodePassesFilters(node) {
    if (activeEntityTypes.size && !activeEntityTypes.has(entityTypeOf(node))) return false;
    if (focusKeepNodes && !focusKeepNodes.has(node.id)) return false;
    return true;
  }

  function applyVisibilityFilters(fitGraph = false) {
    const visibleNodeIds = new Set();
    const nodeUpdates = network.body.data.nodes.get().map(node => {
      const visible = nodePassesFilters(node);
      if (visible) visibleNodeIds.add(node.id);
      return { ...node, hidden: !visible };
    });
    network.body.data.nodes.update(nodeUpdates);

    const edgeUpdates = network.body.data.edges.get().map(edge => ({
      ...edge,
      hidden: !visibleNodeIds.has(edge.from)
        || !visibleNodeIds.has(edge.to)
        || Number(edge.weight || 0.5) < minimumWeight
        || collapsedEdgeIds.has(edge.id)
    }));
    network.body.data.edges.update(edgeUpdates);
    updateVisibleStatus(visibleNodeIds.size, edgeUpdates.filter(edge => !edge.hidden).length);
    if (fitGraph && visibleNodeIds.size) network.fit({ animation: { duration: 350 } });
  }

  function updateVisibleStatus(nodes, edges) {
    const status = document.getElementById('visibleGraphStatus');
    if (status) status.innerHTML = `<strong>${nodes}</strong> 节点 · <strong>${edges}</strong> 关系`;
  }

  function createPanel(className, title, bodyHtml) {
    const panel = document.createElement('section');
    panel.className = `graph-floating-panel ${className}`;
    panel.innerHTML = `
      <div class="graph-panel-header">
        <span>${title}</span>
        <button class="graph-panel-collapse" type="button" aria-label="收起面板">−</button>
      </div>
      <div class="graph-panel-body">${bodyHtml}</div>`;
    return panel;
  }

  function bindPanelCollapse(panel) {
    const button = panel.querySelector('.graph-panel-collapse');
    if (!button) return;
    button.addEventListener('click', () => {
      const collapsed = panel.classList.toggle('is-collapsed');
      button.textContent = collapsed ? '+' : '−';
      button.setAttribute('aria-label', collapsed ? '展开面板' : '收起面板');
    });
  }

  function renderEntityTypeOptions(container) {
    const counts = new Map();
    network.body.data.nodes.get().forEach(node => {
      const type = entityTypeOf(node);
      counts.set(type, (counts.get(type) || 0) + 1);
    });
    container.innerHTML = [...counts.entries()]
      .sort((a, b) => a[0].localeCompare(b[0], 'zh-CN'))
      .map(([type, count]) => `
        <label class="entity-type-option">
          <input type="checkbox" value="${escapeHtml(type)}">
          <span title="${escapeHtml(type)}">${escapeHtml(type)}</span>
          <span class="entity-type-count">${count}</span>
        </label>`).join('');
    container.querySelectorAll('input[type="checkbox"]').forEach(input => {
      input.addEventListener('change', () => {
        if (input.checked) activeEntityTypes.add(input.value);
        else activeEntityTypes.delete(input.value);
        focusKeepNodes = null;
        document.getElementById('focusModeBtn')?.classList.remove('active');
        applyVisibilityFilters(true);
        renderSearchResults();
      });
    });
  }

  function renderSearchResults() {
    const input = document.getElementById('searchInput');
    const container = document.getElementById('searchResults');
    if (!input || !container) return;
    const term = input.value.toLowerCase().trim();
    const nodes = network.body.data.nodes.get()
      .filter(node => !node.hidden)
      .filter(node => !term || String(node.label || node.id).toLowerCase().includes(term))
      .map(node => ({
        kind: 'node', id: node.id, label: node.label || node.id,
        type: entityTypeOf(node), extra: `${nodeDegrees[node.id] || 0} 连接`
      }));
    const edges = term ? network.body.data.edges.get()
      .filter(edge => !edge.hidden && String(edge.label || '').toLowerCase().includes(term))
      .map(edge => ({
        kind: 'edge', id: edge.id, label: edge.label || '未命名关系',
        type: '关系', extra: Number(edge.weight || .5).toFixed(2)
      })) : [];
    const results = [...nodes, ...edges].slice(0, 80);
    container.innerHTML = results.length ? results.map(result => `
      <div class="search-result-item" data-kind="${result.kind}" data-id="${escapeHtml(result.id)}">
        <span class="type-badge ${result.kind === 'edge' ? 'edge' : ''}" title="${escapeHtml(result.type)}">${escapeHtml(result.type)}</span>
        <span class="result-main" title="${escapeHtml(result.label)}">${escapeHtml(result.label)}</span>
        <span class="result-meta">${escapeHtml(result.extra)}</span>
      </div>`).join('') : '<div class="graph-empty-state">没有匹配的实体或关系</div>';
    container.querySelectorAll('.search-result-item').forEach(item => {
      item.addEventListener('click', () => {
        const id = item.dataset.id;
        if (item.dataset.kind === 'node') {
          const node = network.body.data.nodes.get(id)
            || network.body.data.nodes.get().find(candidate => String(candidate.id) === id);
          if (!node) return;
          network.selectNodes([node.id]);
          network.focus(node.id, { scale: 1.45, animation: { duration: 350 } });
        } else {
          const edge = network.body.data.edges.get(id)
            || network.body.data.edges.get().find(candidate => String(candidate.id) === id);
          if (!edge) return;
          network.selectEdges([edge.id]);
          network.fit({ nodes: [edge.from, edge.to], animation: { duration: 350 } });
        }
      });
    });
  }

  function setupCommunityDirectory() {
    const directory = document.getElementById('communityDirectory');
    if (!directory) return;
    directory.querySelector('.graph-panel-collapse')?.addEventListener('click', event => {
      const collapsed = directory.classList.toggle('is-collapsed');
      event.currentTarget.textContent = collapsed ? '+' : '−';
    });
    const search = document.getElementById('communitySearchInput');
    const typeFilter = document.getElementById('communityTypeFilter');
    const items = [...directory.querySelectorAll('.community-list-item')];
    const empty = document.getElementById('communityEmptyState');
    const apply = () => {
      const term = (search?.value || '').toLowerCase().trim();
      const type = typeFilter?.value || '';
      let visible = 0;
      items.forEach(item => {
        const matchesName = !term || (item.dataset.name || '').toLowerCase().includes(term);
        const types = (item.dataset.types || '').split('|');
        const matchesType = !type || types.includes(type);
        item.hidden = !(matchesName && matchesType);
        if (!item.hidden) visible += 1;
      });
      if (empty) empty.hidden = visible > 0;
    };
    search?.addEventListener('input', apply);
    typeFilter?.addEventListener('change', apply);
  }

  document.addEventListener('DOMContentLoaded', function () {
    const graphContainer = document.getElementById('mynetwork');
    if (!graphContainer || typeof network === 'undefined') return;
    const host = graphContainer.parentNode;
    let readyNotified = false;
    const notifyGraphReady = () => {
      if (readyNotified) return;
      readyNotified = true;
      window.parent?.postMessage({ type: 'knowledge-graph-ready' }, '*');
    };
    network.once('afterDrawing', notifyGraphReady);
    network.once('stabilized', () => {
      network.setOptions({ physics: { enabled: false } });
      notifyGraphReady();
    });
    window.setTimeout(notifyGraphReady, 2500);
    initializeGraphMetadata();

    const searchPanel = createPanel('search-panel', '🔍 实体与关系', `
      <input type="search" id="searchInput" class="graph-text-input" placeholder="搜索实体或关系...">
      <div class="search-results" id="searchResults"></div>
      <div class="status-bar" id="visibleGraphStatus"><strong>${NODE_COUNT}</strong> 节点 · <strong>${EDGE_COUNT}</strong> 关系</div>`);
    host.insertBefore(searchPanel, graphContainer);

    const controlPanel = createPanel('control-panel', '⚙️ 图谱控制', `
      <div class="control-actions">
        <button id="showAllBtn" class="control-btn">显示标签</button>
        <button id="hideAllBtn" class="control-btn active">隐藏标签</button>
        <button id="toggleHubsBtn" class="control-btn">折叠 Hub</button>
        <button id="focusModeBtn" class="control-btn">节点聚焦</button>
        <button id="fitBtn" class="control-btn">适应画布</button>
        <button id="resetBtn" class="control-btn">重置</button>
      </div>
      <div class="status-bar">已标记关系：<strong id="counter">0</strong></div>`);
    host.insertBefore(controlPanel, graphContainer);

    const filterPanel = createPanel('filter-panel', '🔧 筛选与类型聚焦', `
      <div class="filter-section">
        <div class="filter-label"><span>最小关系权重</span><strong id="weightValue">0.5</strong></div>
        <input type="range" id="weightFilter" class="filter-slider" min="0.5" max="1" step="0.1" value="0.5">
      </div>
      <div class="filter-section">
        <div class="filter-label"><span>Hub 关系透明度</span><strong id="hubOpacityValue">0.3</strong></div>
        <input type="range" id="hubOpacity" class="filter-slider" min="0" max="1" step="0.1" value="0.3">
      </div>
      <div class="filter-section">
        <div class="filter-label"><span>实体类型（可多选）</span><strong id="selectedTypeCount">0</strong></div>
        <div class="entity-type-actions">
          <button type="button" id="selectAllTypesBtn" class="small-action-btn">全选</button>
          <button type="button" id="clearTypesBtn" class="small-action-btn">清除</button>
        </div>
        <div class="entity-type-options" id="entityTypeOptions"></div>
      </div>`);
    host.insertBefore(filterPanel, graphContainer);

    [searchPanel, controlPanel, filterPanel].forEach(bindPanelCollapse);

    const immersiveButton = document.createElement('button');
    immersiveButton.className = 'immersive-toggle';
    immersiveButton.type = 'button';
    immersiveButton.textContent = '⛶ 沉浸模式';
    immersiveButton.addEventListener('click', () => {
      immersive = !immersive;
      document.querySelectorAll('.graph-floating-panel').forEach(panel => {
        panel.classList.toggle('is-collapsed', immersive);
        const button = panel.querySelector('.graph-panel-collapse');
        if (button) button.textContent = immersive ? '+' : '−';
      });
      immersiveButton.textContent = immersive ? '退出沉浸' : '⛶ 沉浸模式';
    });
    host.insertBefore(immersiveButton, graphContainer);

    const typeOptions = document.getElementById('entityTypeOptions');
    renderEntityTypeOptions(typeOptions);
    const updateSelectedTypeCount = () => {
      document.getElementById('selectedTypeCount').textContent = activeEntityTypes.size;
    };
    typeOptions.addEventListener('change', updateSelectedTypeCount);
    document.getElementById('selectAllTypesBtn').addEventListener('click', () => {
      typeOptions.querySelectorAll('input').forEach(input => { input.checked = true; activeEntityTypes.add(input.value); });
      updateSelectedTypeCount(); applyVisibilityFilters(true); renderSearchResults();
    });
    document.getElementById('clearTypesBtn').addEventListener('click', () => {
      typeOptions.querySelectorAll('input').forEach(input => { input.checked = false; });
      activeEntityTypes.clear(); updateSelectedTypeCount(); applyVisibilityFilters(true); renderSearchResults();
    });

    document.getElementById('searchInput').addEventListener('input', () => {
      clearTimeout(searchTimer); searchTimer = setTimeout(renderSearchResults, 120);
    });
    document.getElementById('weightFilter').addEventListener('input', event => {
      minimumWeight = Number(event.target.value);
      document.getElementById('weightValue').textContent = minimumWeight.toFixed(1);
      applyVisibilityFilters(); renderSearchResults();
    });
    document.getElementById('hubOpacity').addEventListener('input', event => {
      const opacity = Number(event.target.value);
      document.getElementById('hubOpacityValue').textContent = opacity.toFixed(1);
      const updates = network.body.data.edges.get()
        .filter(edge => hubNodes.has(String(edge.from)) || hubNodes.has(String(edge.to)))
        .map(edge => ({ ...edge, color: { ...edge.color, opacity } }));
      network.body.data.edges.update(updates);
    });

    const updateCounter = () => {
      document.getElementById('counter').textContent = Object.values(edgeStates).filter(state => state.clicked).length;
    };
    document.getElementById('showAllBtn').addEventListener('click', event => {
      network.body.data.edges.get().forEach(edge => {
        edge.font = { size: 10, color: '#64748b' }; edgeStates[edge.id].labelVisible = true;
        network.body.data.edges.update(edge);
      });
      document.getElementById('hideAllBtn').classList.remove('active'); event.currentTarget.classList.add('active');
    });
    document.getElementById('hideAllBtn').addEventListener('click', event => {
      network.body.data.edges.get().forEach(edge => {
        if (!edgeStates[edge.id].clicked) edge.font = { size: 0 };
        edgeStates[edge.id].labelVisible = false; network.body.data.edges.update(edge);
      });
      document.getElementById('showAllBtn').classList.remove('active'); event.currentTarget.classList.add('active');
    });
    document.getElementById('toggleHubsBtn').addEventListener('click', event => {
      hubsCollapsed = !hubsCollapsed; collapsedEdgeIds.clear();
      if (hubsCollapsed) hubNodes.forEach(hubId => {
        network.body.data.edges.get().filter(edge => String(edge.from) === hubId || String(edge.to) === hubId)
          .sort((a, b) => Number(b.weight || 0) - Number(a.weight || 0)).slice(3)
          .forEach(edge => collapsedEdgeIds.add(edge.id));
      });
      event.currentTarget.classList.toggle('active', hubsCollapsed); applyVisibilityFilters();
    });
    document.getElementById('focusModeBtn').addEventListener('click', event => {
      if (focusKeepNodes) {
        focusKeepNodes = null; event.currentTarget.classList.remove('active'); applyVisibilityFilters(true); return;
      }
      const selected = network.getSelectedNodes();
      if (!selected.length) { alert('请先选中一个或多个节点'); return; }
      focusKeepNodes = new Set(selected);
      selected.forEach(id => network.getConnectedNodes(id).forEach(neighbor => focusKeepNodes.add(neighbor)));
      event.currentTarget.classList.add('active'); applyVisibilityFilters(true);
    });
    document.getElementById('fitBtn').addEventListener('click', () => network.fit({ animation: { duration: 350 } }));
    document.getElementById('resetBtn').addEventListener('click', () => {
      activeEntityTypes.clear(); collapsedEdgeIds.clear(); focusKeepNodes = null; hubsCollapsed = false; minimumWeight = .5;
      typeOptions.querySelectorAll('input').forEach(input => { input.checked = false; });
      document.getElementById('weightFilter').value = .5; document.getElementById('weightValue').textContent = '0.5';
      document.getElementById('searchInput').value = ''; document.getElementById('focusModeBtn').classList.remove('active');
      document.getElementById('toggleHubsBtn').classList.remove('active'); updateSelectedTypeCount();
      network.body.data.edges.get().forEach(edge => {
        edge.font = { size: 0 }; edge.width = edgeOriginalWidths[edge.id]; edgeStates[edge.id] = { clicked: false, labelVisible: false };
        network.body.data.edges.update(edge);
      });
      applyVisibilityFilters(true); renderSearchResults(); updateCounter();
    });

    network.on('selectEdge', params => {
      if (!params.edges.length) return;
      const edge = network.body.data.edges.get(params.edges[0]);
      edgeStates[edge.id].clicked = true; edge.font = { size: 10, color: '#2563eb' };
      network.body.data.edges.update(edge); updateCounter();
    });
    network.on('hoverEdge', params => {
      const edge = network.body.data.edges.get(params.edge);
      let tooltip = document.getElementById('edge-tooltip');
      if (!tooltip) { tooltip = document.createElement('div'); tooltip.id = 'edge-tooltip'; document.body.appendChild(tooltip); }
      tooltip.innerHTML = `<strong>${escapeHtml(edge.label || '未命名关系')}</strong><div>${escapeHtml(edge.title || '无描述')}</div>`;
      tooltip.style.left = `${(params.event?.clientX || 80) + 12}px`; tooltip.style.top = `${(params.event?.clientY || 80) + 12}px`; tooltip.style.display = 'block';
    });
    network.on('blurEdge', () => { const tip = document.getElementById('edge-tooltip'); if (tip) tip.style.display = 'none'; });
    network.on('hoverNode', params => {
      let tooltip = document.getElementById('node-tooltip');
      if (!tooltip) { tooltip = document.createElement('div'); tooltip.id = 'node-tooltip'; document.body.appendChild(tooltip); }
      const edges = network.getConnectedEdges(params.node).slice(0, 30).map(id => network.body.data.edges.get(id));
      tooltip.innerHTML = `<strong>${escapeHtml(network.body.data.nodes.get(params.node)?.label || params.node)}</strong>`
        + edges.map(edge => `<div class="edge-item"><div class="edge-label">${escapeHtml(edge.label || '关系')}</div><div class="edge-meta">${escapeHtml(edge.from)} → ${escapeHtml(edge.to)}</div></div>`).join('');
      tooltip.style.left = `${(params.event?.clientX || 80) + 12}px`; tooltip.style.top = `${(params.event?.clientY || 80) + 12}px`; tooltip.style.display = 'block';
    });
    network.on('blurNode', () => { const tip = document.getElementById('node-tooltip'); if (tip) tip.style.display = 'none'; });

    setupCommunityDirectory();
    applyVisibilityFilters(); renderSearchResults(); updateCounter();
  });
})();
</script>
"""


def build_graph_interaction_html(node_count: int, edge_count: int) -> str:
    """Build the static interaction layer with escaped numeric counters."""
    return (
        GRAPH_INTERACTION_TEMPLATE
        .replace("__NODE_COUNT__", escape(str(int(node_count))))
        .replace("__EDGE_COUNT__", escape(str(int(edge_count))))
    )


@lru_cache(maxsize=1)
def _local_vis_assets() -> tuple[str, str]:
    """Load the installed PyVis assets once for legacy graph responses."""
    asset_root = Path(pyvis.__file__).resolve().parent / "templates" / "lib" / "vis-9.1.2"
    return (
        (asset_root / "vis-network.css").read_text(encoding="utf-8"),
        (asset_root / "vis-network.min.js").read_text(encoding="utf-8"),
    )


def get_local_vis_asset_path(asset_name: str) -> Path:
    """Resolve one allow-listed browser asset shipped by PyVis."""
    allowed = {"vis-network.css", "vis-network.min.js"}
    if asset_name not in allowed:
        raise ValueError("不支持的图谱资源")
    return (
        Path(pyvis.__file__).resolve().parent
        / "templates" / "lib" / "vis-9.1.2" / asset_name
    )


def prepare_legacy_graph_html(
    html_content: str,
    asset_base_url: str | None = None,
) -> str:
    """Make older CDN-based graph pages local and notify the parent on first draw."""
    if "cdnjs.cloudflare.com/ajax/libs/vis-network/" in html_content:
        if asset_base_url:
            base_url = asset_base_url.rstrip("/")
            css_replacement = f'<link rel="stylesheet" href="{base_url}/vis-network.css">'
            js_replacement = f'<script src="{base_url}/vis-network.min.js"></script>'
        else:
            vis_css, vis_js = _local_vis_assets()
            css_replacement = f"<style>{vis_css}</style>"
            js_replacement = f"<script>{vis_js}</script>"
        html_content = re.sub(
            r'<link\b[^>]*href="https://cdnjs\.cloudflare\.com/ajax/libs/vis-network/[^\"]+"[^>]*>',
            lambda _match: css_replacement,
            html_content,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
        html_content = re.sub(
            r'<script\b[^>]*src="https://cdnjs\.cloudflare\.com/ajax/libs/vis-network/[^\"]+"[^>]*>\s*</script>',
            lambda _match: js_replacement,
            html_content,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )

    if "cdn.jsdelivr.net/npm/bootstrap@" in html_content:
        html_content = re.sub(
            r'\s*<link\b[^>]*href="https://cdn\.jsdelivr\.net/npm/bootstrap@[^\"]+"[^>]*>',
            '',
            html_content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        html_content = re.sub(
            r'\s*<script\b[^>]*src="https://cdn\.jsdelivr\.net/npm/bootstrap@[^\"]+"[^>]*>\s*</script>',
            '',
            html_content,
            flags=re.IGNORECASE | re.DOTALL,
        )

    iteration_targets = {300: 120, 400: 180, 500: 220}
    html_content = re.sub(
        r'("stabilization"\s*:\s*\{[^{}]*?"iterations"\s*:\s*)(300|400|500)',
        lambda match: match.group(1) + str(iteration_targets[int(match.group(2))]),
        html_content,
    )

    if "knowledge-graph-ready" not in html_content:
        ready_script = r"""
<script>
document.addEventListener('DOMContentLoaded', function () {
  let notified = false;
  const ready = () => {
    if (notified) return;
    notified = true;
    window.parent?.postMessage({ type: 'knowledge-graph-ready' }, '*');
  };
  if (typeof network !== 'undefined') {
    network.once('afterDrawing', ready);
    network.once('stabilized', () => {
      network.setOptions({ physics: { enabled: false } });
      ready();
    });
  }
  window.setTimeout(ready, 1200);
});
</script>
"""
        html_content = html_content.replace("</body>", ready_script + "</body>")
    return html_content
