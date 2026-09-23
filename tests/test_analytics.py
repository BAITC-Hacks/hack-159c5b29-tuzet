from pathlib import Path

import pandas as pd

from money_graph.analytics import DataContractError, load_and_validate, run_analysis


def test_supplied_dataset_exports_valid_contract(full_artifacts: Path) -> None:
    import json
    manifest = json.loads((full_artifacts / "manifest.json").read_text())
    nodes = pd.read_csv(full_artifacts / "nodes_roles.csv")
    clusters = pd.read_csv(full_artifacts / "clusters.csv")
    top = pd.read_csv(full_artifacts / "top_nodes.csv")
    assert manifest["elapsed_seconds"] < 300
    assert len(nodes) == 2248
    assert nodes.gid.nunique() == 2248
    assert nodes.evidence.str.len().between(1, 200).all()
    assert nodes.role_score.between(0, 1).all()
    assert nodes.priority_score.between(0, 1).all()
    assert clusters.n_nodes.sum() == 2248
    assert set(nodes.cluster_id) == set(clusters.cluster_id)
    assert len(top) >= 20
    assert top.priority_score.is_monotonic_decreasing
    assert set(nodes.role) == {"consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"}
    features = pd.read_parquet(full_artifacts / "node_features.parquet")
    contributions = features[["structural_contrib", "seed_contrib", "flow_contrib", "typology_contrib", "temporal_contrib"]].sum(axis=1)
    assert (features.priority_score - contributions).abs().max() < 1e-12
    original_transactions = pd.read_parquet("data/transactions.parquet")
    saved_transactions = pd.read_parquet(full_artifacts / "transactions.parquet")
    assert len(saved_transactions) == len(original_transactions) == 4840
    assert saved_transactions.transaction_id.nunique() == len(saved_transactions)
    assert int(saved_transactions.duplicated(["src", "dst", "date", "sum_kzt"]).sum()) == 97


def test_isolated_seed_is_not_lost_or_labeled_terminal(full_artifacts: Path) -> None:
    source_nodes = pd.read_parquet("data/nodes.parquet")
    source_edges = pd.read_parquet("data/edges.parquet")
    connected = set(source_edges.src).union(source_edges.dst)
    isolate = int(source_nodes.loc[(source_nodes.is_seed) & ~source_nodes.gid.isin(connected), "gid"].iloc[0])
    result = pd.read_csv(full_artifacts / "nodes_roles.csv").set_index("gid").loc[isolate]
    assert result.role == "peripheral"
    assert result.priority_score == 0


def test_top_explanations_use_evidence_and_weighted_priority_drivers(full_artifacts: Path) -> None:
    nodes = pd.read_csv(full_artifacts / "nodes_roles.csv").set_index("gid")
    top = pd.read_csv(full_artifacts / "top_nodes.csv")
    for row in top.itertuples(index=False):
        explanation = row.why
        assert explanation.startswith(nodes.loc[row.gid, "evidence"])
        assert "Приоритет" in explanation
        assert "главные вклады:" in explanation
        assert any(label in explanation for label in ("связность", "оборот", "seed", "время", "мотивы"))


def test_censored_peripheral_score_is_capped(full_artifacts: Path) -> None:
    nodes = pd.read_csv(full_artifacts / "nodes_roles.csv")
    features = pd.read_parquet(full_artifacts / "node_features.parquet")
    merged = nodes.merge(features[["gid", "truncated_by_depth", "incomplete_observation_window"]], on="gid")
    censored_peripheral = merged.loc[
        (merged.role == "peripheral")
        & (merged.truncated_by_depth | merged.incomplete_observation_window)
    ]
    assert not censored_peripheral.empty
    assert censored_peripheral.role_score.max() <= 0.49


def test_cluster_hypotheses_name_observed_signals(full_artifacts: Path) -> None:
    clusters = pd.read_csv(full_artifacts / "clusters.csv")
    convergence = clusters.hypothesis.str.contains("достижимостью от 2+ seed", regex=False)
    assert convergence.any()
    assert clusters.loc[convergence, "hypothesis"].str.contains(
        "независимость маршрутов не проверена", regex=False
    ).all()
    assert not clusters.hypothesis.str.contains("несколько ветвей seed", regex=False).any()


def test_invalid_aggregated_transaction_sum_is_rejected(tmp_path: Path) -> None:
    edges = pd.DataFrame({"src": [1], "dst": [2], "sum_kzt": [100.0], "n_tx": [1], "depth": [1]})
    nodes = pd.DataFrame({"gid": [1, 2], "depth": [0, 1], "is_seed": [True, False]})
    tx = pd.DataFrame({"src": [1], "dst": [2], "date": ["2026-07-01"], "sum_kzt": [99.0]})
    edges.to_parquet(tmp_path / "edges.parquet")
    nodes.to_parquet(tmp_path / "nodes.parquet")
    tx.to_parquet(tmp_path / "transactions.parquet")
    try:
        load_and_validate(tmp_path)
    except DataContractError as error:
        assert "Суммы" in str(error)
    else:
        raise AssertionError("Некорректные суммы должны отклоняться")


def test_terminal_requires_observation_and_never_uses_depth_four_boundary(tmp_path: Path) -> None:
    data_dir = tmp_path / "input"
    data_dir.mkdir()
    edges = pd.DataFrame({"src": [1, 1, 1], "dst": [2, 3, 4], "sum_kzt": [100.0, 100.0, 100.0], "n_tx": [1, 1, 1], "depth": [1, 1, 1]})
    nodes = pd.DataFrame({"gid": [1, 2, 3, 4], "depth": [0, 1, 4, 1], "is_seed": [True, False, False, False]})
    tx = pd.DataFrame({"src": [1, 1, 1], "dst": [2, 3, 4], "date": ["2026-07-01", "2026-07-01", "2026-07-04"], "sum_kzt": [100.0, 100.0, 100.0]})
    edges.to_parquet(data_dir / "edges.parquet")
    nodes.to_parquet(data_dir / "nodes.parquet")
    tx.to_parquet(data_dir / "transactions.parquet")
    run_analysis(data_dir, tmp_path / "run")
    result = pd.read_csv(tmp_path / "run" / "nodes_roles.csv").set_index("gid")
    assert result.loc[2, "role"] == "terminal"
    assert result.loc[3, "role"] != "terminal"


def test_same_inputs_keep_scoring_exports_identical(tmp_path: Path, full_artifacts: Path) -> None:
    second = tmp_path / "second"
    run_analysis(Path("data"), second)
    for filename in ("nodes_roles.csv", "clusters.csv", "top_nodes.csv", "node_details.json", "typologies.json", "disruption.json", "sensitivity.json"):
        assert (full_artifacts / filename).read_bytes() == (second / filename).read_bytes()
