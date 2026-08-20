"""Static Sigma.js graph pages and topology-aware layout helpers.

The page stores the graph data and coordinates produced during graph rendering.
Opening it therefore only initializes Sigma's renderer; it never fetches graph
data or runs a browser-side layout simulation.
"""

from __future__ import annotations

import colorsys
import html
import json
import math
import re
import warnings
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

import networkx as nx
import numpy as np

from KnowledgeGraphManager.graph_interactions import build_graph_interaction_html


NODE_COLORS = [
    "#e22653", "#3478c5", "#5c9f68", "#d58d37", "#8b61a8",
    "#258c9a", "#ad6274", "#767c3b", "#5b78ac", "#b05c51",
]
SIGMA_STATIC_PAGE_VERSION = 13

TYPE_ICONS = {
    "chart type": "charttype", "图表类型": "charttype", "图表": "charttype",
    "company": "company", "公司": "company", "企业": "company",
    "concept": "concept", "概念": "concept", "field": "field", "领域": "field",
    "学科": "field", "list": "list", "列表": "list", "method": "method",
    "方法": "method", "organization": "organization", "组织": "organization",
    "机构": "organization", "person": "person", "人物": "person", "人名": "person",
    "technology": "technology", "技术": "technology", "tool": "tool", "工具": "tool",
    "unknown": "unknown", "未知": "unknown", "未分类": "unknown",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _icon_name(entity_type: Any) -> str:
    token = _text(entity_type).lower()
    if token in TYPE_ICONS:
        return TYPE_ICONS[token]
    patterns = (
        ("person", "person"), ("人物", "person"), ("人名", "person"),
        ("organ", "organization"), ("机构", "organization"), ("组织", "organization"),
        ("company", "company"), ("公司", "company"), ("企业", "company"),
        ("concept", "concept"), ("概念", "concept"), ("field", "field"),
        ("领域", "field"), ("method", "method"), ("方法", "method"),
        ("technolog", "technology"), ("技术", "technology"), ("tool", "tool"),
        ("工具", "tool"), ("chart", "charttype"), ("图表", "charttype"),
        ("list", "list"), ("列表", "list"),
    )
    for marker, icon in patterns:
        if marker in token:
            return icon
    return "unknown"


def _cluster_color(index: int) -> str:
    red, green, blue = colorsys.hls_to_rgb((index * 0.381966) % 1.0, 0.48, 0.62)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def _partition(graph: nx.Graph) -> dict[Any, int]:
    if not graph:
        return {}
    try:
        import community as community_louvain

        return community_louvain.best_partition(graph, random_state=42)
    except Exception:
        return {
            node: index
            for index, component in enumerate(nx.connected_components(graph))
            for node in component
        }


def _normalize_positions(positions: Mapping[Any, tuple[float, float]], extent: float) -> dict[Any, tuple[float, float]]:
    if not positions:
        return {}
    mean_x = sum(float(x) for x, _ in positions.values()) / len(positions)
    mean_y = sum(float(y) for _, y in positions.values()) / len(positions)
    centered = {node: (float(x) - mean_x, float(y) - mean_y) for node, (x, y) in positions.items()}
    max_extent = max((max(abs(x), abs(y)) for x, y in centered.values()), default=1.0) or 1.0
    scale = max(1.0, extent / max_extent)
    return {node: (x * scale, y * scale) for node, (x, y) in centered.items()}


def _barnes_hut_forceatlas2(
    graph: nx.Graph,
    node_sizes: Mapping[Any, float],
    iterations: int,
) -> dict[Any, tuple[float, float]]:
    """Large-graph ForceAtlas2 using a Barnes-Hut repulsion approximation."""
    nodes = list(graph.nodes)
    node_index = {node: index for index, node in enumerate(nodes)}
    order = len(nodes)
    rng = np.random.default_rng(42)
    spread = max(24.0, math.sqrt(order) * 4.5)
    positions = rng.uniform(-0.5, 0.5, size=(order, 2))
    positions[:, 0] *= spread * 1.25
    positions[:, 1] *= spread
    sizes = np.array([float(node_sizes.get(node, 3.0)) for node in nodes], dtype=float)
    masses = np.ones(order, dtype=float)
    edge_records = []
    for source, target, data in graph.edges(data=True):
        source_index, target_index = node_index[source], node_index[target]
        weight = max(0.25, min(2.0, float(data.get("weight", 1.0) or 1.0)))
        masses[source_index] += weight
        masses[target_index] += weight
        edge_records.append((source_index, target_index, weight))

    old_forces = np.zeros((order, 2), dtype=float)
    theta_squared = 0.55 ** 2
    scaling_ratio = 18.0 if order > 2500 else 14.0
    gravity = 0.18
    slow_down = 4.0

    for _ in range(iterations):
        min_x, min_y = positions.min(axis=0)
        max_x, max_y = positions.max(axis=0)
        half = max(max_x - min_x, max_y - min_y, 1e-6) * 0.500001
        centers_x = [(min_x + max_x) * 0.5]
        centers_y = [(min_y + max_y) * 0.5]
        halves = [half]
        region_mass = [0.0]
        mass_x = [0.0]
        mass_y = [0.0]
        points = [-1]
        children = [None]

        def add_region(center_x, center_y, region_half):
            region = len(halves)
            centers_x.append(center_x); centers_y.append(center_y); halves.append(region_half)
            region_mass.append(0.0); mass_x.append(0.0); mass_y.append(0.0)
            points.append(-1); children.append(None)
            return region

        def quadrant(region, point_index):
            right = positions[point_index, 0] >= centers_x[region]
            bottom = positions[point_index, 1] >= centers_y[region]
            return (2 if right else 0) + (1 if bottom else 0)

        def insert(region, point_index, depth=0):
            mass = masses[point_index]
            total = region_mass[region] + mass
            mass_x[region] = (mass_x[region] * region_mass[region] + positions[point_index, 0] * mass) / total
            mass_y[region] = (mass_y[region] * region_mass[region] + positions[point_index, 1] * mass) / total
            region_mass[region] = total
            if children[region] is None and points[region] < 0:
                points[region] = point_index
                return
            if children[region] is None:
                child_half = halves[region] * 0.5
                offsets = ((-1, -1), (-1, 1), (1, -1), (1, 1))
                children[region] = tuple(
                    add_region(
                        centers_x[region] + dx * child_half,
                        centers_y[region] + dy * child_half,
                        child_half,
                    )
                    for dx, dy in offsets
                )
                previous = points[region]
                points[region] = -1
                insert(children[region][quadrant(region, previous)], previous, depth + 1)
            if depth < 24:
                insert(children[region][quadrant(region, point_index)], point_index, depth + 1)

        for index in range(order):
            insert(0, index)

        forces = np.zeros((order, 2), dtype=float)
        for index in range(order):
            stack = [0]
            while stack:
                region = stack.pop()
                if region_mass[region] <= 0:
                    continue
                dx = positions[index, 0] - mass_x[region]
                dy = positions[index, 1] - mass_y[region]
                distance_squared = dx * dx + dy * dy
                region_children = children[region]
                if region_children is None:
                    other = points[region]
                    if other < 0 or other == index:
                        continue
                    distance = math.sqrt(max(distance_squared, 1e-12))
                    clearance = distance - sizes[index] - sizes[other]
                    if clearance > 0:
                        factor = scaling_ratio * masses[index] * masses[other] / (clearance * clearance)
                    else:
                        factor = 100.0 * scaling_ratio * masses[index] * masses[other]
                    forces[index, 0] += dx * factor
                    forces[index, 1] += dy * factor
                    continue
                width = halves[region] * 2.0
                if distance_squared > 1e-12 and width * width / distance_squared < theta_squared:
                    factor = scaling_ratio * masses[index] * region_mass[region] / distance_squared
                    forces[index, 0] += dx * factor
                    forces[index, 1] += dy * factor
                else:
                    stack.extend(region_children)

        distance_from_center = np.linalg.norm(positions, axis=1)
        nonzero = distance_from_center > 1e-12
        forces[nonzero] -= (
            positions[nonzero]
            * (masses[nonzero] * gravity / distance_from_center[nonzero])[:, None]
        )
        compensation = masses.mean()
        for source, target, weight in edge_records:
            delta = positions[source] - positions[target]
            distance = float(np.linalg.norm(delta))
            clearance = distance - sizes[source] - sizes[target]
            if clearance <= 0:
                continue
            factor = -compensation * (weight ** 0.35) * math.log1p(clearance) / clearance / masses[source]
            attraction = delta * factor
            forces[source] += attraction
            forces[target] -= attraction

        magnitudes = np.linalg.norm(forces, axis=1)
        too_large = magnitudes > 10.0
        forces[too_large] *= (10.0 / magnitudes[too_large])[:, None]
        swinging = masses * np.linalg.norm(old_forces - forces, axis=1)
        traction = np.linalg.norm(old_forces + forces, axis=1) * 0.5
        speeds = 0.1 * np.log1p(traction) / (1.0 + np.sqrt(swinging)) / slow_down
        positions += forces * speeds[:, None]
        old_forces = forces

    return {node: (float(positions[index, 0]), float(positions[index, 1])) for index, node in enumerate(nodes)}


def _resolve_node_overlaps(
    positions: dict[Any, tuple[float, float]],
    node_sizes: Mapping[Any, float],
) -> dict[Any, tuple[float, float]]:
    """Finish ForceAtlas2 anti-collision with a bounded spatial-hash pass."""
    if len(positions) < 2:
        return positions
    nodes = list(positions)
    max_size = max((float(node_sizes.get(node, 3.0)) for node in nodes), default=3.0)
    cell_size = max(8.0, max_size * 2.0 + 2.0)
    for _ in range(8):
        buckets = defaultdict(list)
        for index, node in enumerate(nodes):
            x, y = positions[node]
            buckets[(math.floor(x / cell_size), math.floor(y / cell_size))].append(index)
        moved = False
        for index, node in enumerate(nodes):
            x, y = positions[node]
            cell_x, cell_y = math.floor(x / cell_size), math.floor(y / cell_size)
            for nearby_x in range(cell_x - 1, cell_x + 2):
                for nearby_y in range(cell_y - 1, cell_y + 2):
                    for other_index in buckets.get((nearby_x, nearby_y), ()):
                        if other_index <= index:
                            continue
                        other = nodes[other_index]
                        other_x, other_y = positions[other]
                        dx, dy = other_x - x, other_y - y
                        distance = math.hypot(dx, dy)
                        required = float(node_sizes.get(node, 3.0)) + float(node_sizes.get(other, 3.0)) + 1.5
                        if distance >= required:
                            continue
                        if distance < 1e-9:
                            angle = (index + 1) * 2.399963229728653
                            dx, dy, distance = math.cos(angle), math.sin(angle), 1.0
                        ux, uy = dx / distance, dy / distance
                        push = (required - distance) * 0.52
                        positions[node] = (x - ux * push, y - uy * push)
                        positions[other] = (other_x + ux * push, other_y + uy * push)
                        x, y = positions[node]
                        moved = True
        if not moved:
            break
    return positions


def sigma_layout(
    graph: nx.Graph,
    communities: Mapping[Any, int] | None = None,
    node_sizes: Mapping[Any, float] | None = None,
) -> dict[Any, tuple[float, float]]:
    """Compute a deterministic ForceAtlas2 layout with size-aware repulsion."""
    if not graph:
        return {}
    undirected = nx.Graph(graph.to_undirected())
    partition = dict(communities) if communities is not None else _partition(undirected)
    if node_sizes is None:
        node_sizes = _node_sizes(_centrality_scores(undirected))
    order = len(undirected)
    iterations = 10 if order > 5000 else 18 if order > 2500 else 36 if order > 1200 else 80
    try:
        if order > 2000:
            raw = _barnes_hut_forceatlas2(undirected, node_sizes, iterations)
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                with np.errstate(divide="ignore", invalid="ignore"):
                    raw = nx.forceatlas2_layout(
                        undirected,
                        max_iter=iterations,
                        scaling_ratio=11.0,
                        gravity=0.18,
                        distributed_action=True,
                        linlog=True,
                        node_size={node: float(node_sizes.get(node, 3.0)) for node in undirected.nodes},
                        weight="weight",
                        seed=42,
                    )
    except (AttributeError, TypeError, ValueError):
        # NetworkX versions without the adjust_sizes keyword still get the
        # same deterministic topology, with a conservative spring fallback.
        raw = nx.spring_layout(
            undirected,
            seed=42,
            iterations=max(24, iterations),
            weight="weight",
            k=max(0.45, 1.1 / math.sqrt(max(1, order))),
        )
    if any(
        not math.isfinite(float(x)) or not math.isfinite(float(y))
        for x, y in raw.values()
    ):
        # ForceAtlas2 has no usable force direction when a community consists
        # entirely of isolated nodes. Keep those detail pages deterministic.
        raw = nx.circular_layout(undirected) if not undirected.number_of_edges() else nx.spring_layout(
            undirected,
            seed=42,
            iterations=max(24, iterations),
            weight="weight",
            k=max(0.45, 1.1 / math.sqrt(max(1, order))),
        )
    extent = max(360.0, math.sqrt(max(1, order)) * 82.0)
    positions = _normalize_positions(raw, extent)
    members: dict[int, list[Any]] = defaultdict(list)
    for node in undirected.nodes:
        members[partition.get(node, 0)].append(node)

    # Keep long intra-community edges from dominating the full map.
    if positions:
        min_x = min(x for x, _ in positions.values())
        max_x = max(x for x, _ in positions.values())
        min_y = min(y for _, y in positions.values())
        max_y = max(y for _, y in positions.values())
        # Leave headroom for the final anti-collision pass. The resulting
        # community span remains below the requested roughly-half-map limit.
        limit = max(120.0, max(max_x - min_x, max_y - min_y) * 0.54)
        longest_edges: dict[int, float] = defaultdict(float)
        for source, target in undirected.edges:
            community = partition.get(source, 0)
            if community != partition.get(target, 0):
                continue
            sx, sy = positions[source]
            tx, ty = positions[target]
            longest_edges[community] = max(
                longest_edges[community],
                math.hypot(tx - sx, ty - sy),
            )
        for community, nodes in members.items():
            longest = longest_edges[community]
            if longest <= limit:
                continue
            cx = sum(positions[node][0] for node in nodes) / len(nodes)
            cy = sum(positions[node][1] for node in nodes) / len(nodes)
            ratio = max(0.24, limit / longest)
            for node in nodes:
                x, y = positions[node]
                positions[node] = (cx + (x - cx) * ratio, cy + (y - cy) * ratio)
    return _resolve_node_overlaps(positions, node_sizes)


def _separate_overview_hubs(
    graph: nx.Graph,
    positions: dict[Any, tuple[float, float]],
    node_sizes: Mapping[Any, float],
) -> dict[Any, tuple[float, float]]:
    """Add screen-scale breathing room between the overview's main hubs."""
    if len(positions) < 2 or not graph:
        return positions
    undirected = nx.Graph(graph.to_undirected())
    degrees = dict(undirected.degree())
    connected = [node for node in positions if degrees.get(node, 0) > 0]
    if len(connected) < 2:
        return positions

    hub_limit = min(40, max(12, math.ceil(math.sqrt(len(connected)) * 2.0)))
    hubs = sorted(
        connected,
        key=lambda node: (
            -float(node_sizes.get(node, 3.0)),
            -degrees.get(node, 0),
            str(node),
        ),
    )[:hub_limit]
    min_x = min(x for x, _ in positions.values())
    max_x = max(x for x, _ in positions.values())
    min_y = min(y for _, y in positions.values())
    max_y = max(y for _, y in positions.values())
    graph_span = max(max_x - min_x, max_y - min_y, 1.0)
    base_distance = max(84.0, graph_span * 0.065)

    for _ in range(12):
        moved = False
        for index, node in enumerate(hubs):
            x, y = positions[node]
            for other_index in range(index + 1, len(hubs)):
                other = hubs[other_index]
                other_x, other_y = positions[other]
                dx, dy = other_x - x, other_y - y
                distance = math.hypot(dx, dy)
                prominence = min(
                    1.45,
                    0.85 + math.log1p(degrees[node] + degrees[other]) / 8.0,
                )
                required = base_distance * prominence
                if distance >= required:
                    continue
                if distance < 1e-9:
                    angle = (index + other_index + 1) * 2.399963229728653
                    dx, dy, distance = math.cos(angle), math.sin(angle), 1.0
                ux, uy = dx / distance, dy / distance
                push = (required - distance) * 0.52
                positions[node] = (x - ux * push, y - uy * push)
                positions[other] = (other_x + ux * push, other_y + uy * push)
                x, y = positions[node]
                moved = True
        if not moved:
            break
    return positions


def obsidian_layout(
    graph: nx.Graph,
    communities: Mapping[Any, int],
    node_sizes: Mapping[Any, float],
) -> dict[Any, tuple[float, float]]:
    """Fast deterministic clustered layout for the panel-free full graph."""
    if not graph:
        return {}
    undirected = nx.Graph(graph.to_undirected())
    partition = dict(communities)
    members: dict[Any, list[Any]] = defaultdict(list)
    for node in undirected.nodes:
        members[partition.get(node, 0)].append(node)

    degrees = dict(undirected.degree())
    communities_by_size = sorted(members, key=lambda key: (-len(members[key]), str(key)))
    radii = {
        key: max(90.0, math.sqrt(len(members[key])) * 29.0)
        for key in communities_by_size
    }
    target_width = max(
        420.0,
        math.sqrt(sum((radius * 2.0 + 70.0) ** 2 for radius in radii.values())),
    )
    centers: dict[Any, tuple[float, float]] = {}
    cursor_x = cursor_y = row_height = 0.0
    for key in communities_by_size:
        diameter = radii[key] * 2.0
        if cursor_x and cursor_x + diameter > target_width:
            cursor_x = 0.0
            cursor_y += row_height + 70.0
            row_height = 0.0
        centers[key] = (cursor_x + radii[key], cursor_y + radii[key])
        cursor_x += diameter + 70.0
        row_height = max(row_height, diameter)

    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    positions: dict[Any, tuple[float, float]] = {}
    for key in communities_by_size:
        center_x, center_y = centers[key]
        ordered = sorted(members[key], key=lambda node: (-degrees.get(node, 0), str(node)))
        mean_size = sum(float(node_sizes.get(node, 3.0)) for node in ordered) / len(ordered)
        spacing = max(15.0, mean_size * 2.2 + 7.0)
        for index, node in enumerate(ordered):
            radius = spacing * math.sqrt(index)
            angle = index * golden_angle
            positions[node] = (
                center_x + radius * math.cos(angle),
                center_y + radius * math.sin(angle),
            )
    return _normalize_positions(positions, max(360.0, math.sqrt(len(undirected)) * 54.0))


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _centrality_scores(graph: nx.Graph) -> dict[Any, float]:
    if not graph:
        return {}
    try:
        if len(graph) <= 900:
            values = nx.betweenness_centrality(graph, normalized=True, weight=None)
        else:
            sample_count = min(128, max(48, round(math.sqrt(len(graph)) * 1.45)))
            values = nx.betweenness_centrality(graph, k=sample_count, normalized=True, weight=None, seed=42)
    except Exception:
        values = {node: 0.0 for node in graph.nodes}
    return {node: max(0.0, float(values.get(node, 0.0))) for node in graph.nodes}


def _node_sizes(scores: Mapping[Any, float]) -> dict[Any, float]:
    """Map betweenness linearly to Sigma's official demo range (3-30)."""
    if not scores:
        return {}
    values = [max(0.0, float(value)) for value in scores.values()]
    minimum, maximum = min(values), max(values)
    sizes = {}
    for node, raw_score in scores.items():
        ratio = 0.0 if maximum <= minimum else (max(0.0, float(raw_score)) - minimum) / (maximum - minimum)
        sizes[node] = round(3.0 + ratio * 27.0, 2)
    return sizes


def build_sigma_page(
    graph: nx.Graph,
    graph_name: str,
    communities: Mapping[Any, int] | None = None,
    navigation: Mapping[str, Any] | None = None,
    page_title: str | None = None,
    page_subtitle: str | None = None,
) -> str:
    navigation_data = dict(navigation or {})
    full_graph_mode = navigation_data.get("mode") == "full"
    undirected = nx.Graph(graph.to_undirected())
    if full_graph_mode:
        node_sizes = {
            node: round(max(2.5, min(14.0, 2.0 + math.sqrt(max(0, degree)) / 2.0)), 2)
            for node, degree in undirected.degree()
        }
    else:
        node_sizes = _node_sizes(_centrality_scores(undirected))
    partition = dict(communities or {})
    for node in graph.nodes:
        partition.setdefault(node, 0)
    positions = (
        obsidian_layout(graph, partition, node_sizes)
        if full_graph_mode
        else sigma_layout(graph, partition, node_sizes)
    )
    if navigation_data.get("mode") == "overview":
        positions = _separate_overview_hubs(graph, positions, node_sizes)
    cluster_members: dict[Any, list[Any]] = defaultdict(list)
    for node in graph.nodes:
        cluster_members[partition[node]].append(node)
    cluster_colors = {
        community_id: _cluster_color(index)
        for index, community_id in enumerate(sorted(cluster_members, key=str))
    }
    degrees = dict(graph.degree())
    clusters = []
    if full_graph_mode:
        for community_id, members in sorted(cluster_members.items(), key=lambda item: str(item[0])):
            representative = max(members, key=lambda node: (degrees.get(node, 0), str(node)))
            representative_label = _text(graph.nodes[representative].get("label") or representative)
            clusters.append({
                "id": _text(community_id),
                "label": f"社区{community_id} · {representative_label}",
                "color": cluster_colors[community_id],
            })
    nodes = []
    type_counts: dict[str, int] = defaultdict(int)
    for node, attrs in graph.nodes(data=True):
        node_id = _text(node)
        entity_type = _text(attrs.get("entity_type") or attrs.get("group") or attrs.get("title") or "未分类")
        type_counts[entity_type] += 1
        node_record = {
            "id": node_id,
            "label": _text(attrs.get("label") or node_id),
            "entityType": entity_type,
            "group": entity_type,
            "community": _text(partition[node]),
            "title": _text(attrs.get("description") or attrs.get("title") or entity_type),
            "color": cluster_colors[partition[node]] if full_graph_mode else NODE_COLORS[len(type_counts) % len(NODE_COLORS)],
            "size": node_sizes.get(node, 3.0),
            "x": round(float(positions.get(node, (0.0, 0.0))[0]), 3),
            "y": round(float(positions.get(node, (0.0, 0.0))[1]), 3),
            "source_blocks": list(attrs.get("source_blocks") or []),
        }
        if not full_graph_mode:
            node_record["image"] = f"/svgs/{_icon_name(entity_type)}.svg"
        nodes.append(node_record)
    type_color = {
        entity_type: NODE_COLORS[index % len(NODE_COLORS)]
        for index, entity_type in enumerate(sorted(type_counts))
    }
    if not full_graph_mode:
        for item in nodes:
            item["color"] = type_color[item["entityType"]]
    edges = []
    for index, (source, target, attrs) in enumerate(graph.edges(data=True)):
        source_id, target_id = _text(source), _text(target)
        edit_id = _text(attrs.get("edit_id")) or f"edge:{index}"
        edge_record = {
            "id": edit_id,
            "source": source_id,
            "target": target_id,
            "label": _text(attrs.get("label")),
            "relation": _text(attrs.get("label")),
            "color": "#8d97a8" if not full_graph_mode else "#a6aebe",
            "size": round(max(0.7, min(2.5, float(attrs.get("weight", 1.0) or 1.0))), 2),
            "width": round(max(0.7, min(3.5, float(attrs.get("weight", 1.0) or 1.0) * 2.5)), 2),
            "weight": round(max(0.0, min(1.0, float(attrs.get("weight", 0.5) or 0.5))), 3),
            "evidence_source": _text(attrs.get("evidence_source") or source_id),
            "evidence_target": _text(attrs.get("evidence_target") or target_id),
        }
        if not full_graph_mode:
            edge_record.update({
                "title": _text(attrs.get("title")),
                "source_block": _text(attrs.get("source_block")),
                "evidence_blocks": list(attrs.get("evidence_blocks") or []),
                "origin": _text(attrs.get("origin") or "extracted"),
            })
        edges.append(edge_record)
    payload = {
        "name": graph_name,
        "title": page_title or f"A cartography of {graph_name}",
        "subtitle": page_subtitle or "All entities and relationships",
        "nodes": nodes,
        "edges": edges,
        "types": [] if full_graph_mode else [
            {
                "type": key,
                "count": value,
                "color": type_color[key],
                "image": f"/svgs/{_icon_name(key)}.svg",
            }
            for key, value in sorted(type_counts.items())
        ],
        "clusters": clusters,
        "navigation": navigation_data,
    }
    return _sigma_html_template(
        page_title or f"A cartography of {graph_name}",
        _safe_json(payload),
        "" if full_graph_mode else build_graph_interaction_html(len(nodes), len(edges), graph_name),
    )


def _sigma_network_adapter_script() -> str:
    return r'''
<script>
(function () {
  const runtime = window.__sigmaGraphRuntime;
  if (!runtime) return;
  const { payload, graph, renderer, selected, selectedEdges, focus } = runtime;
  const nodeRecords = new Map(payload.nodes.map(node => [String(node.id), {
    ...node, id: String(node.id), value: Number(node.size || 3)
  }]));
  const edgeRecords = new Map();
  graph.forEachEdge((key, attrs, source, target) => edgeRecords.set(String(key), {
    ...attrs,
    id: String(key),
    from: String(source),
    to: String(target),
    font: { size: 0 },
    color: { color: attrs.color || '#c8cdd3', opacity: .6 }
  }));
  const labeledEdgeIds = new Set();
  let refreshFrame = 0;
  const scheduleRefresh = () => {
    if (refreshFrame) return;
    refreshFrame = window.requestAnimationFrame(() => {
      refreshFrame = 0;
      const renderEdgeLabels = labeledEdgeIds.size > 0;
      if (renderer.getSetting('renderEdgeLabels') !== renderEdgeLabels) {
        renderer.setSetting('renderEdgeLabels', renderEdgeLabels);
      } else {
        renderer.refresh();
      }
    });
  };
  const listeners = new Map();
  const emit = (event, value) => (listeners.get(event) || []).forEach(handler => handler(value));
  const addListener = (event, handler, once = false) => {
    if (event === 'afterDrawing' || event === 'stabilized') {
      window.requestAnimationFrame(() => handler({}));
      return;
    }
    const wrapped = once ? value => {
      handler(value);
      listeners.set(event, (listeners.get(event) || []).filter(item => item !== wrapped));
    } : handler;
    listeners.set(event, [...(listeners.get(event) || []), wrapped]);
  };
  const listOrItem = (records, id) => id === undefined
    ? [...records.values()].map(item => ({ ...item }))
    : records.has(String(id)) ? { ...records.get(String(id)) } : null;
  const applyNodeUpdate = update => {
    const id = String(update.id);
    if (!nodeRecords.has(id) || !graph.hasNode(id)) return;
    const record = { ...nodeRecords.get(id), ...update, id };
    nodeRecords.set(id, record);
    const safe = {};
    ['label', 'entityType', 'group', 'title', 'source_blocks', 'hidden', 'x', 'y', 'size'].forEach(key => {
      if (record[key] !== undefined) safe[key] = record[key];
    });
    graph.mergeNodeAttributes(id, safe);
  };
  const applyEdgeUpdate = update => {
    const id = String(update.id);
    if (!edgeRecords.has(id) || !graph.hasEdge(id)) return;
    const record = { ...edgeRecords.get(id), ...update, id };
    edgeRecords.set(id, record);
    if (record.font?.size > 0) labeledEdgeIds.add(id);
    else labeledEdgeIds.delete(id);
    graph.mergeEdgeAttributes(id, {
      hidden: Boolean(record.hidden),
      label: record.font?.size > 0 ? String(record.label || '') : '',
      forceLabel: record.font?.size > 0,
      size: Number(record.width || record.size || 1),
      opacity: Number(record.color?.opacity ?? .6),
    });
  };
  const dataSet = (records, apply) => ({
    get: id => listOrItem(records, id),
    update: updates => {
      (Array.isArray(updates) ? updates : [updates]).forEach(apply);
      scheduleRefresh();
    }
  });
  const centerNodes = nodeIds => {
    const ids = (nodeIds || []).map(String).filter(id => graph.hasNode(id));
    if (!ids.length) return renderer.getCamera().animatedReset({ duration: 350 });
    focus(ids);
  };
  const network = {
    body: { data: {
      nodes: dataSet(nodeRecords, applyNodeUpdate),
      edges: dataSet(edgeRecords, applyEdgeUpdate),
    } },
    on: (event, handler) => addListener(event, handler),
    once: (event, handler) => addListener(event, handler, true),
    setOptions: () => {},
    stabilize: () => emit('stabilized', {}),
    fit: options => centerNodes(options?.nodes),
    focus: node => centerNodes([node]),
    selectNodes: ids => {
      selected.clear(); selectedEdges.clear();
      (ids || []).map(String).filter(id => graph.hasNode(id)).forEach(id => selected.add(id));
      renderer.refresh();
    },
    selectEdges: ids => {
      selected.clear(); selectedEdges.clear();
      (ids || []).map(String).filter(id => graph.hasEdge(id)).forEach(id => {
        selectedEdges.add(id); selected.add(graph.source(id)); selected.add(graph.target(id));
      });
      renderer.refresh();
    },
    unselectAll: () => { selected.clear(); selectedEdges.clear(); renderer.refresh(); },
    getSelectedNodes: () => [...selected],
    getSelectedEdges: () => [...selectedEdges],
    getConnectedNodes: id => graph.hasNode(String(id)) ? graph.neighbors(String(id)) : [],
    getConnectedEdges: id => graph.hasNode(String(id)) ? graph.edges(String(id)) : [],
    getPositions: ids => Object.fromEntries((ids || []).map(String).filter(id => graph.hasNode(id)).map(id => {
      const attrs = graph.getNodeAttributes(id);
      return [id, { x: Number(attrs.x || 0), y: Number(attrs.y || 0) }];
    })),
    getNodeAt: pointer => renderer.getNodeAtPosition(pointer) ?? undefined,
    getEdgeAt: pointer => renderer.getEdgeAtPoint(pointer.x, pointer.y) ?? undefined,
  };
  window.network = network;

  renderer.on('clickNode', ({ node }) => network.selectNodes([node]));
  renderer.on('clickEdge', ({ edge, event }) => {
    network.selectEdges([edge]);
    emit('selectEdge', { edges: [edge], event });
  });
  renderer.on('clickStage', () => network.unselectAll());
  const browserEvent = event => event?.original || event;
  renderer.on('enterNode', ({ node, event }) => emit('hoverNode', { node, event: browserEvent(event) }));
  renderer.on('leaveNode', ({ node, event }) => emit('blurNode', { node, event: browserEvent(event) }));
  renderer.on('enterEdge', ({ edge, event }) => emit('hoverEdge', { edge, event: browserEvent(event) }));
  renderer.on('leaveEdge', ({ edge, event }) => emit('blurEdge', { edge, event: browserEvent(event) }));

  const navigation = payload.navigation || {};
  const entries = Array.isArray(navigation.entries) ? navigation.entries : [];
  if (entries.length && navigation.mode !== 'detail') {
    const directory = document.createElement('section');
    directory.id = 'communityDirectory';
    directory.className = 'community-directory graph-floating-panel';
    directory.innerHTML = '<div class="graph-panel-header"><span>社区详情</span><button class="graph-panel-collapse" type="button" aria-label="收起社区详情">−</button></div><div class="graph-panel-body"><input id="communitySearchInput" class="graph-text-input" type="search" placeholder="搜索社区或内部节点..."><select id="communityTypeFilter" class="graph-select"><option value="">全部实体类型</option></select><div class="community-list" id="communityList"></div><div class="graph-empty-state" id="communityEmptyState" hidden>没有匹配的社区，已保留原列表</div></div>';
    const typeFilter = directory.querySelector('#communityTypeFilter');
    [...new Set(entries.map(item => item.entityType).filter(Boolean))].sort().forEach(type => {
      const option = document.createElement('option'); option.value = type; option.textContent = type; typeFilter.appendChild(option);
    });
    const list = directory.querySelector('#communityList');
    entries.forEach(item => {
      const wrapper = document.createElement('div'); wrapper.className = 'community-list-item';
      wrapper.dataset.name = item.name || ''; wrapper.dataset.representativeNode = item.representative || '';
      wrapper.dataset.communityName = item.communityName || ''; wrapper.dataset.memberNames = JSON.stringify(item.members || []);
      wrapper.dataset.types = item.entityType || '未分类';
      const link = document.createElement('a'); link.className = 'community-item-link'; link.href = item.href;
      const name = document.createElement('span'); name.className = 'community-item-name'; name.textContent = [item.communityName,item.name].filter(Boolean).join(' · ');
      const meta = document.createElement('span'); meta.className = 'community-item-meta'; meta.textContent = `${item.count || 0} 个节点 · 主节点类型：${item.entityType || '未分类'}`;
      link.addEventListener('click', () => { wrapper.classList.add('is-loading'); meta.textContent = '正在加载社区子图...'; });
      link.append(name, meta);
      const source = document.createElement('button'); source.type = 'button'; source.className = 'community-source-link'; source.textContent = '查看原文文本块';
      source.dataset.nodeId = item.representative || ''; source.dataset.sourceBlocks = JSON.stringify(item.sourceBlocks || []);
      wrapper.append(link, source); list.appendChild(wrapper);
    });
    document.getElementById('sigma-root').appendChild(directory);
  }
  if (navigation.mode === 'detail' && navigation.overviewHref) {
    const back = document.createElement('div'); back.className = 'community-back-bar';
    const link = document.createElement('a'); link.href = navigation.overviewHref; link.textContent = '← 返回社区总览';
    back.appendChild(link);
    if (navigation.currentCommunity) {
      const meta = document.createElement('span');
      meta.textContent = `${navigation.currentCommunity.name || ''}（${navigation.currentCommunity.count || 0} 个节点）`;
      back.appendChild(meta);
    }
    document.getElementById('sigma-root').appendChild(back);
  }
})();
</script>
'''


def _sigma_html_template(page_title: str, payload_json: str, interaction_html: str) -> str:
    title = html.escape(page_title)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
html,body,#sigma-root{{width:100%;height:100%;margin:0;overflow:hidden}}body{{font-family:Inter,"Noto Sans SC",sans-serif;background:#fff;color:#171717}}#sigma-root{{position:relative}}#mynetwork{{position:absolute;inset:0}}.sigma-title,.sigma-panel,.sigma-controls{{display:none!important}}
body.sigma-obsidian{{background:#17191f}}
#sigma-clusters-layer{{position:absolute;inset:0;z-index:1;pointer-events:none;overflow:hidden}}.sigma-cluster-label{{position:absolute;transform:translate(-50%,-50%);max-width:180px;padding:3px 7px;border:1px solid currentColor;border-radius:5px;background:rgba(255,255,255,.86);font-size:11px;font-weight:700;line-height:1.25;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;box-shadow:0 1px 5px rgba(15,23,42,.08)}}
</style><script src="/api/graph-assets/graphology.umd.min.js"></script><script src="/api/graph-assets/sigma.min.js"></script></head>
  <body><div id="sigma-root"><div id="mynetwork"></div><div class="sigma-title"><h1>{title}</h1><small id="sigma-subtitle"></small><small id="sigma-stats"></small></div><aside class="sigma-panel"><div class="sigma-search">⌕<input id="sigma-search-input" placeholder="搜索节点..."></div><div id="sigma-results"></div><div id="sigma-page-links" class="sigma-page-links" hidden></div><h3>实体类型 <button id="sigma-toggle-types" title="收起或展开分类">⌄</button></h3><div id="sigma-types" hidden></div><section id="sigma-community-section" hidden><h3>社区详情</h3><div class="sigma-community-tools"><input id="sigma-community-search" type="search" placeholder="搜索社区或内部节点..."><select id="sigma-community-type"><option value="">全部类型</option></select></div><div id="sigma-community-list" class="sigma-community-list"></div><div id="sigma-community-empty" class="sigma-community-empty" hidden>没有匹配的社区，已保留原列表</div></section></aside><div class="sigma-controls"><button id="sigma-plus" title="放大">+</button><button id="sigma-minus" title="缩小">−</button><button id="sigma-fit" title="适应视图">⌂</button></div></div>
<script id="sigma-data" type="application/json">{payload_json}</script><script>
(function(){{
  const SIGMA_STATIC_PAGE_VERSION = {SIGMA_STATIC_PAGE_VERSION};
  const payload=JSON.parse(document.getElementById('sigma-data').textContent), root=document.getElementById('mynetwork');
  const Graph=window.graphology, SigmaClass=window.Sigma; if(!Graph||!SigmaClass) return;
  const navigation=payload.navigation||{{}}, isFullGraph=navigation.mode==='full';
  document.body.classList.toggle('sigma-obsidian',isFullGraph);
  const graph=new Graph.MultiDirectedGraph(); payload.nodes.forEach(n=>graph.addNode(String(n.id),{{...n,type:isFullGraph?'circle':'image',zIndex:1,hidden:false}}));
  payload.edges.forEach((e,i)=>{{if(graph.hasNode(String(e.source))&&graph.hasNode(String(e.target))){{let id=String(e.id||('edge:'+i));while(graph.hasEdge(id))id+=':'+i;graph.addDirectedEdgeWithKey(id,String(e.source),String(e.target),{{...e,color:isFullGraph?'rgba(166,174,190,.34)':e.color,opacity:isFullGraph?.6:.78,size:isFullGraph?e.size:Math.max(1.35,Number(e.size)||1.35)}})}}}});
  const selected=new Set(), selectedEdges=new Set();let hovered={{node:'',neighbors:new Set()}};
  const edgeColor=(color,opacity=.6)=>{{const value=String(color||'#c8cdd3');if(!/^#[0-9a-f]{{6}}$/i.test(value))return value;const number=parseInt(value.slice(1),16);return `rgba(${{number>>16}},${{number>>8&255}},${{number&255}},${{Math.max(0,Math.min(1,Number(opacity)))}})`}};
  const imageProgram=isFullGraph?null:SigmaClass.rendering.createNodeImageProgram({{size:{{mode:'force',value:256}},objectFit:'contain',padding:.14,keepWithinCircle:true}});
  const nodeProgramClasses=imageProgram?{{image:imageProgram}}:{{}};
  const nodeReducer=isFullGraph?null:((id,a)=>selected.size?(selected.has(id)?{{...a,highlighted:true,zIndex:2}}:{{...a,label:'',color:'#bbb',image:null,zIndex:0}}):(hovered.node?(id===hovered.node||hovered.neighbors.has(id)?{{...a,zIndex:1}}:{{...a,label:'',color:'#bbb',image:null,zIndex:0,highlighted:false}}):a));
  const edgeReducer=isFullGraph?null:((id,a)=>selectedEdges.size?(selectedEdges.has(id)?{{...a,color:'#e22653',size:3,label:a.label,forceLabel:true}}:{{...a,hidden:true}}):(selected.size?(selected.has(graph.source(id))&&selected.has(graph.target(id))?{{...a,color:'#e22653',size:2.8}}:{{...a,hidden:true}}):(hovered.node?(graph.hasExtremity(id,hovered.node)?{{...a,color:graph.getNodeAttribute(hovered.node,'color'),size:3.5}}:{{...a,hidden:true}}):{{...a,color:edgeColor(a.color,a.opacity)}})));
  const renderer=new SigmaClass(graph,root,{{nodeProgramClasses,defaultNodeType:isFullGraph?'circle':'image',defaultEdgeType:isFullGraph?'line':'arrow',defaultEdgeColor:isFullGraph?'rgba(166,174,190,.34)':'#8d97a8',minEdgeThickness:isFullGraph?1:1.7,allowInvalidContainer:true,zIndex:!isFullGraph,enableEdgeEvents:!isFullGraph,hideEdgesOnMove:isFullGraph,hideLabelsOnMove:true,renderEdgeLabels:false,labelRenderedSizeThreshold:isFullGraph?10:15,labelDensity:isFullGraph ? .035 : .07,labelGridCellSize:isFullGraph?90:60,stagePadding:30,minCameraRatio:.035,maxCameraRatio:10,labelColor:{{color:isFullGraph?'#d7dce5':'#111'}},labelFont:'Lato,"Noto Sans SC",sans-serif',labelSize:isFullGraph?12:14,nodeReducer,edgeReducer}});
  if(isFullGraph&&graph.order<=2500&&Array.isArray(payload.clusters)&&payload.clusters.length<=80){{
    const clusterDefinitions=new Map(payload.clusters.map(cluster=>[String(cluster.id),{{...cluster,positions:[]}}]));
    graph.forEachNode((_node,attributes)=>{{const cluster=clusterDefinitions.get(String(attributes.community));if(cluster)cluster.positions.push({{x:Number(attributes.x)||0,y:Number(attributes.y)||0}})}});
    clusterDefinitions.forEach(cluster=>{{if(!cluster.positions.length)return;cluster.x=cluster.positions.reduce((sum,position)=>sum+position.x,0)/cluster.positions.length;cluster.y=cluster.positions.reduce((sum,position)=>sum+position.y,0)/cluster.positions.length}});
    const clustersLayer=document.createElement('div');clustersLayer.id='sigma-clusters-layer';
    clusterDefinitions.forEach(cluster=>{{if(!cluster.positions.length)return;const label=document.createElement('div');label.className='sigma-cluster-label';label.textContent=cluster.label;label.style.color=cluster.color;cluster.element=label;clustersLayer.appendChild(label)}});
    root.insertBefore(clustersLayer,root.querySelector('.sigma-hovers'));
    const updateClusterLabels=()=>clusterDefinitions.forEach(cluster=>{{if(!cluster.element)return;const viewport=renderer.graphToViewport(cluster);cluster.element.style.left=`${{viewport.x}}px`;cluster.element.style.top=`${{viewport.y}}px`}});
    renderer.on('afterRender',updateClusterLabels);updateClusterLabels();
  }}
  const send=(message)=>window.parent&&window.parent.postMessage(message,'*'); const select=(nodes,edge='')=>{{selected.clear();selectedEdges.clear();nodes.forEach(n=>selected.add(n));if(edge)selectedEdges.add(String(edge));renderer.refresh()}};
  const focus=(nodes)=>{{const points=nodes.map(n=>renderer.getNodeDisplayData(n)).filter(Boolean);if(!points.length)return;const p=points.reduce((a,b)=>({{x:a.x+b.x,y:a.y+b.y}}),{{x:0,y:0}});renderer.getCamera().animate({{x:p.x/points.length,y:p.y/points.length,ratio:points.length>1?.3:.14}},{{duration:400}})}};
  window.__sigmaGraphRuntime={{payload,graph,renderer,selected,selectedEdges,select,focus}};
  if(!isFullGraph){{renderer.on('enterNode',({{node}})=>{{hovered={{node,neighbors:new Set(graph.neighbors(node))}};renderer.refresh()}});renderer.on('leaveNode',()=>{{hovered={{node:'',neighbors:new Set()}};renderer.refresh()}})}}
  if(!isFullGraph)renderer.on('clickStage',()=>select([])); renderer.on('clickNode',({{node}})=>{{if(!isFullGraph)select([node]);focus([node]);const n=graph.getNodeAttributes(node);send({{type:'knowledge-graph-evidence',kind:'node',id:node,sourceBlocks:n.source_blocks||[],entityTerms:[n.label||node],relationTerms:[]}})}});
  if(!isFullGraph)renderer.on('clickEdge',({{edge}})=>{{const source=graph.source(edge),target=graph.target(edge),e=graph.getEdgeAttributes(edge);select([source,target],edge);focus([source,target]);send({{type:'knowledge-graph-evidence',kind:'edge',id:e.id||edge,sourceBlocks:e.evidence_blocks|| (e.source_block?[e.source_block]:[]),entityTerms:[e.evidence_source||source,e.evidence_target||target],relationTerms:[e.relation||e.label].filter(Boolean)}})}});
  const types=document.getElementById('sigma-types'); const active=new Set(payload.types.map(t=>t.type));
  if(!isFullGraph)payload.types.forEach(t=>{{const label=document.createElement('label');label.className='sigma-type';label.innerHTML='<input type="checkbox" checked><img alt=""><span></span><small></small>';label.querySelector('img').src=t.image;label.querySelector('img').alt=t.type;label.querySelector('span').textContent=t.type;label.querySelector('small').textContent=t.count;label.querySelector('input').onchange=(event)=>{{event.target.checked?active.add(t.type):active.delete(t.type);let visible=0,visibleEdges=0;graph.forEachNode((id,a)=>{{const hidden=!active.has(a.entityType);graph.setNodeAttribute(id,'hidden',hidden);if(!hidden)visible++}});graph.forEachEdge((id,a,s,d)=>{{const hidden=graph.getNodeAttribute(s,'hidden')||graph.getNodeAttribute(d,'hidden');graph.setEdgeAttribute(id,'hidden',hidden);if(!hidden)visibleEdges++}});document.getElementById('sigma-stats').textContent=visible+' / '+payload.nodes.length+' nodes, '+visibleEdges+' / '+payload.edges.length+' edges';renderer.refresh()}};types.appendChild(label)}});
  const query=document.getElementById('sigma-search-input'), results=document.getElementById('sigma-results');query.oninput=()=>{{const q=query.value.trim().toLowerCase();results.innerHTML='';if(q.length<2)return;graph.filterNodes((id,a)=>!a.hidden&&String(a.label||id).toLowerCase().startsWith(q)).slice(0,8).forEach(id=>{{const button=document.createElement('button');button.textContent=graph.getNodeAttribute(id,'label')||id;button.onclick=()=>{{select([id]);focus([id]);query.value='';results.innerHTML=''}};results.appendChild(button)}})}};
  const pageLinks=document.getElementById('sigma-page-links');
  const addPageLink=(label,href,current=false)=>{{if(!href)return;const link=document.createElement('a');link.href=href;link.textContent=label;if(current)link.setAttribute('aria-current','page');pageLinks.appendChild(link);pageLinks.hidden=false}};
  addPageLink('全量图',navigation.allHref,navigation.mode==='full');addPageLink('社区总览',navigation.overviewHref,navigation.mode==='overview');
  const communityEntries=Array.isArray(navigation.entries)?navigation.entries:[];
  if(!isFullGraph&&communityEntries.length){{
    const section=document.getElementById('sigma-community-section'), communitySearch=document.getElementById('sigma-community-search'), communityType=document.getElementById('sigma-community-type'), communityList=document.getElementById('sigma-community-list'), communityEmpty=document.getElementById('sigma-community-empty');section.hidden=false;
    [...new Set(communityEntries.map(item=>item.entityType).filter(Boolean))].sort().forEach(value=>{{const option=document.createElement('option');option.value=value;option.textContent=value;communityType.appendChild(option)}});
    const rank=(item,term)=>{{if(!term)return 0;const name=String(item.name||'').toLowerCase(),communityName=String(item.communityName||'').toLowerCase(),members=(item.members||[]).map(value=>String(value).toLowerCase());if(name===term||communityName===term)return 5;if(name.startsWith(term)||communityName.startsWith(term))return 4;if(name.includes(term)||communityName.includes(term))return 3;if(members.some(value=>value===term))return 2;if(members.some(value=>value.includes(term)))return 1;return -1}};
    const renderCommunities=()=>{{const term=communitySearch.value.trim().toLowerCase(),type=communityType.value;let ranked=communityEntries.map((item,index)=>({{item,index,rank:rank(item,term)}})).filter(record=>!type||record.item.entityType===type);const matches=ranked.filter(record=>record.rank>=0);communityEmpty.hidden=!term||matches.length>0;if(term&&matches.length)ranked=matches;ranked.sort((a,b)=>b.rank-a.rank||a.index-b.index);communityList.innerHTML='';ranked.forEach(({{item,rank:score}})=>{{const wrapper=document.createElement('div');wrapper.className='sigma-community-item'+(score>0?' search-match':'');const link=document.createElement('a');link.href=item.href;link.textContent=[item.communityName,item.name].filter(Boolean).join(' · ');const meta=document.createElement('span');meta.className='sigma-community-meta';meta.textContent=String(item.count||0)+' 个节点 · '+String(item.entityType||'未分类');const actions=document.createElement('div');actions.className='sigma-community-actions';const focusButton=document.createElement('button');focusButton.type='button';focusButton.textContent='图中定位';focusButton.onclick=()=>{{const node=String(item.representative||'');if(graph.hasNode(node)){{select([node]);focus([node])}}}};const sourceButton=document.createElement('button');sourceButton.type='button';sourceButton.textContent='原文查找';sourceButton.onclick=()=>send({{type:'knowledge-graph-evidence',kind:'node',id:String(item.representative||''),sourceBlocks:item.sourceBlocks||[],entityTerms:[String(item.representative||item.name||'')],relationTerms:[]}});actions.append(focusButton,sourceButton);wrapper.append(link,meta,actions);communityList.appendChild(wrapper)}})}};
    communitySearch.oninput=renderCommunities;communityType.onchange=renderCommunities;renderCommunities();
  }}
  document.getElementById('sigma-plus').onclick=()=>renderer.getCamera().animatedZoom({{duration:220}});document.getElementById('sigma-minus').onclick=()=>renderer.getCamera().animatedUnzoom({{duration:220}});document.getElementById('sigma-fit').onclick=()=>renderer.getCamera().animatedReset({{duration:300}});document.getElementById('sigma-toggle-types').onclick=(event)=>{{types.hidden=!types.hidden;event.currentTarget.textContent=types.hidden?'⌄':'⌃'}};
  window.addEventListener('message',(event)=>{{const m=event.data||{{}};if(m.type!=='knowledge-graph-highlight')return;const edgeKind=['edge','relation','relationship'].includes(String(m.kind||'').toLowerCase());if(edgeKind){{let edge=graph.findEdge((id,a)=>String(a.id||id)===String(m.id||''))||'';if(!edge)edge=graph.findEdge((id,a,s,t)=>(!m.source||s===m.source||t===m.source||a.evidence_source===m.source||a.evidence_target===m.source)&&(!m.target||s===m.target||t===m.target||a.evidence_source===m.target||a.evidence_target===m.target)&&(!m.relation||a.relation===m.relation||a.label===m.relation))||'';if(edge){{const source=graph.source(edge),target=graph.target(edge);select([source,target],edge);focus([source,target]);return}}send({{type:'knowledge-graph-highlight-missing'}});return}}let node=graph.hasNode(String(m.id))?String(m.id):'';if(!node&&m.source)node=graph.findNode((id,a)=>a.label===m.source)||'';if(node){{select([node]);focus([node])}}else send({{type:'knowledge-graph-highlight-missing'}})}});
  document.getElementById('sigma-subtitle').textContent=payload.subtitle||'';document.getElementById('sigma-stats').textContent=payload.nodes.length+' nodes, '+payload.edges.length+' edges';send({{type:'knowledge-graph-ready'}});
}})();
</script>{_sigma_network_adapter_script() if interaction_html else ""}{interaction_html}
<!-- const SIGMA_STATIC_PAGE_VERSION = {SIGMA_STATIC_PAGE_VERSION}; -->
</body></html>'''


def write_sigma_graph_page(
    graph: nx.Graph,
    path: str | Path,
    graph_name: str,
    communities: Mapping[Any, int] | None = None,
    navigation: Mapping[str, Any] | None = None,
    page_title: str | None = None,
    page_subtitle: str | None = None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            build_sigma_page(
                graph,
                graph_name,
                communities,
                navigation=navigation,
                page_title=page_title,
                page_subtitle=page_subtitle,
            ),
            encoding="utf-8",
        )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _community_page_token(community_id: Any) -> str:
    token = re.sub(r"[^\w.-]+", "_", str(community_id), flags=re.UNICODE).strip("._")
    return token or "0"


def _edge_weight(attrs: Mapping[str, Any]) -> float:
    try:
        return float(attrs.get("weight", 0.5) or 0.5)
    except (TypeError, ValueError):
        return 0.5


def write_sigma_graph_pages(
    graph: nx.Graph,
    directory: str | Path,
    graph_name: str,
    communities: Mapping[Any, int] | None = None,
    community_min_size: int = 20,
    requested_page: str | None = None,
    include_detail_pages: bool = True,
) -> list[Path]:
    """Persist the Sigma full graph, community overview, and community details."""
    target_directory = Path(directory)
    target_directory.mkdir(parents=True, exist_ok=True)
    partition = dict(communities) if communities is not None else _partition(nx.Graph(graph.to_undirected()))
    for node in graph.nodes:
        partition.setdefault(node, 0)

    members: dict[Any, list[Any]] = defaultdict(list)
    for node in graph.nodes:
        members[partition[node]].append(node)
    minimum_size = max(1, int(community_min_size))
    detail_communities = sorted(
        (community_id for community_id, nodes in members.items() if len(nodes) >= minimum_size),
        key=str,
    )
    # Large graphs can contain thousands of singleton components. When some
    # communities are large enough to open, keep the overview aligned with
    # those navigation cards instead of flooding it with unopenable nodes.
    overview_communities = detail_communities or sorted(members, key=str)
    overview_enabled = bool(overview_communities)
    root_name = f"{graph_name}.sigma.html"
    overview_name = f"{graph_name}.sigma-communities.html"

    representatives: dict[Any, Any] = {}
    degrees = dict(graph.degree())
    for community_id, nodes in members.items():
        representatives[community_id] = max(
            nodes,
            key=lambda node: (degrees.get(node, 0), str(node)),
        )

    entries = []
    if detail_communities:
        for community_id in detail_communities:
            representative = representatives[community_id]
            attrs = graph.nodes[representative]
            entity_type = _text(
                attrs.get("entity_type") or attrs.get("group") or attrs.get("title") or "未分类"
            )
            entries.append({
                "id": str(community_id),
                "communityName": f"社区{community_id}",
                "name": _text(attrs.get("label") or representative),
                "representative": _text(representative),
                "count": len(members[community_id]),
                "entityType": entity_type,
                "members": [_text(node) for node in members[community_id]],
                "sourceBlocks": list(attrs.get("source_blocks") or []),
                "href": f"{graph_name}.sigma-community-{_community_page_token(community_id)}.html",
            })

    shared_navigation = {
        "allHref": root_name,
        "overviewHref": overview_name if overview_enabled else "",
        "entries": entries,
    }
    written = []
    if requested_page is None or requested_page == root_name:
        written.append(write_sigma_graph_page(
            graph,
            target_directory / root_name,
            graph_name,
            partition,
            navigation={**shared_navigation, "entries": [], "mode": "full"},
            page_title=f"{graph_name} 全量图",
            page_subtitle="全部实体与关系",
        ))
    if not overview_enabled:
        return written

    if requested_page is None or requested_page == overview_name:
        overview = nx.MultiDiGraph()
        overview_community_set = set(overview_communities)
        for community_id in overview_communities:
            community_members = members[community_id]
            representative = representatives[community_id]
            attrs = dict(graph.nodes[representative])
            attrs.update({
                "label": _text(attrs.get("label") or representative),
                "community_id": community_id,
                "community_size": len(community_members),
                "representative_node": representative,
            })
            overview.add_node(representative, **attrs)

        cross_edges: dict[tuple[Any, Any], list[tuple[Any, Any, Mapping[str, Any]]]] = defaultdict(list)
        for source, target, attrs in graph.edges(data=True):
            source_community = partition[source]
            target_community = partition[target]
            if source_community == target_community:
                continue
            if (
                source_community not in overview_community_set
                or target_community not in overview_community_set
            ):
                continue
            pair = tuple(sorted((source_community, target_community), key=str))
            cross_edges[pair].append((source, target, attrs))
        for pair, candidates in cross_edges.items():
            source_community, target_community = pair
            source_rep = representatives[source_community]
            target_rep = representatives[target_community]
            direct = [
                record for record in candidates
                if {record[0], record[1]} == {source_rep, target_rep}
            ]
            evidence_source, evidence_target, edge_attrs = max(
                direct or candidates,
                key=lambda record: _edge_weight(record[2]),
            )
            attrs = dict(edge_attrs)
            attrs.update({
                "evidence_source": evidence_source,
                "evidence_target": evidence_target,
            })
            overview.add_edge(source_rep, target_rep, **attrs)

        written.append(write_sigma_graph_page(
            overview,
            target_directory / overview_name,
            graph_name,
            {node: 0 for node in overview.nodes},
            navigation={**shared_navigation, "mode": "overview"},
            page_title=f"{graph_name} 社区总览",
            page_subtitle=f"{len(overview_communities)} 个社区及跨社区关系",
        ))
    entry_by_community = {entry["id"]: entry for entry in entries}
    for community_id in detail_communities:
        entry = entry_by_community[str(community_id)]
        if not include_detail_pages or (
            requested_page is not None and requested_page != entry["href"]
        ):
            continue
        detail_graph = graph.subgraph(members[community_id]).copy()
        written.append(write_sigma_graph_page(
            detail_graph,
            target_directory / entry["href"],
            graph_name,
            {node: 0 for node in detail_graph.nodes},
            navigation={
                "mode": "detail",
                "allHref": root_name,
                "overviewHref": overview_name,
                "entries": entries,
                "currentCommunity": {
                    "name": entry["name"],
                    "count": entry["count"],
                },
            },
            page_title=f"{entry['name']} 社区详情",
            page_subtitle=f"社区{community_id} · {entry['count']} 个节点",
        ))
    return written
