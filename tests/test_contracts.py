from __future__ import annotations

import copy
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from money_graph.analytics import independent_seed_branches, run_analysis
from money_graph.api import create_app
from money_graph.disruption import disruption_scenarios
from money_graph.ingestion import DataContractError, load_and_validate, load_config
from money_graph.motifs import detect_motifs
from money_graph.temporal import match_transactions


def write_small_dataset(directory: Path, *, amount: float = 100.0, duplicate: bool = False) -> Path:
    directory.mkdir()
    nodes = pd.DataFrame({"gid": [1, 2, 3, 4, 5], "depth": [0, 1, 1, 2, 0], "is_seed": [True, False, False, False, True]})
    edges = pd.DataFrame({"src": [1, 1, 2], "dst": [2, 3, 4], "depth": [1, 1, 2], "sum_kzt": [amount * (2 if duplicate else 1), amount, amount], "n_tx": [2 if duplicate else 1, 1, 1]})
    tx = pd.DataFrame({"src": [1, 1, 2], "dst": [2, 3, 4], "date": ["2026-07-01", "2026-07-01", "2026-07-03"], "sum_kzt": [amount, amount, amount]})
    if duplicate:
        tx = pd.concat([tx, tx.iloc[[0]]], ignore_index=True)
    nodes.to_parquet(directory / "nodes.parquet")
    edges.to_parquet(directory / "edges.parquet")
    tx.to_parquet(directory / "transactions.parquet")
    return directory


def test_money_is_exact_and_matching_rows_remain(tmp_path: Path) -> None:
    source = write_small_dataset(tmp_path / "input", amount=1_000_000.01, duplicate=True)
    loaded = load_and_validate(source)
    assert len(loaded.transactions) == 4
    assert loaded.transactions.transaction_id.nunique() == 4
    assert int(loaded.edges.sum_tiyn.sum()) == 400_000_004
    edges = pd.read_parquet(source / "edges.parquet")
    edges.loc[0, "sum_kzt"] += 0.05
    edges.to_parquet(source / "edges.parquet")
    with pytest.raises(DataContractError, match="Суммы"):
        load_and_validate(source)


@pytest.mark.parametrize("column,value", [("sum_kzt", float("nan")), ("sum_kzt", float("inf")), ("sum_kzt", 1.001)])
def test_invalid_money_is_rejected(tmp_path: Path, column: str, value: float) -> None:
    source = write_small_dataset(tmp_path / "input")
    edges = pd.read_parquet(source / "edges.parquet")
    edges.loc[0, column] = value
    edges.to_parquet(source / "edges.parquet")
    with pytest.raises(DataContractError):
        load_and_validate(source)


def test_invalid_types_and_config_are_rejected(tmp_path: Path) -> None:
    source = write_small_dataset(tmp_path / "input")
    nodes = pd.read_parquet(source / "nodes.parquet")
    nodes["gid"] = nodes.gid.astype(float)
    nodes.to_parquet(source / "nodes.parquet")
    with pytest.raises(DataContractError, match="gid"):
        load_and_validate(source)
    bad = copy.deepcopy(load_config())
    bad["priority"]["flow"] = 0.99
    path = tmp_path / "bad.yaml"
    import yaml
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(DataContractError, match="сумма весов"):
        load_config(path)


def test_fifo_never_reuses_money_and_same_day_is_ambiguous() -> None:
    tx = pd.DataFrame([
        (1, 2, "2026-07-01", 10000, "in"),
        (2, 3, "2026-07-01", 10000, "same"),
        (2, 4, "2026-07-02", 8000, "out1"),
        (2, 5, "2026-07-03", 8000, "out2"),
    ], columns=["src", "dst", "date", "sum_tiyn", "transaction_id"])
    tx["date"] = pd.to_datetime(tx.date)
    strict, ambiguous, matches, _ = match_transactions(tx, 1, 2)
    assert strict[2] == 10000
    assert ambiguous[2] >= 1
    assert sum(match["matched_tiyn"] for match in matches if match["node_id"] == "2") == 10000


