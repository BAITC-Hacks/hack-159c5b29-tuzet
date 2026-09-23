"""Removal experiments and ranking-weight sensitivity on the observed graph."""
from __future__ import annotations

from typing import Any

import networkx as nx
import pandas as pd


def _reachable(graph: nx.DiGraph, sources: set[int]) -> set[int]:
    seen = set(sources) & set(graph)
    stack = list(seen)
    while stack:
        node = stack.pop()
        for neighbor in graph.successors(node):
            if neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return seen


def _snapshot(graph: nx.DiGraph, seeds: set[int], cluster_ids: dict[int, int]) -> dict[str, int]:
    components = list(nx.weakly_connected_components(graph))
    seed_reach = _reachable(graph, seeds)
    directed_seed_pairs = sum(target in _reachable(graph, {source}) for source in seeds for target in seeds if target != source)
    community_sources: dict[int, set[int]] = {}
    for node in graph:
        community_sources.setdefault(cluster_ids[node], set()).add(node)
    linked_pairs = 0
    for community, sources in community_sources.items():
        reached_communities = {cluster_ids[node] for node in _reachable(graph, sources)}
        linked_pairs += len(reached_communities - {community})
    return {
        "largest_component": max((len(item) for item in components), default=0),
        "components": len(components),
        "isolates": nx.number_of_isolates(graph),
        "seed_coverage": len(seed_reach),
        "directed_seed_pairs": directed_seed_pairs,
        "directed_community_pairs": linked_pairs,
    }


def disruption_scenarios(graph: nx.DiGraph, seeds: set[int], ranked: list[int], cluster_ids: dict[int, int]) -> list[dict[str, Any]]:
    scenarios = [([node], "individual") for node in ranked[:20]]
    scenarios.extend((ranked[:count], "cumulative") for count in (1, 3, 5, 10))
    results = []
    for removed, kind in scenarios:
        removed_set = set(removed)
        remaining_seeds = seeds - removed_set
        before = _snapshot(graph, remaining_seeds, cluster_ids)
        candidate = graph.copy()
        candidate.remove_nodes_from(removed)
        after = _snapshot(candidate, remaining_seeds, cluster_ids)
        # Compare the same remaining-client population on both sides.
        comparable_before = len(_reachable(graph, remaining_seeds) - removed_set)
        comparable_after = after["seed_coverage"]
        before["seed_coverage"] = comparable_before
        results.append({
            "kind": kind, "removed_gids": [str(node) for node in removed],
            "before": before, "after": after,
            "relative_seed_coverage_change": None if comparable_before == 0 else comparable_after / comparable_before - 1,
        })
    return results


def sensitivity_scenarios(frame: pd.DataFrame, config: dict[str, Any]) -> list[dict[str, Any]]:
    groups = ("structural", "seed_exposure", "flow", "typology", "temporal")
    components = {group: frame[("seed" if group == "seed_exposure" else group) + "_component"].to_numpy() for group in groups}
    original = frame.sort_values(["priority_score", "gid"], ascending=[False, True]).gid.astype(int).tolist()
    top20 = set(original[:20])
    records = []
    for group in groups:
        for factor in (0.8, 1.2):
            weights = {name: float(config["priority"][name]) * (factor if name == group else 1.0) for name in groups}
            total = sum(weights.values())
            scores = sum(weights[name] / total * components[name] for name in groups)
            ranked = frame.assign(scenario_score=scores).sort_values(["scenario_score", "gid"], ascending=[False, True]).gid.astype(int).tolist()
            changed = set(ranked[:20])
            records.append({
                "group": group, "factor": factor,
                "overlap_top20": len(top20 & changed),
                "entered_gids": [str(gid) for gid in sorted(changed - top20)],
                "left_gids": [str(gid) for gid in sorted(top20 - changed)],
                "top20_positions": {str(gid): ranked.index(gid) + 1 for gid in original[:20]},
                "max_position_change": max(abs(ranked.index(gid) - original.index(gid)) for gid in original[:20]),
            })
    return records
