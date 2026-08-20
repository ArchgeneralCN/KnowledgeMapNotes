"""Reusable interaction layer injected into every generated graph page."""

import re
import json
from functools import lru_cache
from html import escape
from pathlib import Path

import pyvis


GRAPH_EDITOR_VERSION = 7


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
    margin-bottom: 6px; color: #334155;
  }
  .community-list-item:hover { border-color: #93c5fd; background: #eff6ff; }
  .community-list-item.search-match { border-color: #60a5fa; background: #eff6ff; }
  .community-list-item.is-loading { opacity: .68; }
  .community-item-link { display: block; color: #334155; text-decoration: none; }
  .community-item-name { display: block; font-size: 11px; font-weight: 700; }
  .community-item-meta {
    display: block; overflow: hidden; margin-top: 3px; color: #64748b;
    font-size: 9px; text-overflow: ellipsis; white-space: nowrap;
  }
  .community-source-link {
    margin-top: 6px; padding: 3px 6px; border: 1px solid #bfdbfe; border-radius: 5px;
    background: #eff6ff; color: #2563eb; cursor: pointer; font-size: 9px;
  }
  .community-source-link:hover { background: #dbeafe; border-color: #60a5fa; }
  .community-back-bar {
    position: fixed; z-index: 2050; right: 10px; bottom: 10px; display: flex; gap: 10px;
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
  .graph-context-menu {
    position: fixed; z-index: 12000; display: none; min-width: 150px;
    padding: 4px; border: 1px solid #dbe2ea; border-radius: 8px;
    background: rgba(255,255,255,.98); box-shadow: 0 8px 24px rgba(15,23,42,.18);
  }
  .graph-context-menu button {
    display: block; width: 100%; padding: 7px 9px; border: 0; border-radius: 5px;
    background: transparent; color: #334155; text-align: left; cursor: pointer; font-size: 11px;
  }
  .graph-context-menu button:hover { background: #eff6ff; color: #1d4ed8; }
  .graph-context-menu button.danger:hover { background: #fef2f2; color: #dc2626; }
  .graph-editor-dialog-mask {
    position: fixed; z-index: 13000; inset: 0; display: flex; align-items: center; justify-content: center;
    padding: 16px; background: rgba(15,23,42,.42);
  }
  .graph-editor-dialog {
    width: min(560px, calc(100vw - 32px)); max-height: min(88vh, 720px); overflow-y: auto;
    box-sizing: border-box; padding: 16px; border-radius: 10px; background: #fff;
    color: #334155; box-shadow: 0 18px 50px rgba(15,23,42,.3); font-size: 12px;
  }
  .graph-editor-dialog h3 { margin: 0 0 14px; font-size: 15px; color: #0f172a; }
  .graph-editor-field { margin-bottom: 10px; }
  .graph-editor-field label { display: block; margin-bottom: 4px; color: #64748b; font-weight: 600; }
  .graph-editor-field input, .graph-editor-field textarea {
    box-sizing: border-box; width: 100%; padding: 7px 8px; border: 1px solid #dbe2ea;
    border-radius: 6px; outline: none; color: #334155; background: #fff; font: inherit;
  }
  .graph-editor-field textarea { min-height: 96px; resize: vertical; }
  .graph-editor-field input:focus, .graph-editor-field textarea:focus { border-color: #3b82f6; box-shadow: 0 0 0 2px #dbeafe; }
  .graph-editor-field input[readonly], .graph-editor-field textarea[readonly] { background: #f8fafc; }
  .graph-editor-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
  .graph-editor-actions button { padding: 7px 13px; border: 1px solid #dbe2ea; border-radius: 6px; background: #f8fafc; color: #475569; cursor: pointer; }
  .graph-editor-actions button.primary { border-color: #2563eb; background: #2563eb; color: #fff; }
  .graph-editor-actions button:hover { filter: brightness(.97); }

  @media (max-width: 720px) {
    .graph-floating-panel { max-height: calc(50% - 18px); overflow: auto; }
    .search-panel, .filter-panel { left: 8px; width: calc(50% - 12px); }
    .control-panel, .community-directory { right: 8px; width: calc(50% - 12px); }
    .control-panel { top: 8px; }
    .community-directory { bottom: 8px; max-height: calc(50% - 18px); }
    .graph-panel-body { min-width: 0; }
    .control-actions { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
</style>
<script>
(function () {
  const GRAPH_EDITOR_VERSION = __GRAPH_EDITOR_VERSION__;
  const NODE_COUNT = __NODE_COUNT__;
  const EDGE_COUNT = __EDGE_COUNT__;
  const GRAPH_NAME = __GRAPH_NAME__;
  const GRAPH_STATIC_LAYOUT_VERSION = __GRAPH_STATIC_LAYOUT_VERSION__;
  let searchTimer = null;
  let minimumWeight = 0.5;
  let focusKeepNodes = null;
  let hubsCollapsed = false;
  let immersive = true;
  const activeEntityTypes = new Set();
  const collapsedEdgeIds = new Set();
  const edgeStates = {};
  const edgeOriginalWidths = {};
  const nodeDegrees = {};
  const hubNodes = new Set();
  let editorRevision = 0;
  let contextTarget = { type: 'canvas', id: null };
  let contextMenu = null;
  const edgeApiIds = new Map();
  const edgeDetails = new Map();
  const nodeDetails = new Map();
  let editorMetadataReady = Promise.resolve();

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    })[char]);
  }

  function entityTypeOf(node) {
    return String(node.entityType || node.group || '未分类');
  }

  function normalizeCommunitySearchText(value) {
    return String(value || '').normalize('NFKC').toLocaleLowerCase('zh-CN')
      .replace(/[\s.,，。！？!?、:：;；'"“”‘’()[\]{}<>《》【】_+*\/\\|@#$%^&=~`·-]+/g, '');
  }

  function fuzzyCommunityNameScore(name, query) {
    const normalizedName = normalizeCommunitySearchText(name);
    const normalizedQuery = normalizeCommunitySearchText(query);
    if (!normalizedQuery) return 0;
    if (normalizedName === normalizedQuery) return 1000;
    if (normalizedName.startsWith(normalizedQuery)) return 900 - normalizedName.length;
    const substringIndex = normalizedName.indexOf(normalizedQuery);
    if (substringIndex >= 0) return 800 - substringIndex;
    let queryIndex = 0;
    let firstMatch = -1;
    let lastMatch = -1;
    let nameIndex = 0;
    for (const character of normalizedName) {
      if (character === normalizedQuery[queryIndex]) {
        if (firstMatch < 0) firstMatch = nameIndex;
        lastMatch = nameIndex;
        queryIndex += 1;
      }
      if (queryIndex === normalizedQuery.length) {
        return 600 - (lastMatch - firstMatch) - firstMatch;
      }
      nameIndex += 1;
    }
    return -1;
  }

  function communitySearchRank(item, query) {
    const representative = item.dataset.representativeNode || item.dataset.name || '';
    const communityName = item.dataset.communityName || '';
    let memberNames = [];
    try {
      memberNames = JSON.parse(item.dataset.memberNames || '[]');
    } catch (error) {
      console.warn('社区节点名列表格式无效:', error);
    }
    const primaryScore = Math.max(
      fuzzyCommunityNameScore(representative, query),
      fuzzyCommunityNameScore(communityName, query)
    );
    const memberScore = memberNames.reduce((best, name) =>
      Math.max(best, fuzzyCommunityNameScore(name, query)), -1);
    if (primaryScore >= 0) return 2000 + primaryScore;
    if (memberScore >= 0) return 1000 + memberScore;
    return -1;
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

  function moveLegacyIsolatedNodesOutside() {
    const nodes = network.body.data.nodes.get();
    const isolated = nodes.filter(node => network.getConnectedNodes(node.id).length === 0);
    const connected = nodes.filter(node => network.getConnectedNodes(node.id).length > 0);
    if (!isolated.length) return;
    // A graph can consist entirely of isolated nodes. Use all current
    // positions only to choose a stable center, then place every node on rings.
    const referenceNodes = connected.length ? connected : nodes;
    const connectedPositions = network.getPositions(referenceNodes.map(node => node.id));
    const values = Object.values(connectedPositions).filter(position =>
      Number.isFinite(position?.x) && Number.isFinite(position?.y)
    );
    const centerX = values.length
      ? values.reduce((sum, position) => sum + position.x, 0) / values.length
      : 0;
    const centerY = values.length
      ? values.reduce((sum, position) => sum + position.y, 0) / values.length
      : 0;
    const connectedRadius = connected.length && values.length
      ? Math.max(...values.map(position =>
        Math.hypot(position.x - centerX, position.y - centerY)
      ))
      : 0;
    const ringSpacing = 180;
    const radius = Math.max(connectedRadius + 260, 360);
    const updates = [];
    let offset = 0;
    let ringIndex = 0;
    while (offset < isolated.length) {
      const ringRadius = radius + ringIndex * ringSpacing;
      const capacity = Math.max(8, Math.floor(2 * Math.PI * ringRadius / ringSpacing));
      const ringNodes = isolated.slice(offset, offset + capacity);
      ringNodes.forEach((node, index) => {
        const angle = 2 * Math.PI * index / ringNodes.length - Math.PI / 2;
        updates.push({
          id: node.id,
          x: centerX + ringRadius * Math.cos(angle),
          y: centerY + ringRadius * Math.sin(angle)
        });
      });
      offset += ringNodes.length;
      ringIndex += 1;
    }
    network.body.data.nodes.update(updates);
  }

  function prepareLegacyStaticForceLayout(nodeCount) {
    const graphContainer = document.getElementById('mynetwork');
    if (!graphContainer) return false;
    // Keep degree-zero nodes out of the hidden ForceAtlas2 run. They are
    // positioned after the related graph has stabilized, on the outer rings.
    const isolatedNodes = network.body.data.nodes.get().filter(node =>
      network.getConnectedNodes(node.id).length === 0
    );
    if (isolatedNodes.length) {
      network.body.data.nodes.update(isolatedNodes.map(node => ({
        id: node.id,
        physics: false
      })));
    }
    graphContainer.style.visibility = 'hidden';
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      moveLegacyIsolatedNodesOutside();
      network.setOptions({ physics: { enabled: false } });
      graphContainer.style.visibility = 'visible';
      updateVisibleStatus(nodeCount, network.body.data.edges.get().length);
      network.fit({ animation: false });
    };
    network.once('stabilized', finish);
    network.setOptions({
      physics: {
        enabled: true,
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: -80,
          centralGravity: 0.01,
          springLength: 200,
          springConstant: 0.08,
          damping: 0.4,
          avoidOverlap: 1.0
        },
        stabilization: {
          enabled: true,
          iterations: nodeCount > 500 ? 50 : 80,
          updateInterval: 25,
          fit: true
        }
      },
      layout: { improvedLayout: true }
    });
    network.stabilize(nodeCount > 500 ? 50 : 80);
    window.setTimeout(finish, 5000);
    return true;
  }

  function applyLargeGraphPerformance() {
    const nodes = network.body?.data?.nodes?.get?.() || [];
    const edges = network.body?.data?.edges?.get?.() || [];
    const hasIsolatedNodes = nodes.some(node => network.getConnectedNodes(node.id).length === 0);
    if (nodes.length <= 50 && !hasIsolatedNodes) return false;

    // Newly generated pages already contain server-side ForceAtlas2 coordinates.
    // Legacy pages are stabilized while hidden, then physics is disabled before
    // they are shown, so users do not see the original continuous bouncing.
    network.setOptions({
      physics: { enabled: false, stabilization: { enabled: false } },
      layout: { improvedLayout: false },
      interaction: {
        dragNodes: true, dragView: true, zoomView: true,
        hideEdgesOnDrag: true
      }
    });
    const hasCoordinates = nodes.length > 0 && nodes.every(node =>
      Number.isFinite(Number(node.x)) && Number.isFinite(Number(node.y))
    );
    if (GRAPH_STATIC_LAYOUT_VERSION < 2 || !hasCoordinates) {
      prepareLegacyStaticForceLayout(nodes.length);
    }
    updateVisibleStatus(nodes.length, edges.length);
    network.fit({ animation: false });
    return true;
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
      delete panel.dataset.autoCollapsed;
      syncPanelCollapseButton(panel, collapsed);
    });
  }

  function syncPanelCollapseButton(panel, collapsed = panel.classList.contains('is-collapsed')) {
    const button = panel.querySelector('.graph-panel-collapse');
    if (!button) return;
    button.textContent = collapsed ? '+' : '−';
    button.setAttribute('aria-label', collapsed ? '展开面板' : '收起面板');
  }

  function applyDefaultImmersivePanels() {
    document.querySelectorAll('.graph-floating-panel').forEach(panel => {
      if (panel.classList.contains('community-directory')) {
        syncPanelCollapseButton(panel);
        return;
      }
      panel.classList.add('is-collapsed');
      panel.dataset.immersiveCollapsed = '1';
      syncPanelCollapseButton(panel, true);
    });
  }

  function setupResponsivePanels(host, graphContainer) {
    const compactWidth = 720;
    const apply = (forceExpand = false) => {
      const width = graphContainer.getBoundingClientRect().width || window.innerWidth;
      const compact = width < compactWidth;
      document.querySelectorAll('.graph-floating-panel').forEach(panel => {
        if (panel.classList.contains('community-directory')) {
          if (panel.dataset.autoCollapsed === '1' || panel.dataset.immersiveCollapsed === '1') {
            panel.classList.remove('is-collapsed');
            delete panel.dataset.autoCollapsed;
            delete panel.dataset.immersiveCollapsed;
          }
          syncPanelCollapseButton(panel);
          return;
        }
        if (forceExpand && (
          panel.dataset.autoCollapsed === '1' || panel.dataset.immersiveCollapsed === '1'
        )) {
          panel.classList.remove('is-collapsed');
          delete panel.dataset.autoCollapsed;
          delete panel.dataset.immersiveCollapsed;
        } else if (compact && immersive) {
          if (!panel.classList.contains('is-collapsed')) {
            panel.classList.add('is-collapsed');
            panel.dataset.autoCollapsed = '1';
          }
        } else if (!immersive && panel.dataset.autoCollapsed === '1') {
          panel.classList.remove('is-collapsed');
          delete panel.dataset.autoCollapsed;
        }
        syncPanelCollapseButton(panel);
      });
    };
    if (typeof ResizeObserver === 'function') {
      const observer = new ResizeObserver(() => apply());
      observer.observe(host);
    } else {
      window.addEventListener('resize', apply);
    }
    apply();
    return apply;
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
          requestEvidence('node', node.id);
        } else {
          const edge = network.body.data.edges.get(id)
            || network.body.data.edges.get().find(candidate => String(candidate.id) === id);
          if (!edge) return;
          network.selectEdges([edge.id]);
          network.fit({ nodes: [edge.from, edge.to], animation: { duration: 350 } });
          requestEvidence('edge', edge.id);
        }
      });
    });
  }

  function bindCommunitySourceButton(button) {
    if (!button || button.dataset.bound === '1') return;
    button.dataset.bound = '1';
    button.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      let sourceBlocks = [];
      try {
        sourceBlocks = JSON.parse(button.dataset.sourceBlocks || '[]');
      } catch (error) {
        console.warn('社区主节点出处文本块格式无效:', error);
      }
      window.parent?.postMessage({
        type: 'knowledge-graph-evidence',
        graphName: GRAPH_NAME,
        kind: 'node',
        id: button.dataset.nodeId || '',
        sourceBlocks,
        entityTerms: [button.dataset.nodeId || ''].filter(Boolean),
        relationTerms: []
      }, '*');
    });
  }

  function refreshCommunityMetadata() {
    const directory = document.getElementById('communityDirectory');
    if (!directory || !nodeDetails.size) return;
    const findNodeDetail = label => nodeDetails.get(String(label))
      || [...nodeDetails.values()].find(node => String(node.name || node.id) === String(label));
    const types = new Set();
    directory.querySelectorAll('.community-list-item').forEach(item => {
      const representative = item.dataset.representativeNode || item.dataset.name || '';
      const detail = findNodeDetail(representative);
      if (!detail) return;
      const type = String(detail.entityType || '未分类');
      types.add(type);
      item.dataset.types = type;
      const meta = item.querySelector('.community-item-meta');
      if (meta) {
        const count = (meta.textContent.match(/\d+/) || [''])[0];
        meta.textContent = `${count ? `${count} 个节点 · ` : ''}主节点类型：${type}`;
      }
      let sourceButton = item.querySelector('.community-source-link');
      if (!sourceButton) {
        sourceButton = document.createElement('button');
        sourceButton.type = 'button';
        sourceButton.className = 'community-source-link';
        sourceButton.textContent = '查看原文文本块';
        item.appendChild(sourceButton);
      }
      sourceButton.dataset.nodeId = String(detail.id);
      const detailSourceBlocks = Array.isArray(detail.source_blocks) ? detail.source_blocks : [];
      if (detailSourceBlocks.length) {
        sourceButton.dataset.sourceBlocks = JSON.stringify(detailSourceBlocks);
      }
      bindCommunitySourceButton(sourceButton);
    });
    const typeFilter = document.getElementById('communityTypeFilter');
    if (typeFilter && types.size) {
      typeFilter.innerHTML = '<option value="">全部实体类型</option>'
        + [...types].sort((a, b) => a.localeCompare(b, 'zh-CN'))
          .map(type => `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`).join('');
    }
    const communityNodes = network.body.data.nodes.get().map(node => {
      const detail = findNodeDetail(node.label || node.id);
      return detail ? {
        ...node,
        entityType: detail.entityType || '未分类',
        group: detail.entityType || '未分类',
        source_blocks: detail.source_blocks?.length ? detail.source_blocks : (node.source_blocks || [])
      } : node;
    });
    network.body.data.nodes.update(communityNodes);
    const typeOptions = document.getElementById('entityTypeOptions');
    if (typeOptions) renderEntityTypeOptions(typeOptions);
    applyVisibilityFilters();
    renderSearchResults();
  }

  function setupCommunityDirectory() {
    const directory = document.getElementById('communityDirectory');
    if (!directory) return;
    bindPanelCollapse(directory);
    const search = document.getElementById('communitySearchInput');
    const typeFilter = document.getElementById('communityTypeFilter');
    const list = document.getElementById('communityList');
    const items = [...directory.querySelectorAll('.community-list-item')];
    const originalOrder = new Map(items.map((item, index) => [item, index]));
    const empty = document.getElementById('communityEmptyState');
    directory.querySelectorAll('.community-source-link').forEach(bindCommunitySourceButton);
    directory.querySelectorAll('.community-item-link').forEach(link => {
      link.addEventListener('click', () => {
        const item = link.closest('.community-list-item');
        item?.classList.add('is-loading');
        const meta = item?.querySelector('.community-item-meta');
        if (meta) meta.textContent = '正在加载社区子图...';
      });
    });
    editorMetadataReady.then(refreshCommunityMetadata);
    const apply = () => {
      const term = (search?.value || '').toLowerCase().trim();
      const type = typeFilter?.value || '';
      const rankedItems = [];
      items.forEach(item => {
        const rank = term ? communitySearchRank(item, term) : 0;
        const types = (item.dataset.types || '').split('|');
        const matchesType = !type || types.includes(type);
        item.hidden = !matchesType;
        item.classList.toggle('search-match', Boolean(term) && rank >= 0 && matchesType);
        rankedItems.push({ item, rank: matchesType ? rank : -1 });
      });
      rankedItems.sort((left, right) =>
        right.rank - left.rank
        || originalOrder.get(left.item) - originalOrder.get(right.item));
      rankedItems.forEach(({ item }) => list?.appendChild(item));
      const matchedCount = term
        ? rankedItems.filter(({ item, rank }) => !item.hidden && rank >= 0).length
        : rankedItems.filter(({ item }) => !item.hidden).length;
      if (empty) empty.hidden = matchedCount > 0;
    };
    search?.addEventListener('input', apply);
    typeFilter?.addEventListener('change', apply);
  }

  function editorApi(path, options = {}) {
    return fetch(`/api${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
    }).then(async response => {
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || payload.error || '图谱操作失败');
      return payload;
    });
  }

  function edgeSignature(edge) {
    return [edge.from, edge.to, edge.label || '', edge.title || ''].join('|');
  }

  function syncEditorRevision() {
    if (!GRAPH_NAME) return Promise.resolve();
    return editorApi(`/graph-data/${encodeURIComponent(GRAPH_NAME)}`)
      .then(payload => {
        editorRevision = Number(payload.revision || 0);
        nodeDetails.clear();
        edgeApiIds.clear();
        (payload.nodes || []).forEach(node => nodeDetails.set(String(node.id), node));
        edgeDetails.clear();
        (payload.links || []).forEach(link => edgeDetails.set(String(link.id), link));
        const apiBySignature = new Map(
          (payload.links || []).map(link => [
            [link.source, link.target, link.relation || '', link.context || ''].join('|'),
            link.id
          ])
        );
        network.body.data.edges.get().forEach(edge => {
          const apiId = apiBySignature.get(edgeSignature(edge));
          if (apiId) edgeApiIds.set(String(edge.id), apiId);
        });
      })
      .catch(error => console.warn('图谱编辑接口暂不可用:', error.message));
  }

  function requestEvidence(kind, id) {
    const requestedId = String(id ?? '');
    if (!requestedId) return;
    editorMetadataReady.then(() => {
      let sourceBlocks = [];
      let entityTerms = [];
      let relationTerms = [];
      if (kind === 'node') {
        const detail = nodeDetails.get(requestedId);
        const graphNode = network.body.data.nodes.get(id)
          || network.body.data.nodes.get().find(candidate => String(candidate.id) === requestedId);
        sourceBlocks = detail?.source_blocks?.length
          ? detail.source_blocks
          : (graphNode?.source_blocks || []);
        entityTerms = [detail?.name || graphNode?.label || graphNode?.id || requestedId];
      } else if (kind === 'edge') {
        const edge = network.body.data.edges.get(id)
          || network.body.data.edges.get().find(candidate => String(candidate.id) === requestedId);
        let apiId = edgeApiIds.get(requestedId) || requestedId;
        if (edge && !edgeDetails.has(String(apiId))) {
          const matchingDetail = [...edgeDetails.entries()].find(([, detail]) => {
            const endpointsMatch = (String(detail.source) === String(edge.from)
              && String(detail.target) === String(edge.to))
              || (String(detail.source) === String(edge.to)
                && String(detail.target) === String(edge.from));
            return endpointsMatch && (!detail.relation || String(detail.relation) === String(edge.label || ''));
          });
          if (matchingDetail) apiId = matchingDetail[0];
        }
        const detail = edgeDetails.get(String(apiId)) || {};
        sourceBlocks = detail.evidence_blocks || [];
        if (!sourceBlocks.length && detail.source_block) sourceBlocks = [detail.source_block];
        if (edge && !sourceBlocks.length) {
          const fallback = edgeDetails.get(String(edge.id));
          sourceBlocks = fallback?.evidence_blocks || [];
        }
        if (edge && !sourceBlocks.length) {
          sourceBlocks = edge.evidence_blocks || [];
          if (!sourceBlocks.length && edge.source_block) sourceBlocks = [edge.source_block];
        }
        entityTerms = [
          edge?.from, edge?.to, edge?.evidence_source, edge?.evidence_target
        ].filter(Boolean);
        entityTerms.push(detail.source, detail.target, detail.relation);
        relationTerms = [edge?.label, detail.relation];
      }
      window.parent?.postMessage({
        type: 'knowledge-graph-evidence',
        graphName: GRAPH_NAME,
        kind,
        id: requestedId,
        sourceBlocks,
        entityTerms: [...new Set(entityTerms.map(value => String(value || '').trim()).filter(Boolean))],
        relationTerms: [...new Set(relationTerms.map(value => String(value || '').trim()).filter(Boolean))]
      }, '*');
    });
  }

  function showNodeDialog(target) {
    const node = network.body.data.nodes.get(target.id);
    if (!node) return;
    const detail = nodeDetails.get(String(node.id)) || {};
    const detailSourceBlocks = Array.isArray(detail.source_blocks) ? detail.source_blocks : [];
    const sourceBlocks = detailSourceBlocks.length ? detailSourceBlocks : (node.source_blocks || []);
    const mask = document.createElement('div');
    mask.className = 'graph-editor-dialog-mask';
    mask.innerHTML = `
      <section class="graph-editor-dialog" role="dialog" aria-modal="true">
        <h3>节点详情</h3>
        <div class="graph-editor-field"><label>节点名称</label><input value="${escapeHtml(node.label || node.id)}" readonly></div>
        <div class="graph-editor-field"><label>节点类型</label><input value="${escapeHtml(entityTypeOf(node))}" readonly></div>
        <div class="graph-editor-field"><label>连接数</label><input value="${escapeHtml(network.getConnectedNodes(node.id).length)}" readonly></div>
        <div class="graph-editor-field"><label>出处文本块（只读）</label><textarea readonly>${escapeHtml(sourceBlocks.length ? sourceBlocks.join('\n') : '无可定位出处')}</textarea></div>
        <div class="graph-editor-actions">
          <button type="button" data-dialog-close>关闭</button>
          <button type="button" class="primary" data-dialog-locate>原文查找</button>
        </div>
      </section>`;
    document.body.appendChild(mask);
    const close = () => mask.remove();
    mask.addEventListener('click', event => {
      if (event.target === mask || event.target.closest('[data-dialog-close]')) close();
    });
    mask.querySelector('[data-dialog-locate]').addEventListener('click', () => {
      requestEvidence('node', target.id);
      close();
    });
  }

  function highlightGraphTarget(kind, id, locateSource = true, edgeHint = {}) {
    const requestedId = String(id ?? '');
    if (!requestedId) return;
    editorMetadataReady.then(() => {
      if (kind === 'node') {
        const node = network.body.data.nodes.get(requestedId)
          || network.body.data.nodes.get().find(item => String(item.id) === requestedId);
        if (!node) {
          window.parent?.postMessage({ type: 'knowledge-graph-highlight-missing', kind, id: requestedId }, '*');
          return;
        }
        network.selectNodes([node.id]);
        network.focus(node.id, { scale: 1.45, animation: { duration: 350 } });
        window.parent?.postMessage({ type: 'knowledge-graph-highlighted', kind, id: requestedId }, '*');
        if (locateSource) requestEvidence('node', node.id);
        return;
      }
      let edge = network.body.data.edges.get(requestedId)
        || network.body.data.edges.get().find(item =>
          String(item.id) === requestedId || String(edgeApiIds.get(String(item.id))) === requestedId
        );
      if (!edge && (edgeHint.source || edgeHint.target || edgeHint.relation)) {
        const source = String(edgeHint.source || '');
        const target = String(edgeHint.target || '');
        const relation = String(edgeHint.relation || '');
        edge = network.body.data.edges.get().find(item => {
          const endpointsMatch = (!source || !target)
            ? String(item.from) === source || String(item.to) === target
            : (String(item.from) === source && String(item.to) === target)
              || (String(item.from) === target && String(item.to) === source);
          const relationMatches = !relation || String(item.label || '') === relation;
          return endpointsMatch && relationMatches;
        });
      }
      if (!edge) {
        window.parent?.postMessage({ type: 'knowledge-graph-highlight-missing', kind, id: requestedId }, '*');
        return;
      }
      network.selectEdges([edge.id]);
      network.fit({ nodes: [edge.from, edge.to], animation: { duration: 350 } });
      window.parent?.postMessage({ type: 'knowledge-graph-highlighted', kind, id: requestedId }, '*');
      if (locateSource) requestEvidence('edge', edge.id);
    });
  }

  function showContextMenu(event, target) {
    contextTarget = target;
    if (!contextMenu) {
      contextMenu = document.createElement('div');
      contextMenu.className = 'graph-context-menu';
      document.body.appendChild(contextMenu);
      contextMenu.addEventListener('click', event => {
        const action = event.target.closest('button')?.dataset.action;
        if (!action) return;
        hideContextMenu();
        runGraphAction(action, contextTarget);
      });
    }
    const nodeActions = `
      <button data-action="view-node">查看节点</button>
      <button data-action="edit-node">编辑节点</button>
      <button data-action="add-edge">从此节点新增关系</button>
      <button class="danger" data-action="delete-node">删除节点</button>`;
    const edgeActions = `
      <button data-action="view-edge">查看关系</button>
      <button data-action="edit-edge">编辑关系</button>
      <button class="danger" data-action="delete-edge">删除关系</button>`;
    const canvasActions = '<button data-action="add-node">新增节点</button>';
    contextMenu.innerHTML = `${target.type === 'node' ? nodeActions : target.type === 'edge' ? edgeActions : canvasActions}
      <button data-action="history">历史记录与还原</button>`;
    contextMenu.style.display = 'block';
    contextMenu.style.left = `${Math.min(event.clientX, window.innerWidth - 170)}px`;
    contextMenu.style.top = `${Math.min(event.clientY, window.innerHeight - 180)}px`;
  }

  function hideContextMenu() {
    if (contextMenu) contextMenu.style.display = 'none';
  }

  function askText(label, value = '') {
    const result = window.prompt(label, value);
    return result === null ? null : result.trim();
  }

  function mutation(operation, payload = {}) {
    if (!GRAPH_NAME) return Promise.reject(new Error('当前图谱页面缺少文件标识'));
    return editorApi(`/graph-mutation/${encodeURIComponent(GRAPH_NAME)}`, {
      method: 'POST',
      body: JSON.stringify({ operation, revision: editorRevision, ...payload })
    }).then(() => {
      window.parent?.postMessage({ type: 'knowledge-graph-updated', filename: GRAPH_NAME }, '*');
      window.location.reload();
    });
  }

  function selectedNode(target) {
    return network.body.data.nodes.get(target.id);
  }

  function selectedEdge(target) {
    return network.body.data.edges.get(target.id);
  }

  function editNode(target) {
    const node = selectedNode(target);
    if (!node) return;
    const name = askText('节点名称：', node.label || node.id);
    if (!name) return;
    const entityType = askText('节点类型：', entityTypeOf(node));
    if (!entityType) return;
    mutation('update_node', { node_id: String(node.id), name, entity_type: entityType })
      .catch(error => window.alert(error.message));
  }

  function addNode() {
    const name = askText('新节点名称：');
    if (!name) return;
    const entityType = askText('节点类型：', '未知标签');
    if (!entityType) return;
    mutation('add_node', { name, entity_type: entityType })
      .catch(error => window.alert(error.message));
  }

  function addEdge(target) {
    const source = String(target.id);
    const nodeNames = network.body.data.nodes.get().map(node => node.label || node.id).join('、');
    const targetName = askText(`关系终点节点（已有节点：${nodeNames}）：`);
    if (!targetName) return;
    const relation = askText('关系名称：');
    if (!relation) return;
    const context = askText('关系说明：', relation) || relation;
    mutation('add_edge', { source, target: targetName, relation, context, weight: 0.5 })
      .catch(error => window.alert(error.message));
  }

  function edgeRecord(target) {
    const edge = selectedEdge(target);
    if (!edge) return null;
    const edgeId = edgeApiIds.get(String(edge.id)) || edge.id;
    const detail = edgeDetails.get(String(edgeId)) || {};
    return {
      ...edge,
      ...detail,
      editId: edgeId,
      source: detail.source || edge.from,
      target: detail.target || edge.to,
      relation: detail.relation || edge.label || '',
      evidence: detail.evidence || detail.context || edge.title || '',
      sourceBlock: detail.source_block || edge.source_block || '无',
      evidenceBlocks: Array.isArray(detail.evidence_blocks) && detail.evidence_blocks.length
        ? detail.evidence_blocks
        : (Array.isArray(edge.evidence_blocks) ? edge.evidence_blocks : []),
      score: detail.score ?? detail.weight ?? edge.weight ?? 0.5,
      origin: (detail.origin || edge.origin) === 'manual' ? '用户新增' : 'AI抽取'
    };
  }

  function showEdgeDialog(target, readonly = false) {
    const edge = edgeRecord(target);
    if (!edge) return;
    const mask = document.createElement('div');
    mask.className = 'graph-editor-dialog-mask';
    const disabled = readonly ? ' readonly' : '';
    mask.innerHTML = `
      <section class="graph-editor-dialog" role="dialog" aria-modal="true">
        <h3>${readonly ? '关系详情' : '编辑关系'}</h3>
        <div class="graph-editor-field"><label>起点节点</label><input id="edgeEditorSource" value="${escapeHtml(edge.source)}"${disabled}></div>
        <div class="graph-editor-field"><label>终点节点</label><input id="edgeEditorTarget" value="${escapeHtml(edge.target)}"${disabled}></div>
        <div class="graph-editor-field"><label>关系名称</label><input id="edgeEditorRelation" value="${escapeHtml(edge.relation)}"${disabled}></div>
        <div class="graph-editor-field"><label>出处依据 / 关系说明</label><textarea id="edgeEditorEvidence"${disabled}>${escapeHtml(edge.evidence)}</textarea></div>
        <div class="graph-editor-field"><label>出处文本块（只读）</label><textarea readonly>${escapeHtml(edge.evidenceBlocks.length
          ? edge.evidenceBlocks.map(item => item.source_block || item).filter(Boolean).join('\n')
          : edge.sourceBlock)}</textarea></div>
        <div class="graph-editor-field"><label>得分 / 权重（0-1）</label><input id="edgeEditorScore" type="number" min="0" max="1" step="0.01" value="${escapeHtml(edge.score)}"${disabled}></div>
        <div class="graph-editor-field"><label>关系来源</label><input value="${escapeHtml(edge.origin)}" readonly></div>
        <div class="graph-editor-field"><label>关系 ID</label><input value="${escapeHtml(edge.editId)}" readonly></div>
        <div class="graph-editor-actions">
          <button type="button" data-dialog-close>关闭</button>
          <button type="button" data-dialog-locate>原文查找</button>
          ${readonly ? '' : '<button type="button" class="primary" data-dialog-save>保存修改</button>'}
        </div>
      </section>`;
    document.body.appendChild(mask);
    const close = () => mask.remove();
    mask.addEventListener('click', event => {
      if (event.target === mask || event.target.closest('[data-dialog-close]')) close();
    });
    mask.querySelector('[data-dialog-locate]').addEventListener('click', () => {
      requestEvidence('edge', target.id);
      close();
    });
    if (!readonly) {
      mask.querySelector('[data-dialog-save]').addEventListener('click', () => {
        const score = Number(mask.querySelector('#edgeEditorScore').value);
        if (!Number.isFinite(score) || score < 0 || score > 1) return window.alert('得分必须在0到1之间');
        mutation('update_edge', {
          edge_id: edge.editId,
          source: mask.querySelector('#edgeEditorSource').value.trim(),
          target: mask.querySelector('#edgeEditorTarget').value.trim(),
          relation: mask.querySelector('#edgeEditorRelation').value.trim(),
          context: mask.querySelector('#edgeEditorEvidence').value.trim(),
          weight: score
        }).catch(error => window.alert(error.message));
      });
    }
  }

  function editEdge(target) {
    showEdgeDialog(target, false);
  }

  function deleteTarget(target) {
    const isNode = target.type === 'node';
    const item = isNode ? selectedNode(target) : selectedEdge(target);
    if (!item || !window.confirm(isNode ? '删除节点会同时删除相连关系，是否继续？' : '是否删除这条关系？')) return;
    const id = isNode ? item.id : (edgeApiIds.get(String(item.id)) || item.id);
    mutation(isNode ? 'delete_node' : 'delete_edge', isNode ? { node_id: String(id) } : { edge_id: id })
      .catch(error => window.alert(error.message));
  }

  function viewTarget(target) {
    const item = target.type === 'node' ? selectedNode(target) : selectedEdge(target);
    if (!item) return;
    if (target.type === 'node') {
      showNodeDialog(target);
    } else {
      showEdgeDialog(target, true);
    }
  }

  function showHistory() {
    editorApi(`/graph-history/${encodeURIComponent(GRAPH_NAME)}`).then(payload => {
      const versions = payload.versions || [];
      if (!versions.length) return window.alert('暂无图谱修改历史');
      const description = versions.map(version =>
        `${version.revision}: ${version.description || version.operation || '图谱修改'} (${version.created_at})`).join('\n');
      const revision = askText(`历史版本（输入版本号还原）：\n${description}`);
      if (!revision) return;
      const number = Number(revision);
      if (!Number.isInteger(number)) return window.alert('版本号必须是整数');
      if (!window.confirm(`确认还原到版本 ${number}？还原会创建新的历史版本。`)) return;
      editorApi(`/graph-restore/${encodeURIComponent(GRAPH_NAME)}/${number}`, {
        method: 'POST',
        body: JSON.stringify({ operation: 'restore', revision: editorRevision })
      }).then(() => {
        window.parent?.postMessage({ type: 'knowledge-graph-restored', filename: GRAPH_NAME }, '*');
        window.location.reload();
      }).catch(error => window.alert(error.message));
    }).catch(error => window.alert(error.message));
  }

  function runGraphAction(action, target) {
    if (action === 'add-node') return addNode();
    if (action === 'edit-node') return editNode(target);
    if (action === 'delete-node') return deleteTarget(target);
    if (action === 'add-edge') return addEdge(target);
    if (action === 'edit-edge') return editEdge(target);
    if (action === 'delete-edge') return deleteTarget(target);
    if (action === 'view-node' || action === 'view-edge') return viewTarget(target);
    if (action === 'history') return showHistory();
  }

  document.addEventListener('DOMContentLoaded', function () {
    const graphContainer = document.getElementById('mynetwork');
    if (!graphContainer || typeof network === 'undefined') return;
    const host = graphContainer.parentNode;
    applyLargeGraphPerformance();
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
    editorMetadataReady = syncEditorRevision();
    window.addEventListener('message', event => {
      if (event.source !== window.parent) return;
      if (event.data?.graphName && event.data.graphName !== GRAPH_NAME) return;
      if (event.data?.type === 'knowledge-graph-exit-immersive') {
        immersive = false;
        applyResponsivePanels(true);
        return;
      }
      if (event.data?.type === 'knowledge-graph-highlight') {
        highlightGraphTarget(event.data.kind, event.data.id, event.data.locateSource !== false, {
          source: event.data.source,
          target: event.data.target,
          relation: event.data.relation
        });
      }
    });
    document.addEventListener('click', hideContextMenu);
    // vis-network's `oncontext` is not emitted consistently across its
    // versions, especially when the canvas is inside a sandboxed iframe.
    // Bind the native DOM event as the authoritative browser-menu blocker.
    graphContainer.addEventListener('contextmenu', event => {
      event.preventDefault();
      event.stopPropagation();
      const rect = graphContainer.getBoundingClientRect();
      const pointer = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      const nodeId = network.getNodeAt(pointer);
      const hasNode = nodeId !== undefined && nodeId !== null;
      const edgeId = hasNode ? undefined : network.getEdgeAt(pointer);
      const hasEdge = edgeId !== undefined && edgeId !== null;
      showContextMenu(event, hasNode
        ? { type: 'node', id: nodeId }
        : hasEdge
          ? { type: 'edge', id: edgeId }
          : { type: 'canvas', id: null });
    }, true);
    network.on('oncontext', params => {
      params.event?.srcEvent?.preventDefault?.();
      const nodeId = params.nodes?.[0];
      const edgeId = params.edges?.[0];
      const sourceEvent = params.event?.srcEvent;
      if (!sourceEvent) return;
      showContextMenu(sourceEvent, nodeId !== undefined
        ? { type: 'node', id: nodeId }
        : edgeId !== undefined
          ? { type: 'edge', id: edgeId }
          : { type: 'canvas', id: null });
    });

    const runtimeNodeCount = network.body.data.nodes.get().length;
    const runtimeEdgeCount = network.body.data.edges.get().length;
    const searchPanel = createPanel('search-panel', '🔍 实体与关系', `
      <input type="search" id="searchInput" class="graph-text-input" placeholder="搜索实体或关系...">
      <div class="search-results" id="searchResults"></div>
      <div class="status-bar" id="visibleGraphStatus"><strong>${Math.max(NODE_COUNT, runtimeNodeCount)}</strong> 节点 · <strong>${Math.max(EDGE_COUNT, runtimeEdgeCount)}</strong> 关系</div>`);
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
      <div class="status-bar">右键节点、关系或空白处，可进行增删改查</div>
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

    let applyResponsivePanels = () => {};
    const immersiveButton = document.createElement('button');
    immersiveButton.className = 'immersive-toggle';
    immersiveButton.type = 'button';
    immersiveButton.textContent = immersive ? '退出沉浸' : '⛶ 沉浸模式';
    immersiveButton.addEventListener('click', () => {
      const leavingImmersive = immersive;
      immersive = !immersive;
      if (immersive) {
        document.querySelectorAll('.graph-floating-panel').forEach(panel => {
          if (panel.classList.contains('community-directory')) {
            syncPanelCollapseButton(panel);
            return;
          }
          if (!panel.classList.contains('is-collapsed')) panel.dataset.immersiveCollapsed = '1';
          panel.classList.add('is-collapsed');
          syncPanelCollapseButton(panel, true);
        });
      }
      immersiveButton.textContent = immersive ? '退出沉浸' : '⛶ 沉浸模式';
      applyResponsivePanels(leavingImmersive);
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
    applyDefaultImmersivePanels();
    applyResponsivePanels = setupResponsivePanels(host, graphContainer);
    window.requestAnimationFrame(applyResponsivePanels);
    applyVisibilityFilters(); renderSearchResults(); updateCounter();
  });
})();
</script>
"""


def build_graph_interaction_html(
    node_count: int,
    edge_count: int,
    graph_name: str = "",
    static_layout_version: int = 2,
) -> str:
    """Build the static interaction layer with escaped numeric counters."""
    return (
        GRAPH_INTERACTION_TEMPLATE
        .replace("__GRAPH_EDITOR_VERSION__", escape(str(GRAPH_EDITOR_VERSION)))
        .replace("__NODE_COUNT__", escape(str(int(node_count))))
        .replace("__EDGE_COUNT__", escape(str(int(edge_count))))
        .replace("__GRAPH_NAME__", json.dumps(str(graph_name), ensure_ascii=False))
        .replace("__GRAPH_STATIC_LAYOUT_VERSION__", escape(str(int(static_layout_version))))
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


def finalize_generated_graph_html(
    html_content: str,
    asset_base_url: str | None = "/api/graph-assets",
) -> str:
    """Finalize browser assets while writing a graph page to disk."""
    has_vis_asset_reference = (
        "cdnjs.cloudflare.com/ajax/libs/vis-network/" in html_content
        or "/api/graph-assets/vis-network" in html_content
    )
    if has_vis_asset_reference:
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
        html_content = re.sub(
            r'<link\b[^>]*href="/api/graph-assets/vis-network\.css"[^>]*>',
            lambda _match: css_replacement,
            html_content,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
        html_content = re.sub(
            r'<script\b[^>]*src="/api/graph-assets/vis-network\.min\.js"[^>]*>\s*</script>',
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
    return html_content


def prepare_legacy_graph_html(
    html_content: str,
    asset_base_url: str | None = None,
    graph_name: str = "",
) -> str:
    """Upgrade legacy graph content during explicit migration or export work."""
    html_content = finalize_generated_graph_html(html_content, asset_base_url)

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
    if graph_name and (
        f"const GRAPH_EDITOR_VERSION = {GRAPH_EDITOR_VERSION};" not in html_content
        or "function applyLargeGraphPerformance()" not in html_content
        or "function moveLegacyIsolatedNodesOutside()" not in html_content
        or "const GRAPH_STATIC_LAYOUT_VERSION =" not in html_content
        or "GRAPH_STATIC_LAYOUT_VERSION < 2" not in html_content
    ):
        # Replace an older injected interaction layer instead of appending a
        # second one. Otherwise both old and new context-menu handlers would
        # run on the same right click.
        old_layer = re.compile(
            r'<style>\s*div\.vis-configuration-wrapper.*?</style>\s*'
            r'<script>\s*\(function \(\) \{\s*'
            r'(?:const GRAPH_EDITOR_VERSION\s*=\s*\d+;\s*)?'
            r'const NODE_COUNT = .*?</script>',
            flags=re.IGNORECASE | re.DOTALL,
        )
        html_content = old_layer.sub('', html_content, count=1)
        # Older generated pages predate the editor. Inject the current layer
        # on delivery so they gain the same CRUD and history behavior.
        editor_html = build_graph_interaction_html(0, 0, graph_name, static_layout_version=0)
        html_content = html_content.replace("</body>", editor_html + "</body>", 1)
    return html_content