def test_independent_seed_branches_distinguish_common_middle() -> None:
    shared = nx.DiGraph([(1, 3), (2, 3), (3, 4)])
    separate = nx.DiGraph([(1, 3), (2, 5), (3, 4), (5, 4)])
    assert independent_seed_branches(shared, {1, 2}, 4)["count"] == 1
    answer = independent_seed_branches(separate, {1, 2}, 4)
    assert answer["count"] == 2
    assert len(answer["paths"]) == 2


def test_motifs_have_real_edges_and_timing_status() -> None:
    graph = nx.DiGraph()
    for src, dst in [(1, 2), (2, 4), (1, 3), (3, 4), (4, 1)]:
        graph.add_edge(src, dst, sum_kzt=100.0)
    frame = pd.DataFrame({"gid": [1, 2, 3, 4], "in_deg": [1, 1, 1, 2], "out_deg": [2, 1, 1, 1], "seed_reach": [0, 1, 1, 1]})
    cfg = copy.deepcopy(load_config())
    cfg["typologies"]["fan_in_min_counterparties"] = 2
    matches = [
        {"node_id": "2", "source": "1", "target": "4", "incoming_transaction_id": "a", "outgoing_transaction_id": "b", "incoming_date": "2026-07-01", "outgoing_date": "2026-07-02", "matched_tiyn": 10000},
        {"node_id": "3", "source": "1", "target": "4", "incoming_transaction_id": "c", "outgoing_transaction_id": "d", "incoming_date": "2026-07-01", "outgoing_date": "2026-07-03", "matched_tiyn": 10000},
        {"node_id": "2", "source": "1", "target": "4", "incoming_transaction_id": "e", "outgoing_transaction_id": "f", "incoming_date": "2026-07-07", "outgoing_date": "2026-07-08", "matched_tiyn": 10000},
    ]
    _, motifs, flags = detect_motifs(graph, frame, cfg, matches, {})
    assert any(item["type"] == "scatter_gather" and item["temporal_status"] == "compatible" for item in motifs)
    assert any(item["type"] == "pass_through_chain" and item["node_ids"] == ["1", "2", "4"] for item in motifs)
    assert any(item["type"] == "cycle" for item in motifs)
    assert any(item["type"] == "repeated_route" and item["node_ids"] == ["1", "2", "4"] for item in motifs)
    assert all(graph.has_edge(int(edge["source"]), int(edge["target"])) for item in motifs for edge in item["edges"])
    assert not any(flags.values())


def test_weights_change_results_and_publishing_preserves_last_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_small_dataset(tmp_path / "input")
    output = tmp_path / "latest"
    first = run_analysis(source, output)
    previous = output.resolve()
    cfg = copy.deepcopy(load_config())
    cfg["priority"].update({"structural": 0.1, "seed_exposure": 0.1, "flow": 0.6, "typology": 0.1, "temporal": 0.1})
    import yaml
    changed_config = tmp_path / "changed.yaml"
    changed_config.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    second = run_analysis(source, output, changed_config)
    assert first["config_sha256"] != second["config_sha256"]
    old = pd.read_csv(previous / "nodes_roles.csv")
    new = pd.read_csv(output / "nodes_roles.csv")
    assert not old.priority_score.equals(new.priority_score)
    bad_output = tmp_path / "unrelated"
    bad_output.mkdir()
    (bad_output / "sentinel.txt").write_text("keep")
    with pytest.raises(DataContractError, match="перезапись запрещена"):
        run_analysis(source, bad_output)
    assert (bad_output / "sentinel.txt").read_text() == "keep"
    preserved = output.resolve()
    from money_graph import exports
    monkeypatch.setattr(exports.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("injected publication failure")))
    with pytest.raises(OSError, match="injected publication failure"):
        run_analysis(source, output)
    assert output.resolve() == preserved


