"""Orchestrate the deterministic graph analysis and preserve the public CLI API."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from .evidence import build_evidence
from .features import compute_features, independent_seed_branches
from .ingestion import DataContractError, InputData, load_and_validate, load_config
from .scoring import score_frame

__all__ = ["DataContractError", "InputData", "compute_analysis", "independent_seed_branches", "load_and_validate", "load_config", "run_analysis"]


def compute_analysis(data: InputData, config: dict[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], nx.DiGraph, dict[int, dict[str, Any]]]:
    frame, graph, community_sets, seeds, paths, matches, daily, hits_warning = compute_features(data, config)
    frame, motifs, motif_ids, motif_truncation, role_context = score_frame(frame, data, graph, config, matches, paths)
    frame, clusters, details = build_evidence(frame, data, graph, config, community_sets, seeds, paths, matches, daily, hits_warning, motif_ids, motif_truncation, role_context)
    return frame, clusters, motifs, graph, details


def run_analysis(data_dir: Path, out_dir: Path, config_path: Path | None = None) -> dict[str, Any]:
    from .exports import run_analysis as publish
    return publish(data_dir, out_dir, config_path)
