"""Deterministic role and priority scoring from precomputed features."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

from .features import percentile_positive
from .ingestion import InputData
from .motifs import detect_motifs

ROLES = ("consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral")

def score_frame(frame: pd.DataFrame, data: InputData, graph: nx.DiGraph, config: dict[str, Any], matches: list[dict[str, Any]], paths: dict[int, list[list[int]]]) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[int, list[str]], dict[str, bool], dict[str, Any]]:
    motif_labels, motifs, motif_truncation = detect_motifs(graph, frame.reset_index(), config, matches, paths)
    frame["typologies"] = [motif_labels.get(int(gid), []) for gid in frame.index]
    motif_scores: dict[int, float] = defaultdict(float)
    motif_ids: dict[int, list[str]] = defaultdict(list)
    for motif in motifs:
        kind = motif["type"]
        score = 0.0 if kind == "multi_seed_convergence" else 1.0 if motif["temporal_status"] == "compatible" else 0.7 if kind in {"cycle", "scatter_gather"} else 0.5
        for value in motif["node_ids"]:
            gid = int(value)
            motif_scores[gid] = max(motif_scores[gid], score)
            motif_ids[gid].append(motif["motif_id"])
    frame["typology_score"] = pd.Series(motif_scores, dtype=float).reindex(frame.index, fill_value=0.0)

    roles_cfg = config["roles"]
    positive_betweenness = frame.loc[frame.betweenness > 0, "betweenness"]
    betweenness_threshold = (
        float(positive_betweenness.quantile(float(roles_cfg["coordinator_betweenness_percentile"])))
        if not positive_betweenness.empty
        else None
    )
    last_date = pd.Timestamp(config["period"]["end"])
    last_inbound = data.transactions.groupby("dst").date.max().reindex(frame.index)
    frame["days_after_last_in"] = (last_date - last_inbound).dt.days.fillna(0).astype(int)
    frame["incomplete_observation_window"] = (frame.in_deg > 0) & (frame.days_after_last_in < int(config["typologies"]["temporal_max_days"]))
    weights = roles_cfg["weights"]
    frame["consolidator_score"] = np.where(
        frame.in_deg >= int(roles_cfg["consolidator_min_in_degree"]),
        weights["consolidator"]["in_degree"] * frame.in_deg_norm + weights["consolidator"]["in_kzt"] * frame.in_kzt_norm + weights["consolidator"]["in_tx"] * frame.in_tx_norm + weights["consolidator"]["seed_reach"] * percentile_positive(frame.seed_reach),
        0.0,
    )
    frame["distributor_score"] = np.where(
        frame.out_deg >= int(roles_cfg["distributor_min_out_degree"]),
        weights["distributor"]["out_degree"] * frame.out_deg_norm + weights["distributor"]["out_tx"] * frame.out_tx_norm + weights["distributor"]["out_kzt"] * frame.out_kzt_norm,
        0.0,
    )
    balance = (
        frame[["in_kzt", "out_kzt"]].min(axis=1)
        .div(frame[["in_kzt", "out_kzt"]].max(axis=1).replace(0, np.nan))
        .fillna(0.0)
    )
    transit_allowed = (
        (frame.in_kzt > 0)
        & (frame.out_kzt > 0)
        & (~frame.is_seed)
        & frame.pass_through.between(float(roles_cfg["transit_min_ratio"]), float(roles_cfg["transit_max_ratio"]))
    )
    frame["transit_score"] = np.where(transit_allowed, weights["transit"]["balance"] * balance + weights["transit"]["temporal"] * frame.temporal_ratio, 0.0)
    coordinator_allowed = (
        (frame.betweenness > 0)
        & ((frame.betweenness >= betweenness_threshold) if betweenness_threshold is not None else False)
        & ((frame.seed_reach >= 2) | (frame.neighbor_cluster_count >= 2))
    )
    frame["coordinator_score"] = np.where(
        coordinator_allowed,
        weights["coordinator"]["betweenness"] * frame.betweenness_norm + weights["coordinator"]["seed_exposure"] * frame.seed_extra_norm + weights["coordinator"]["cross_cluster"] * frame.cross_cluster_ratio,
        0.0,
    )
    terminal_allowed = (
        (frame.in_kzt > 0)
        & (frame.out_deg == 0)
        & (frame.depth < 4)
        & (frame.days_after_last_in >= int(roles_cfg["terminal_min_days_after_last_in"]))
    )
    terminal_cfg = roles_cfg["terminal_score"]
    frame["terminal_score"] = np.where(
        terminal_allowed,
        np.minimum(float(terminal_cfg["cap"]), float(terminal_cfg["base"]) + float(terminal_cfg["in_kzt"]) * frame.in_kzt_norm + float(terminal_cfg["days"]) * np.minimum(frame.days_after_last_in / int(terminal_cfg["days_scale"]), 1.0)),
        0.0,
    )
    priority_order = ["coordinator", "consolidator", "distributor", "transit", "terminal"]
    selections = []
    role_scores = []
    for gid, row in frame.iterrows():
        if bool(row.is_isolate):
            selections.append("peripheral")
            role_scores.append(0.2)
            continue
        candidates = {role: float(row[f"{role}_score"]) for role in priority_order}
        selected = max(priority_order, key=lambda role: (candidates[role], -priority_order.index(role)))
        if candidates[selected] < float(roles_cfg["minimum_score"]):
            selections.append("peripheral")
            peripheral_score = float(np.clip(1 - max(candidates.values()), 0, 1))
            # Absence of a detected role is weak evidence when the observed graph
            # ends at the depth boundary or the time window is still open.
            if bool(row.truncated_by_depth) or bool(row.incomplete_observation_window):
                peripheral_score = min(peripheral_score, float(roles_cfg["censored_role_score_cap"]))
            role_scores.append(peripheral_score)
        else:
            selections.append(selected)
            role_scores.append(float(np.clip(candidates[selected], 0, 1)))
    frame["role"] = selections
    frame["role_score"] = role_scores
    frame["peripheral_score"] = np.where(frame.role == "peripheral", frame.role_score, 0.0)

    priority = config["priority"]
    structural_weights = priority["structural_components"]
    flow_weights = priority["flow_components"]
    frame["structural_component"] = (structural_weights["betweenness"] * frame.betweenness_norm + structural_weights["pagerank"] * frame.pagerank_norm + structural_weights["cross_cluster"] * frame.cross_cluster_ratio)
    frame["seed_component"] = frame.seed_extra_norm
    frame["flow_component"] = flow_weights["turnover"] * percentile_positive(frame.in_kzt + frame.out_kzt) + flow_weights["transaction_count"] * percentile_positive(frame.in_tx + frame.out_tx)
    frame["typology_component"] = frame.typology_score
    frame["temporal_component"] = np.where(frame.is_seed, 0.0, frame.temporal_ratio)
    for column, group in (("structural_contrib", "structural"), ("seed_contrib", "seed_exposure"), ("flow_contrib", "flow"), ("typology_contrib", "typology"), ("temporal_contrib", "temporal")):
        component = "seed_component" if group == "seed_exposure" else f"{group}_component"
        frame[column] = float(priority[group]) * frame[component]
    frame["priority_score"] = (
        frame.structural_contrib + frame.seed_contrib + frame.flow_contrib + frame.typology_contrib + frame.temporal_contrib
    ).clip(0, 1)
    frame.loc[frame.is_isolate, ["priority_score", "structural_contrib", "seed_contrib", "flow_contrib", "typology_contrib", "temporal_contrib"]] = 0.0

    context = {"transit_allowed": transit_allowed, "coordinator_allowed": coordinator_allowed,
               "terminal_allowed": terminal_allowed, "betweenness_threshold": betweenness_threshold,
               "betweenness_threshold_status": "ok" if betweenness_threshold is not None else "no_positive_betweenness"}
    return frame, motifs, motif_ids, motif_truncation, context