def test_disruption_uses_remaining_population() -> None:
    graph = nx.DiGraph([(1, 2), (2, 3)])
    rows = disruption_scenarios(graph, {1}, [2], {1: 0, 2: 0, 3: 0})
    assert rows[0]["before"]["seed_coverage"] == 2
    assert rows[0]["after"]["seed_coverage"] == 1
    assert rows[0]["relative_seed_coverage_change"] == -0.5


def test_multi_seed_convergence_is_not_double_counted_as_typology(tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.mkdir()
    pd.DataFrame({"gid": [1, 2, 3], "depth": [0, 0, 1], "is_seed": [True, True, False]}).to_parquet(source / "nodes.parquet")
    pd.DataFrame({"src": [1, 2], "dst": [3, 3], "sum_kzt": [100.0, 100.0], "n_tx": [1, 1], "depth": [1, 1]}).to_parquet(source / "edges.parquet")
    pd.DataFrame({"src": [1, 2], "dst": [3, 3], "sum_kzt": [100.0, 100.0], "date": ["2026-07-01", "2026-07-01"]}).to_parquet(source / "transactions.parquet")
    run_analysis(source, tmp_path / "latest")
    features = pd.read_parquet(tmp_path / "latest" / "node_features.parquet").set_index("gid")
    assert features.loc[3, "seed_reach"] == 2
    assert features.loc[3, "typology_component"] == 0


def test_input_row_order_does_not_change_csv(tmp_path: Path) -> None:
    first = write_small_dataset(tmp_path / "first-input", duplicate=True)
    second = tmp_path / "second-input"
    second.mkdir()
    for name in ("nodes", "edges", "transactions"):
        pd.read_parquet(first / f"{name}.parquet").sample(frac=1, random_state=42).to_parquet(second / f"{name}.parquet")
    run_analysis(first, tmp_path / "first")
    run_analysis(second, tmp_path / "second")
    for name in ("nodes_roles.csv", "clusters.csv", "top_nodes.csv"):
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()


def test_api_ids_and_limits_are_explicit(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    source = write_small_dataset(tmp_path / "input")
    run_analysis(source, tmp_path / "latest")
    client = TestClient(create_app(tmp_path / "latest"))
    item = client.get("/api/nodes?limit=1").json()["items"][0]
    assert isinstance(item["gid"], str)
    neighborhood = client.get(f"/api/nodes/{item['gid']}/neighborhood?hops=2&max_nodes=2&max_edges=1").json()
    assert neighborhood["shown_nodes"] <= 2
    assert neighborhood["shown_edges"] <= 1
    assert any(node["gid"] == item["gid"] for node in neighborhood["nodes"])
    assert client.get("/api/health").json()["run_id"] == neighborhood["run_id"]
    assert client.get("/api/assistant/status").json()["available"] is False


def test_assistant_mock_uses_only_artifact_facts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from money_graph import assistant
    from money_graph.api import ArtifactStore

    source = write_small_dataset(tmp_path / "input")
    run_analysis(source, tmp_path / "latest")
    store = ArtifactStore(tmp_path / "latest")
    monkeypatch.setattr(assistant, "provider_status", lambda: {"available": True})
    async def valid_intent(*args: object, **kwargs: object) -> assistant.ParsedIntent:
        return assistant.INTENT_ADAPTER.validate_python({"intent": "explain_priority", "gid": "2"})
    monkeypatch.setattr(assistant, "_parse_intent", valid_intent)
    result = asyncio.run(assistant.answer("Почему 2?", store))
    assert result["facts"][0]["fact_id"] == "node:2"
    assert str(round(result["facts"][0]["priority_score"], 3)) in result["answer"]
    async def unknown_intent(*args: object, **kwargs: object) -> assistant.ParsedIntent:
        return assistant.INTENT_ADAPTER.validate_python({"intent": "explain_priority", "gid": "999"})
    monkeypatch.setattr(assistant, "_parse_intent", unknown_intent)
    assert not asyncio.run(assistant.answer("Почему 999?", store))["facts"]
