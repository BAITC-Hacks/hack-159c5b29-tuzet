"""Directed graph, flow, centrality, community and seed features."""
from __future__ import annotations

from collections import defaultdict
from itertools import pairwise
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

from .ingestion import InputData
from .temporal import match_transactions


def build_graph(data: InputData) -> nx.DiGraph:
    graph = nx.DiGraph()
    for row in data.nodes.itertuples(index=False):
        graph.add_node(int(row.gid), depth=int(row.depth), is_seed=bool(row.is_seed))
    for row in data.edges.itertuples(index=False):
        graph.add_edge(int(row.src), int(row.dst), sum_kzt=float(row.sum_kzt), sum_tiyn=int(row.sum_tiyn), weight=int(row.sum_tiyn), n_tx=int(row.n_tx), depth=int(row.depth))
    return graph


def percentile_positive(series: pd.Series) -> pd.Series:
    result = pd.Series(0.0, index=series.index)
    positive = series > 0
    if positive.any():
        result.loc[positive] = series.loc[positive].rank(pct=True, method="average")
    return result.clip(0, 1)


def _hhi(values: pd.Series) -> float:
    total = float(values.sum())
    return float(((values / total) ** 2).sum()) if total else 0.0


def _seed_features(graph: nx.DiGraph, seeds: list[int]) -> tuple[dict[int, set[int]], dict[int, int], dict[int, list[list[int]]]]:
    reachable: dict[int, set[int]] = {node: set() for node in graph.nodes}
    distance: dict[int, int] = {node: 999 for node in graph.nodes}
    paths: dict[int, list[list[int]]] = defaultdict(list)
    for seed in sorted(seeds):
        lengths = nx.single_source_shortest_path_length(graph, seed, cutoff=4)
        for node, length in lengths.items():
            if node != seed:
                reachable[node].add(seed)
                distance[node] = min(distance[node], length)
    for node, sources in reachable.items():
        for seed in sorted(sources, key=lambda source: (nx.shortest_path_length(graph, source, node), source))[:5]:
            try:
                paths[node].append(nx.shortest_path(graph, seed, node))
            except nx.NetworkXNoPath:
                pass
        paths[node].sort(key=lambda path: (len(path), path))
    return reachable, distance, paths


def _communities(graph: nx.DiGraph, config: dict[str, Any]) -> tuple[dict[int, int], list[set[int]]]:
    projected = nx.Graph()
    projected.add_nodes_from(sorted(graph.nodes))
    for source, target, attrs in graph.edges(data=True):
        existing = projected.get_edge_data(source, target, {}).get("weight", 0.0)
        projected.add_edge(source, target, weight=existing + float(attrs["sum_kzt"]))
    raw = nx.community.louvain_communities(
        projected,
        weight="weight",
        seed=int(config["community"]["seed"]),
        resolution=float(config["community"]["resolution"]),
    )
    ordered = sorted((set(group) for group in raw), key=lambda group: (-len(group), min(group)))
    ids = {node: index for index, group in enumerate(ordered) for node in group}
    return ids, ordered


def independent_seed_branches(graph: nx.DiGraph, seeds: set[int], target: int) -> dict[str, Any]:
    """Vertex-disjoint directed branches on the full observed graph, not a four-hop search."""
    possible = (nx.ancestors(graph, target) | {target})
    sources = sorted((seeds & possible) - {target})
    if not sources:
        return {"count": 0, "paths": []}
    capacity = len(sources)
    network = nx.DiGraph()
    origin = ("source", -1)
    for node in sorted(possible):
        network.add_edge(("in", node), ("out", node), capacity=capacity if node == target else 1)
    for source, destination in sorted(graph.subgraph(possible).edges()):
        network.add_edge(("out", source), ("in", destination), capacity=capacity)
    for seed in sources:
        network.add_edge(origin, ("in", seed), capacity=1)
    value, flow = nx.maximum_flow(network, origin, ("in", target), flow_func=nx.algorithms.flow.edmonds_karp)
    remaining = nx.DiGraph()
    remaining.add_edges_from((node, neighbor, {"capacity": int(amount)}) for node, neighbors in flow.items() for neighbor, amount in neighbors.items() if amount > 0)
    paths: list[list[str]] = []
    for seed in sources:
        if not remaining.has_edge(origin, ("in", seed)):
            continue
        try:
            flow_path = nx.shortest_path(remaining, ("in", seed), ("in", target))
        except nx.NetworkXNoPath:
            continue
        for left, right in pairwise(flow_path):
            remaining[left][right]["capacity"] -= 1
            if remaining[left][right]["capacity"] == 0:
                remaining.remove_edge(left, right)
        remaining.remove_edge(origin, ("in", seed))
        paths.append([str(node) for kind, node in flow_path if kind == "in"])
    return {"count": int(value), "paths": paths}


