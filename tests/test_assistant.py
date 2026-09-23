"""Behavioral checks for the boundary between model intent and published facts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient

from money_graph import assistant
from money_graph.api import create_app


def _intent(monkeypatch, payload: dict[str, object]) -> None:
    monkeypatch.setattr(assistant, "provider_status", lambda: {"available": True})

    async def parsed(*args: object, **kwargs: object) -> assistant.ParsedIntent:
        return assistant.INTENT_ADAPTER.validate_python(payload)

    monkeypatch.setattr(assistant, "_parse_intent", parsed)


def _node_store() -> SimpleNamespace:
    node = {
        "gid": "2",
        "role": "terminal",
        "role_score": 0.75,
        "priority_score": 0.4,
        "evidence": "Получил 100 KZT.",
        "details": {
            "priority_contributions": {"flow": 0.4},
            "rules": {
                "terminal": {
                    "measured": {"out_degree": 0},
                    "thresholds": {"max_depth_exclusive": 4},
                }
            },
            "limitations": ["Неполное окно наблюдения."],
        },
    }
    return SimpleNamespace(
        get_node=lambda gid: node if gid == 2 else (_ for _ in ()).throw(KeyError(gid))
    )


def test_selected_client_and_explicit_gid_are_verified(monkeypatch) -> None:
    store = _node_store()
    _intent(monkeypatch, {"intent": "explain_role", "gid": "2"})
    answer = asyncio.run(assistant.answer("Почему этот клиент?", store, selected_gid="2"))
    assert answer["status"] == "ok"
    assert answer["facts"][0]["rule"]["measured"]["out_degree"] == 0
    assert answer["facts"][0]["limitations"] == ["Неполное окно наблюдения."]

    assert (
        asyncio.run(assistant.answer("Почему клиент 1?", store, selected_gid="2"))["status"]
        == "needs_clarification"
    )
    assert (
        asyncio.run(assistant.answer("Почему этот клиент?", store))["status"]
        == "needs_clarification"
    )


def test_motif_status_and_incomplete_results_are_visible(monkeypatch) -> None:
    _intent(monkeypatch, {"intent": "motif_participants", "motif_type": "cycle"})
    motifs = [
        {
            "motif_id": f"cycle-{index}",
            "type": "cycle",
            "node_ids": ["1", "2"],
            "temporal_status": "structural",
            "supporting_transaction_ids": [],
            "limitations": ["Временная последовательность не подтверждена."],
        }
        for index in range(21)
    ]
    store = SimpleNamespace(
        motifs=motifs,
        manifest={"optional_status": {"motif_truncation": {"cycle": True}}},
    )
    result = asyncio.run(assistant.answer("Покажи циклы", store))
    assert result["total"] == 21
    assert result["shown"] == 20
    assert result["truncated"] and result["search_truncated"]
    assert result["facts"][0]["temporal_status"] == "structural"
    assert result["facts"][0]["limitations"]

    store.motifs = []
    empty = asyncio.run(assistant.answer("Покажи циклы", store))
    assert empty["status"] == "no_data"
    assert empty["search_truncated"]
    assert "не доказывает" in empty["answer"]


def test_list_selection_is_local_and_complete(monkeypatch) -> None:
    _intent(monkeypatch, {"intent": "multi_seed"})

    async def unexpected_provider_call(*args: object, **kwargs: object) -> str:
        raise AssertionError("Факты не должны отправляться модели для ранжирования")

    monkeypatch.setattr(assistant, "_provider_content", unexpected_provider_call)
    store = SimpleNamespace(nodes=pd.DataFrame({"gid": [1, 2], "seed_reach": [2, 3]}))
    result = asyncio.run(assistant.answer("Кто достижим от двух seed?", store))
    assert result["status"] == "ok"
    assert [fact["gid"] for fact in result["facts"]] == ["2", "1"]
    assert result["total"] == result["shown"] == 2


def test_stale_run_is_rejected_before_model_call(full_artifacts: Path, monkeypatch) -> None:
    async def unexpected(*args: object, **kwargs: object) -> assistant.ParsedIntent:
        raise AssertionError("Запрос к модели не должен выполняться")

    monkeypatch.setattr(assistant, "_parse_intent", unexpected)
    client = TestClient(create_app(full_artifacts))
    response = client.post(
        "/api/assistant/query",
        json={
            "question": "Почему этот клиент?",
            "selected_gid": "2",
            "expected_run_id": "stale",
        },
    )
    assert response.status_code == 409
