"""Bounded structural motifs with explicit evidence and temporal status."""
from __future__ import annotations

from collections import defaultdict
from itertools import pairwise
from typing import Any

import networkx as nx
import pandas as pd


def detect_motifs(graph: nx.DiGraph, frame: pd.DataFrame, config: dict[str, Any], matches: list[dict[str, Any]], seed_paths: dict[int, list[list[int]]]) -> tuple[dict[int, list[str]], list[dict[str, Any]], dict[str, bool]]:
    limits = config["typologies"]
    labels: dict[int, set[str]] = defaultdict(set)
    records: list[dict[str, Any]] = []
    truncation = {"cycle": False, "scatter_gather": False, "pass_through_chain": False}
    by_middle: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        by_middle[int(match["node_id"])].append(match)
    for candidates in by_middle.values():
        candidates.sort(key=lambda item: (
            item["incoming_date"], item["outgoing_date"],
            item["incoming_transaction_id"], item["outgoing_transaction_id"],
        ))

    def compatible_path(path: list[int]) -> tuple[list[str], int, list[str]] | None:
        candidates = [match for match in by_middle[path[1]] if int(match["source"]) == path[0] and int(match["target"]) == path[2]]
        failed: set[tuple[int, str]] = set()

        def continuation(index: int, incoming_id: str) -> list[dict[str, Any]] | None:
            if index == len(path) - 1:
                return []
            state = (index, incoming_id)
            if state in failed:
                return None
            for match in by_middle[path[index]]:
                if (int(match["source"]) != path[index - 1]
                        or int(match["target"]) != path[index + 1]
                        or match["incoming_transaction_id"] != incoming_id):
                    continue
                tail = continuation(index + 1, match["outgoing_transaction_id"])
                if tail is not None:
                    return [match, *tail]
            failed.add(state)
            return None

        for first in candidates:
            tail = continuation(2, first["outgoing_transaction_id"])
            if tail is not None:
                sequence = [first, *tail]
                ids = [first["incoming_transaction_id"], *[match["outgoing_transaction_id"] for match in sequence]]
                return ids, min(int(match["matched_tiyn"]) for match in sequence), [first["incoming_date"], sequence[-1]["outgoing_date"]]
        return None

    def add(kind: str, nodes: list[int], edges: list[tuple[int, int]], *, txids: list[str] | None = None,
            amount_tiyn: int = 0, dates: list[str] | None = None,
            confirmation_route: list[int] | None = None,
            confirmations: list[dict[str, Any]] | None = None) -> None:
        record = {
            "motif_id": f"m{len(records) + 1}", "type": kind,
            "node_ids": [str(gid) for gid in nodes],
            "edges": [{"source": str(source), "target": str(target), "sum_kzt": float(graph[source][target]["sum_kzt"]),
                       "n_tx": int(graph[source][target].get("n_tx", 0))} for source, target in edges],
            "metrics": {"compatible_tiyn": amount_tiyn, "compatible_kzt": amount_tiyn / 100,
                        "dates": dates or [],
                        "confirmation_route": [str(gid) for gid in confirmation_route] if confirmation_route else [],
                        "confirmations": confirmations or []},
            "temporal_status": "compatible" if txids else "structural",
            "supporting_transaction_ids": list(dict.fromkeys(txids or [])),
            "limitations": ["Совместимость по датам и суммам не доказывает происхождение конкретных денег."] if txids else ["Наблюдается структура связей; временная последовательность не подтверждена."],
        }
        records.append(record)
        for gid in nodes:
            labels[gid].add(kind)

    for row in frame.itertuples(index=False):
        gid = int(row.gid)
        if row.in_deg >= int(limits["fan_in_min_counterparties"]):
            sources = sorted(graph.predecessors(gid))
            add("fan_in", [*sources, gid], [(source, gid) for source in sources])
        if row.out_deg >= int(limits["fan_out_min_counterparties"]):
            targets = sorted(graph.successors(gid))
            add("fan_out", [gid, *targets], [(gid, target) for target in targets])
        if row.seed_reach >= 2:
            paths = seed_paths.get(gid, [])
            edges = sorted({edge for path in paths for edge in pairwise(path)})
            if edges:
                add("multi_seed_convergence", sorted({gid for pair in edges for gid in pair}), edges)

    for target in sorted(graph):
        by_source: dict[int, set[int]] = defaultdict(set)
        for middle in sorted(graph.predecessors(target)):
            for source in graph.predecessors(middle):
                if source != target:
                    by_source[source].add(middle)
        for source in sorted(by_source):
            middles = sorted(by_source[source])
            if len(middles) < int(limits["scatter_min_branches"]):
                continue
            if sum(record["type"] == "scatter_gather" for record in records) >= int(limits["max_scatter_gather"]):
                truncation["scatter_gather"] = True
                break
            edges = [(source, middle) for middle in middles] + [(middle, target) for middle in middles]
            supports = [compatible_path([source, middle, target]) for middle in middles]
            supports = [support for support in supports if support is not None]
            confirmed = len(supports) >= int(limits["scatter_min_branches"])
            add("scatter_gather", [source, *middles, target], edges,
                txids=[txid for support in supports for txid in support[0]] if confirmed else None,
                amount_tiyn=sum(support[1] for support in supports) if confirmed else 0,
                dates=sorted({date for support in supports for date in support[2]}) if confirmed else None)
        if truncation["scatter_gather"]:
            break

    cycle_seen: set[tuple[int, ...]] = set()
    for cycle in nx.simple_cycles(graph, length_bound=int(limits["cycle_max_edges"])):
        if len(cycle) < int(limits["cycle_min_edges"]):
            continue
        index = cycle.index(min(cycle))
        key = tuple(cycle[index:] + cycle[:index])
        cycle_seen.add(key)
        if len(cycle_seen) > int(limits["max_cycles"]):
            truncation["cycle"] = True
            break
    for cycle in sorted(cycle_seen)[:int(limits["max_cycles"])]:
        confirmations = []
        for index in range(len(cycle)):
            rotation = [*cycle[index:], *cycle[:index]]
            route = [*rotation, rotation[0]]
            support = compatible_path(route)
            if support is not None:
                confirmations.append((support, route))
        chosen = min(confirmations, key=lambda item: (item[0][2][0], item[0][2][-1], item[0][0], item[1])) if confirmations else None
        support, confirmation_route = chosen if chosen else (None, None)
        add("cycle", list(cycle), list(zip(cycle, cycle[1:] + cycle[:1])),
            txids=support[0] if support else None, amount_tiyn=support[1] if support else 0,
            dates=support[2] if support else None, confirmation_route=confirmation_route)

    # A compatible chain requires two consecutive FIFO matches sharing a transaction.
    chains_seen: set[tuple[str, ...]] = set()
    next_by_in: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        next_by_in[match["incoming_transaction_id"]].append(match)
    for first in matches:
        stack = [(first, [first])]
        while stack:
            current, sequence = stack.pop()
            txids = [sequence[0]["incoming_transaction_id"], *[step["outgoing_transaction_id"] for step in sequence]]
            if len(sequence) >= int(limits["chain_min_edges"]) - 1:
                key = tuple(txids)
                if key not in chains_seen:
                    chains_seen.add(key)
                    if len(chains_seen) > int(limits["max_chains"]):
                        truncation["pass_through_chain"] = True
                        break
                    nodes = [int(sequence[0]["source"]), *[int(step["node_id"]) for step in sequence], int(sequence[-1]["target"])]
                    if len(nodes) == len(set(nodes)):
                        edges = list(pairwise(nodes))
                        amount = min(int(step["matched_tiyn"]) for step in sequence)
                        add("pass_through_chain", nodes, edges, txids=txids, amount_tiyn=amount,
                            dates=[sequence[0]["incoming_date"], sequence[-1]["outgoing_date"]],
                            confirmation_route=nodes)
            if len(sequence) < int(limits["chain_max_edges"]) - 1:
                for following in next_by_in.get(current["outgoing_transaction_id"], []):
                    if following["node_id"] not in [step["node_id"] for step in sequence]:
                        stack.append((following, [*sequence, following]))
        if truncation["pass_through_chain"]:
            break

    # Two distinct compatible occurrences of the same path, with disjoint transactions.
    chain_groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["type"] == "pass_through_chain":
            chain_groups[tuple(record["node_ids"])].append(record)
    for path, group in sorted(chain_groups.items()):
        chosen: list[dict[str, Any]] = []
        used: set[str] = set()
        starts: set[str] = set()
        for record in sorted(group, key=lambda item: (
                *item["metrics"]["dates"], item["supporting_transaction_ids"])):
            txids = set(record["supporting_transaction_ids"])
            start_date = record["metrics"]["dates"][0]
            if txids.isdisjoint(used) and start_date not in starts:
                chosen.append(record)
                used.update(txids)
                starts.add(start_date)
        if len(chosen) >= int(limits["repeated_min_occurrences"]):
            confirmations = [{"start_date": item["metrics"]["dates"][0],
                              "end_date": item["metrics"]["dates"][-1],
                              "compatible_tiyn": item["metrics"]["compatible_tiyn"],
                              "transaction_ids": item["supporting_transaction_ids"]}
                             for item in chosen]
            add("repeated_route", [int(gid) for gid in path],
                [(int(a), int(b)) for a, b in pairwise(path)],
                txids=[txid for item in chosen for txid in item["supporting_transaction_ids"]],
                amount_tiyn=sum(item["compatible_tiyn"] for item in confirmations),
                dates=sorted({day for item in chosen for day in item["metrics"]["dates"]}),
                confirmation_route=[int(gid) for gid in path], confirmations=confirmations)
    return {gid: sorted(kinds) for gid, kinds in labels.items()}, records, truncation
