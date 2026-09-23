"""Regressions found during the independent acceptance review."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import httpx
import networkx as nx
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from money_graph import assistant, exports
from money_graph.api import create_app
from money_graph.ingestion import DataContractError, load_config
from money_graph.motifs import detect_motifs


def _source(directory: Path) -> Path:
    directory.mkdir()
    pd.DataFrame({"gid": [1, 2], "depth": [0, 1], "is_seed": [True, False]}).to_parquet(directory / "nodes.parquet")
    pd.DataFrame({"src": [1], "dst": [2], "depth": [1], "sum_kzt": [100.0], "n_tx": [1]}).to_parquet(directory / "edges.parquet")
    pd.DataFrame({"src": [1], "dst": [2], "date": ["2026-07-01"], "sum_kzt": [100.0]}).to_parquet(directory / "transactions.parquet")
    return directory


@pytest.mark.parametrize("path,value", [
    (("priority", "structural_components"), {"unknown": 1.0}),
    (("typologies", "temporal_min_days"), 1.5),
    (("typologies", "temporal_min_days"), True),
    (("typologies", "chain_min_edges"), 1),
    (("typologies", "scatter_min_branches"), 1),
    (("roles", "transit_max_ratio"), float("inf")),
])
def test_invalid_configuration_fails_before_data_read(tmp_path: Path, path: tuple[str, str], value: object) -> None:
    config = copy.deepcopy(load_config())
    config[path[0]][path[1]] = value
    config_path = tmp_path / "bad.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(DataContractError, match=path[1]):
        exports.run_analysis(tmp_path / "missing-data", tmp_path / "latest", config_path)
    assert not (tmp_path / "latest").exists()


def test_packaged_and_project_config_are_semantically_equal() -> None:
    root = Path(__file__).resolve().parents[1]
    project = yaml.safe_load((root / "config/scoring.yaml").read_text())
    packaged = yaml.safe_load((root / "src/money_graph/scoring.yaml").read_text())
    assert project == packaged
    assert load_config()["methodology_version"] == "1.2.2"


def test_demo_accepts_custom_scoring_config(tmp_path: Path) -> None:
    from money_graph.cli import parser

    args = parser().parse_args([
        "demo", "--data", str(tmp_path / "data"), "--out", str(tmp_path / "out"),
        "--config", str(tmp_path / "scoring.yaml"),
    ])
    assert args.config == tmp_path / "scoring.yaml"


def _frame(nodes: list[int], graph: nx.DiGraph) -> pd.DataFrame:
    return pd.DataFrame({"gid": nodes, "in_deg": [graph.in_degree(node) for node in nodes],
                         "out_deg": [graph.out_degree(node) for node in nodes],
                         "seed_reach": [0] * len(nodes)})


def _match(node: int, source: int, target: int, incoming: str, outgoing: str,
           start: str, end: str, amount: int = 10000) -> dict[str, object]:
    return {"node_id": str(node), "source": str(source), "target": str(target),
            "incoming_transaction_id": incoming, "outgoing_transaction_id": outgoing,
            "incoming_date": start, "outgoing_date": end, "matched_tiyn": amount}


def test_cycle_uses_valid_rotation_and_ordered_transaction_witness() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from([(1, 2), (2, 3), (3, 1)], sum_kzt=100.0)
    matches = [_match(3, 2, 1, "a", "b", "2026-07-01", "2026-07-02"),
               _match(1, 3, 2, "b", "c", "2026-07-02", "2026-07-03")]
    _, records, _ = detect_motifs(graph, _frame([1, 2, 3], graph), load_config(), matches, {})
    cycle = next(record for record in records if record["type"] == "cycle")
    assert cycle["temporal_status"] == "compatible"
    assert cycle["metrics"]["confirmation_route"] == ["2", "3", "1", "2"]
    assert cycle["supporting_transaction_ids"] == ["a", "b", "c"]


def test_cycle_searches_past_a_dead_continuation() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from([(1, 2), (2, 3), (3, 4), (4, 1)], sum_kzt=100.0)
    matches = [_match(2, 1, 3, "a", "b", "2026-07-01", "2026-07-02"),
               _match(3, 2, 4, "b", "dead", "2026-07-02", "2026-07-03"),
               _match(3, 2, 4, "b", "good", "2026-07-02", "2026-07-03"),
               _match(4, 3, 1, "good", "end", "2026-07-03", "2026-07-04")]
    _, records, _ = detect_motifs(graph, _frame([1, 2, 3, 4], graph), load_config(), matches, {})
    cycle = next(record for record in records if record["type"] == "cycle")
    assert cycle["temporal_status"] == "compatible"
    assert cycle["supporting_transaction_ids"] == ["a", "b", "good", "end"]


def test_cycle_chooses_earliest_complete_confirmation_across_rotations() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from([(1, 2), (2, 3), (3, 1)], sum_kzt=100.0)
    matches = [
        _match(2, 1, 3, "late-a", "late-b", "2026-07-10", "2026-07-11"),
        _match(3, 2, 1, "late-b", "late-c", "2026-07-11", "2026-07-12"),
        _match(3, 2, 1, "early-a", "early-b", "2026-07-01", "2026-07-02"),
        _match(1, 3, 2, "early-b", "early-c", "2026-07-02", "2026-07-03"),
    ]
    _, records, _ = detect_motifs(graph, _frame([1, 2, 3], graph), load_config(), matches, {})
    cycle = next(record for record in records if record["type"] == "cycle")
    assert cycle["metrics"]["confirmation_route"] == ["2", "3", "1", "2"]
    assert cycle["supporting_transaction_ids"] == ["early-a", "early-b", "early-c"]


def test_adjacent_day_repetitions_sum_integer_tiyn() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from([(1, 2), (2, 3)], sum_kzt=16384.10)
    matches = [_match(2, 1, 3, "a1", "b1", "2026-07-01", "2026-07-02", 819205),
               _match(2, 1, 3, "a2", "b2", "2026-07-02", "2026-07-03", 819205)]
    _, records, _ = detect_motifs(graph, _frame([1, 2, 3], graph), load_config(), matches, {})
    repeated = next(record for record in records if record["type"] == "repeated_route")
    assert repeated["metrics"]["compatible_tiyn"] == 1638410
    assert repeated["metrics"]["compatible_kzt"] == 16384.10
    assert len(repeated["metrics"]["confirmations"]) == 2
    assert repeated["supporting_transaction_ids"] == ["a1", "b1", "a2", "b2"]


def test_no_positive_betweenness_produces_strict_json(tmp_path: Path) -> None:
    source = _source(tmp_path / "input")
    exports.run_analysis(source, tmp_path / "latest")
    def reject_constant(value: str) -> object:
        raise AssertionError(f"Нестандартное JSON-значение: {value}")
    details = json.loads((tmp_path / "latest/node_details.json").read_text(), parse_constant=reject_constant)
    rule = details["2"]["rules"]["coordinator"]
    assert rule["thresholds"]["betweenness_value"] is None
    assert rule["threshold_status"] == "no_positive_betweenness"
    assert not rule["eligible"]


def test_serialization_failure_keeps_previous_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path / "input")
    latest = tmp_path / "latest"
    exports.run_analysis(source, latest)
    previous = latest.resolve()
    original = exports.json.dumps
    def bad_dumps(*args: object, **kwargs: object) -> str:
        if kwargs.get("indent") == 2:
            raise ValueError("injected JSON failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(exports.json, "dumps", bad_dumps)
    with pytest.raises(ValueError, match="injected JSON failure"):
        exports.run_analysis(source, latest)
    assert latest.resolve() == previous


def test_provider_invalid_intents_and_unavailable_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path / "input")
    exports.run_analysis(source, tmp_path / "latest")
    client = TestClient(create_app(tmp_path / "latest"), raise_server_exceptions=False)
    monkeypatch.setattr(assistant, "provider_status", lambda: {"available": True})
    async def bad_content(*args: object, **kwargs: object) -> str:
        return json.dumps({"intent": "convergence", "gids": None})
    monkeypatch.setattr(assistant, "_provider_content", bad_content)
    response = client.post("/api/assistant/query", json={"question": "Где сходятся?"})
    assert response.status_code == 200
    assert response.json()["status"] == "invalid_provider_response"
    assert response.json()["facts"] == []
    async def unavailable(*args: object, **kwargs: object) -> str:
        raise TimeoutError()
    monkeypatch.setattr(assistant, "_provider_content", unavailable)
    assert client.post("/api/assistant/query", json={"question": "Где сходятся?"}).json()["status"] == "provider_unavailable"


@pytest.mark.parametrize("response", [
    {"choices": []},
    {"choices": [{}]},
    {"choices": [{"message": {"content": None}}]},
])
def test_provider_response_shape_is_checked(monkeypatch: pytest.MonkeyPatch, response: dict[str, object]) -> None:
    monkeypatch.setenv("MONEY_GRAPH_LLM_URL", "https://example.invalid/ai")
    monkeypatch.setenv("MONEY_GRAPH_LLM_MODEL", "test")
    monkeypatch.setenv("MONEY_GRAPH_LLM_API_KEY", "dummy")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    original = httpx.AsyncClient
    monkeypatch.setattr(assistant.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(assistant.ProviderResponseError):
        asyncio.run(assistant._provider_content([{"role": "user", "content": "test"}], timeout=1))


@pytest.mark.parametrize("payload", [
    {"intent": "convergence", "gids": None},
    {"intent": "convergence", "gids": ["1", "1"]},
    {"intent": "explain_role", "gid": 1},
    {"intent": "cluster_consolidators", "cluster_id": True},
    {"intent": "motif_participants", "motif_type": "invented"},
    {"intent": "multi_seed", "gid": "1"},
])
def test_provider_intent_rejects_wrong_types_and_extra_fields(payload: dict[str, object]) -> None:
    with pytest.raises(assistant.ValidationError):
        assistant.INTENT_ADAPTER.validate_python(payload)


def test_bad_ranking_falls_back_to_checked_facts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path / "input")
    exports.run_analysis(source, tmp_path / "latest")
    from money_graph.api import ArtifactStore
    store = ArtifactStore(tmp_path / "latest")
    monkeypatch.setattr(assistant, "provider_status", lambda: {"available": True})
    async def intent(*args: object, **kwargs: object) -> assistant.ParsedIntent:
        return assistant.INTENT_ADAPTER.validate_python({"intent": "multi_seed"})
    async def invented_fact(*args: object, **kwargs: object) -> str:
        return json.dumps({"fact_ids": ["invented"]})
    monkeypatch.setattr(assistant, "_parse_intent", intent)
    monkeypatch.setattr(assistant, "_provider_content", invented_fact)
    # Use a graph where a non-seed is reachable from two seeds.
    store.nodes.loc[store.nodes.gid == 2, "seed_reach"] = 2
    store.nodes.loc[store.nodes.gid == 1, "seed_reach"] = 2
    result = asyncio.run(assistant.answer("Кто достижим от двух seed?", store))
    assert result["status"] == "ok"
    assert {item["gid"] for item in result["facts"]} == {"1", "2"}
