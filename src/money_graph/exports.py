"""CSV contract validation and atomic publication of immutable runs."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd

from .analytics import compute_analysis
from .disruption import disruption_scenarios, sensitivity_scenarios
from .ingestion import DataContractError, load_and_validate, load_config
from .scoring import ROLES


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_exports(nodes: pd.DataFrame, clusters: pd.DataFrame, top: pd.DataFrame, expected_nodes: int) -> None:
    required_nodes = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
    if len(nodes) != expected_nodes or nodes.gid.duplicated().any() or nodes[required_nodes].isna().any().any():
        raise DataContractError("nodes_roles.csv не прошёл проверку полноты")
    if not nodes.role.isin(ROLES).all() or not nodes.role_score.between(0, 1).all() or not nodes.priority_score.between(0, 1).all():
        raise DataContractError("Некорректные роли или scores в nodes_roles.csv")
    if not nodes.evidence.map(lambda value: 0 < len(str(value)) <= 200).all():
        raise DataContractError("Evidence должен быть непустым и не длиннее 200 символов")
    if set(nodes.cluster_id) != set(clusters.cluster_id) or int(clusters.n_nodes.sum()) != expected_nodes:
        raise DataContractError("Кластеры не покрывают все узлы")
    minimum_top = min(20, expected_nodes)
    if len(top) < minimum_top or top.gid.duplicated().any() or not top.priority_score.is_monotonic_decreasing:
        raise DataContractError("top_nodes.csv не прошёл проверку")


def run_analysis(data_dir: Path, out_dir: Path, config_path: Path | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    config = load_config(config_path)
    data_dir = data_dir.resolve()
    out_dir = out_dir.absolute()
    project_root = Path(__file__).resolve().parents[2]
    parent = out_dir.parent.resolve()
    runs_dir = parent / ".money_graph_runs"
    if out_dir == data_dir or out_dir == project_root or parent == data_dir or data_dir in parent.parents:
        raise DataContractError("Каталог результатов не должен быть исходными данными или внутри них")
    if out_dir.is_symlink() and out_dir.resolve().parent != runs_dir:
        raise DataContractError("Указатель результатов ссылается на посторонний каталог; замена запрещена")
    if out_dir.exists() and not out_dir.is_symlink() and not all((out_dir / name).is_file() for name in ("manifest.json", "nodes_roles.csv", "clusters.csv", "top_nodes.csv")):
        raise DataContractError("Существующий каталог результатов не распознан; перезапись запрещена")
    data = load_and_validate(data_dir, config)
    loaded_at = time.perf_counter()
    computed, cluster_rows, motifs, graph, details = compute_analysis(data, config)
    computed_at = time.perf_counter()
    nodes_export = computed[["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]].sort_values("gid")
    clusters_export = pd.DataFrame(cluster_rows).sort_values("cluster_id")
    top_export = (
        computed.sort_values(["priority_score", "gid"], ascending=[False, True])
        .head(50)[["gid", "role", "priority_score", "evidence", "structural_contrib", "seed_contrib", "flow_contrib", "typology_contrib", "temporal_contrib"]]
        .reset_index(drop=True)
    )
    def why(row: pd.Series) -> str:
        values = {
            "связность": row.structural_contrib,
            "связь с seed": row.seed_contrib,
            "оборот и операции": row.flow_contrib,
            "мотивы": row.typology_contrib,
            "временное совпадение": row.temporal_contrib,
        }
        leading = sorted(values.items(), key=lambda item: (-item[1], item[0]))[:3]
        drivers = ", ".join(f"{name} +{value:.2f}" for name, value in leading if value > 0)
        explanation = str(row.evidence)
        suffix = f" Приоритет {row.priority_score:.2f}; главные вклады: {drivers or 'нет выраженных вкладов'}."
        return explanation + suffix
    top_export["why"] = top_export.apply(why, axis=1)
    top_export = top_export[["gid", "role", "priority_score", "why"]]
    top_export.insert(0, "rank", top_export.index + 1)
    _validate_exports(nodes_export, clusters_export, top_export, len(data.nodes))
    disruptions = disruption_scenarios(
        graph,
        set(map(int, data.nodes.loc[data.nodes.is_seed, "gid"])),
        list(map(int, top_export.gid)),
        dict(zip(map(int, computed.gid), map(int, computed.cluster_id))),
    )
    sensitivity = sensitivity_scenarios(computed, config)
    ranked_top20 = computed.sort_values(["priority_score", "gid"], ascending=[False, True]).head(20).gid.astype(int).tolist()
    position_ranges = {str(gid): {"min": min([rank] + [item["top20_positions"][str(gid)] for item in sensitivity]),
                                  "max": max([rank] + [item["top20_positions"][str(gid)] for item in sensitivity])}
                       for rank, gid in enumerate(ranked_top20, start=1)}
    diagnostics_at = time.perf_counter()
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out_dir.name}-", dir=out_dir.parent) as temporary:
        staging = Path(temporary)
        nodes_export.to_csv(staging / "nodes_roles.csv", index=False)
        clusters_export.to_csv(staging / "clusters.csv", index=False)
        top_export.to_csv(staging / "top_nodes.csv", index=False)
        _validate_exports(
            pd.read_csv(staging / "nodes_roles.csv"), pd.read_csv(staging / "clusters.csv"),
            pd.read_csv(staging / "top_nodes.csv"), len(data.nodes),
        )
        computed.to_parquet(staging / "node_features.parquet", index=False)
        data.edges.to_parquet(staging / "graph_edges.parquet", index=False)
        data.transactions.to_parquet(staging / "transactions.parquet", index=False)
        for name, value in (("node_details.json", details), ("typologies.json", motifs),
                            ("disruption.json", disruptions), ("sensitivity.json", sensitivity),
                            ("sensitivity_summary.json", {"position_ranges": position_ranges})):
            (staging / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        elapsed = round(time.perf_counter() - started, 3)
        run_id = hashlib.sha256((str(time.time_ns()) + str(data_dir)).encode()).hexdigest()[:16]
        config_text = json.dumps(config, sort_keys=True, ensure_ascii=False, allow_nan=False)
        output_names = ("nodes_roles.csv", "clusters.csv", "top_nodes.csv", "node_features.parquet", "graph_edges.parquet", "transactions.parquet", "node_details.json", "typologies.json", "disruption.json", "sensitivity.json", "sensitivity_summary.json")
        manifest = {
            "run_id": run_id,
            "methodology_version": config["methodology_version"], "artifact_version": config["artifact_version"], "elapsed_seconds": elapsed,
            "effective_config": config, "config_sha256": hashlib.sha256(config_text.encode()).hexdigest(),
            "phase_seconds": {"loading": round(loaded_at-started, 3), "analytics": round(computed_at-loaded_at, 3), "diagnostics": round(diagnostics_at-computed_at, 3), "export": round(time.perf_counter()-diagnostics_at, 3)},
            "input": {name: {"sha256": _sha256(data_dir / f"{name}.parquet"), "rows": len(getattr(data, name))} for name in ("edges", "nodes", "transactions")},
            "output": {"nodes": len(nodes_export), "edges": len(data.edges), "transactions": len(data.transactions), "clusters": len(clusters_export), "top_nodes": len(top_export), "motifs": len(motifs)},
            "output_sha256": {name: _sha256(staging / name) for name in output_names},
            "warnings": ["Даты операций имеют точность до дня.", "Граф обрывается после depth=4.", "Входящий поток seed неполон."] + ([details[int(computed.iloc[0].gid)]["hits"]["warning"]] if details[int(computed.iloc[0].gid)]["hits"]["warning"] else []),
            "optional_status": {"motif_truncation": details[int(computed.iloc[0].gid)]["motif_search_truncated"], "hits_converged": details[int(computed.iloc[0].gid)]["hits"]["warning"] is None, "disruption_scenarios": len(disruptions), "sensitivity_scenarios": len(sensitivity)},
            "runtime": {"python": sys.version.split()[0], "platform": platform.platform(), **{name: version(name) for name in ("networkx", "pandas", "numpy", "pyarrow", "scipy", "fastapi", "pydantic")}},
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        # Publish a completed immutable run, then switch the short pointer in one rename.
        run_dir = runs_dir / run_id
        os.rename(staging, run_dir)
        old_dir = None
        if out_dir.exists() and not out_dir.is_symlink():
            old_dir = runs_dir / f"legacy-{time.time_ns()}"
            os.rename(out_dir, old_dir)
        pointer = out_dir.parent / f".{out_dir.name}-{run_id}.link"
        try:
            pointer.symlink_to(run_dir, target_is_directory=True)
            os.replace(pointer, out_dir)
        except OSError:
            pointer.unlink(missing_ok=True)
            if old_dir is not None and not out_dir.exists():
                os.rename(old_dir, out_dir)
            raise
    return manifest