def compute_features(data: InputData, config: dict[str, Any]) -> tuple[pd.DataFrame, nx.DiGraph, list[set[int]], list[int], dict[int, list[list[int]]], list[dict[str, Any]], dict[int, dict[str, Any]], str | None]:
    graph = build_graph(data)
    in_sum_tiyn = data.edges.groupby("dst").sum_tiyn.sum()
    out_sum_tiyn = data.edges.groupby("src").sum_tiyn.sum()
    in_tx = data.edges.groupby("dst").n_tx.sum()
    out_tx = data.edges.groupby("src").n_tx.sum()
    amounts_in = data.transactions.groupby("dst").sum_kzt.agg(["mean", "median"])
    amounts_out = data.transactions.groupby("src").sum_kzt.agg(["mean", "median"])
    in_hhi = data.edges.groupby("dst").sum_kzt.apply(_hhi)
    out_hhi = data.edges.groupby("src").sum_kzt.apply(_hhi)
    pagerank = nx.pagerank(graph, weight="sum_kzt")
    betweenness = nx.betweenness_centrality(graph, weight=None, normalized=True)
    hits_warning = None
    try:
        hubs, authorities = nx.hits(graph, max_iter=300, tol=1e-8, normalized=True, nstart={gid: 1 / len(graph) for gid in graph})
    except (nx.PowerIterationFailedConvergence, ValueError) as error:
        hubs, authorities = {}, {}
        hits_warning = f"HITS не сошёлся: {type(error).__name__}"
    cluster_ids, community_sets = _communities(graph, config)
    seeds = list(map(int, data.nodes.loc[data.nodes.is_seed, "gid"]))
    reach, seed_distance, paths = _seed_features(graph, seeds)
    temporal_cfg = config["typologies"]
    strict_amount, same_day, matches, daily = match_transactions(
        data.transactions, int(temporal_cfg["temporal_min_days"]), int(temporal_cfg["temporal_max_days"]),
        synchronous_min_counterparties=int(temporal_cfg["synchronous_min_counterparties"]),
        burst_min_operations=int(temporal_cfg["burst_min_operations"]), burst_multiplier=float(temporal_cfg["burst_multiplier"]),
    )

    frame = data.nodes.set_index("gid").copy()
    frame["in_deg"] = pd.Series(dict(graph.in_degree())).reindex(frame.index, fill_value=0).astype(int)
    frame["out_deg"] = pd.Series(dict(graph.out_degree())).reindex(frame.index, fill_value=0).astype(int)
    for name, source in (("in_tiyn", in_sum_tiyn), ("out_tiyn", out_sum_tiyn), ("in_tx", in_tx), ("out_tx", out_tx)):
        frame[name] = source.reindex(frame.index, fill_value=0)
    frame["in_kzt"] = frame.in_tiyn / 100
    frame["out_kzt"] = frame.out_tiyn / 100
    frame["pagerank"] = pd.Series(pagerank).reindex(frame.index, fill_value=0.0)
    frame["betweenness"] = pd.Series(betweenness).reindex(frame.index, fill_value=0.0)
    frame["hits_hub"] = pd.Series(hubs, dtype=float).reindex(frame.index)
    frame["hits_authority"] = pd.Series(authorities, dtype=float).reindex(frame.index)
    frame["in_mean_kzt"] = amounts_in["mean"].reindex(frame.index, fill_value=0.0)
    frame["in_median_kzt"] = amounts_in["median"].reindex(frame.index, fill_value=0.0)
    frame["out_mean_kzt"] = amounts_out["mean"].reindex(frame.index, fill_value=0.0)
    frame["out_median_kzt"] = amounts_out["median"].reindex(frame.index, fill_value=0.0)
    frame["in_hhi"] = in_hhi.reindex(frame.index, fill_value=0.0)
    frame["out_hhi"] = out_hhi.reindex(frame.index, fill_value=0.0)
    frame["largest_in_counterparty_share"] = data.edges.groupby("dst").sum_tiyn.max().reindex(frame.index, fill_value=0).div(frame.in_tiyn.replace(0, np.nan)).fillna(0.0)
    frame["largest_out_counterparty_share"] = data.edges.groupby("src").sum_tiyn.max().reindex(frame.index, fill_value=0).div(frame.out_tiyn.replace(0, np.nan)).fillna(0.0)
    frame["cluster_id"] = pd.Series(cluster_ids).reindex(frame.index).astype(int)
    frame["seed_reach"] = pd.Series({node: len(sources) for node, sources in reach.items()}).reindex(frame.index, fill_value=0).astype(int)
    frame["min_seed_distance"] = pd.Series(seed_distance).reindex(frame.index, fill_value=999).replace(999, np.nan)
    frame["temporal_matched_tiyn"] = pd.Series(strict_amount, dtype="int64").reindex(frame.index, fill_value=0).astype("int64")
    frame["temporal_matched_kzt"] = frame.temporal_matched_tiyn / 100
    frame["same_day_ambiguous_count"] = pd.Series(same_day).reindex(frame.index, fill_value=0).astype(int)
    frame["temporal_ratio"] = (
        frame.temporal_matched_tiyn.div(frame.out_tiyn.replace(0, np.nan)).clip(upper=1.0).fillna(0.0)
    )
    frame["pass_through"] = np.where(frame.in_kzt > 0, frame.out_kzt / frame.in_kzt, np.nan)
    frame["truncated_by_depth"] = (frame.depth == 4) & (frame.out_deg == 0)
    frame["is_isolate"] = (frame.in_deg == 0) & (frame.out_deg == 0)
    frame["synchronous_fan_in_days"] = pd.Series({gid: item["synchronous_fan_in_days"] for gid, item in daily.items()}).reindex(frame.index, fill_value=0).astype(int)
    frame["synchronous_fan_out_days"] = pd.Series({gid: item["synchronous_fan_out_days"] for gid, item in daily.items()}).reindex(frame.index, fill_value=0).astype(int)
    frame["burst_days"] = pd.Series({gid: item["burst_days"] for gid, item in daily.items()}).reindex(frame.index, fill_value=0).astype(int)
    frame["largest_day_share"] = pd.Series({gid: item["largest_day_share"] for gid, item in daily.items()}).reindex(frame.index, fill_value=0.0)
    frame["in_kzt_norm"] = percentile_positive(frame.in_kzt)
    frame["out_kzt_norm"] = percentile_positive(frame.out_kzt)
    frame["in_deg_norm"] = percentile_positive(frame.in_deg)
    frame["out_deg_norm"] = percentile_positive(frame.out_deg)
    frame["in_tx_norm"] = percentile_positive(frame.in_tx)
    frame["out_tx_norm"] = percentile_positive(frame.out_tx)
    frame["pagerank_norm"] = percentile_positive(frame.pagerank.where(~frame.is_isolate, 0.0))
    frame["betweenness_norm"] = percentile_positive(frame.betweenness)
    frame["seed_extra_norm"] = percentile_positive((frame.seed_reach - 1).clip(lower=0))

    external = []
    neighbor_clusters = []
    for gid in frame.index:
        own = int(frame.loc[gid, "cluster_id"])
        cross_sum = 0.0
        total = 0.0
        neighbors = set()
        for _, target, attrs in graph.out_edges(int(gid), data=True):
            value = float(attrs["sum_kzt"])
            total += value
            if cluster_ids[target] != own:
                cross_sum += value
                neighbors.add(cluster_ids[target])
        for source, _, attrs in graph.in_edges(int(gid), data=True):
            value = float(attrs["sum_kzt"])
            total += value
            if cluster_ids[source] != own:
                cross_sum += value
                neighbors.add(cluster_ids[source])
        external.append(cross_sum / total if total else 0.0)
        neighbor_clusters.append(len(neighbors))
    frame["cross_cluster_ratio"] = external
    frame["neighbor_cluster_count"] = neighbor_clusters
    frame["cross_cluster_norm"] = percentile_positive(frame.cross_cluster_ratio)

    return frame, graph, community_sets, seeds, paths, matches, daily, hits_warning
