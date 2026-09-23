"""Optional AI intent parsing with validated, locally sourced answers."""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Annotated, Any, Literal

import httpx
import networkx as nx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    TypeAdapter,
    ValidationError,
    field_validator,
)

Gid = Annotated[str, Field(pattern=r"^[0-9]+$")]
MotifType = Literal[
    "fan_in",
    "fan_out",
    "multi_seed_convergence",
    "pass_through_chain",
    "cycle",
    "scatter_gather",
    "repeated_route",
]


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    selected_gid: Gid | None = None
    expected_run_id: str | None = Field(default=None, min_length=1, max_length=128)


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExplainRole(Intent):
    intent: Literal["explain_role"]
    gid: Gid


class ExplainPriority(Intent):
    intent: Literal["explain_priority"]
    gid: Gid


class MultiSeed(Intent):
    intent: Literal["multi_seed"]


class ClusterConsolidators(Intent):
    intent: Literal["cluster_consolidators"]
    cluster_id: StrictInt


class MotifParticipants(Intent):
    intent: Literal["motif_participants"]
    motif_type: MotifType


class Convergence(Intent):
    intent: Literal["convergence"]
    gids: list[Gid] = Field(min_length=2, max_length=10)

    @field_validator("gids")
    @classmethod
    def unique_gids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("gid должны быть различными")
        return value


class NeedsClarification(Intent):
    intent: Literal["needs_clarification"]
    missing: Literal["gid", "cluster_id", "motif_type", "gids", "question"]


class Unsupported(Intent):
    intent: Literal["unsupported"]


ParsedIntent = Annotated[
    ExplainRole
    | ExplainPriority
    | MultiSeed
    | ClusterConsolidators
    | MotifParticipants
    | Convergence
    | NeedsClarification
    | Unsupported,
    Field(discriminator="intent"),
]
INTENT_ADAPTER = TypeAdapter(ParsedIntent)


class ProviderResponseError(ValueError):
    """The provider returned data outside the permitted response contract."""


def provider_status() -> dict[str, Any]:
    enabled = bool(
        os.getenv("MONEY_GRAPH_LLM_URL")
        and os.getenv("MONEY_GRAPH_LLM_MODEL")
        and os.getenv("MONEY_GRAPH_LLM_API_KEY")
    )
    return {
        "available": enabled,
        "external_provider": enabled,
        "message": "Настройки AI заданы; доступность провайдера проверится при запросе"
        if enabled
        else "AI отключён; поиск и расчётные объяснения доступны без него",
    }


async def _provider_content(messages: list[dict[str, str]], timeout: float) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            os.environ["MONEY_GRAPH_LLM_URL"],
            headers={"Authorization": f"Bearer {os.environ['MONEY_GRAPH_LLM_API_KEY']}"},
            json={
                "model": os.environ["MONEY_GRAPH_LLM_MODEL"],
                "temperature": 0,
                "messages": messages,
            },
        )
        response.raise_for_status()
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderResponseError("Некорректная структура ответа провайдера") from error
    if not isinstance(content, str):
        raise ProviderResponseError("Провайдер вернул нестроковый ответ")
    return content


async def _parse_intent(
    question: str, timeout: float, selected_gid: str | None = None
) -> ParsedIntent:
    system = (
        "Return exactly one JSON object matching this schema: "
        + json.dumps(INTENT_ADAPTER.json_schema(), ensure_ascii=False, separators=(",", ":"))
        + ". For 'этот клиент' use selected_gid only when provided. An explicit gid in the "
        "question takes precedence. If a required parameter is missing or ambiguous, return "
        "needs_clarification with missing. If the question is outside the supported intents, "
        "return unsupported. Do not answer or invent identifiers."
    )
    content = await _provider_content(
        [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "selected_gid": selected_gid},
                    ensure_ascii=False,
                ),
            },
        ],
        timeout,
    )
    try:
        return INTENT_ADAPTER.validate_python(json.loads(content))
    except (ValidationError, ValueError, TypeError) as error:
        raise ProviderResponseError("Некорректное аналитическое намерение") from error


def _question_gid(question: str) -> tuple[str | None, bool]:
    labeled = re.findall(
        r"(?i)(?:\bgid\b|\bклиент(?:а|у|ом|е)?\b|\bузел\b|\bузла\b|\bузлу\b)\s*[№#:]?\s*(\d+)\b",
        question,
    )
    ids = {str(int(value)) for value in labeled}
    if len(ids) > 1:
        return None, True
    if ids:
        return next(iter(ids)), False
    simple = re.fullmatch(r"(?i)\s*(?:почему|роль|приоритет)\s+(?:у\s+)?(\d+)\s*\??\s*", question)
    return (str(int(simple.group(1))), False) if simple else (None, False)


def _result(
    status: str,
    message: str,
    *,
    facts: list[dict[str, Any]] | None = None,
    total: int = 0,
    search_truncated: bool = False,
    intent: str | None = None,
) -> dict[str, Any]:
    selected = facts or []
    return {
        "status": status,
        "available": status != "disabled",
        "answer": message,
        "facts": selected,
        "total": total,
        "shown": len(selected),
        "truncated": len(selected) < total,
        "search_truncated": search_truncated,
        "intent": intent,
        "external_provider": status not in {"disabled", "provider_unavailable"},
    }


async def answer(question: str, store: Any, selected_gid: str | None = None) -> dict[str, Any]:
    if not provider_status()["available"]:
        return _result("disabled", "AI отключён. Используйте поиск по gid и карточки клиентов.")
    try:
        intent = await asyncio.wait_for(
            _parse_intent(question, timeout=30.0, selected_gid=selected_gid),
            30.0,
        )
    except (ProviderResponseError, ValidationError, ValueError, TypeError):
        return _result(
            "invalid_provider_response",
            "Провайдер вернул некорректный ответ. Используйте поиск и карточки клиентов.",
        )
    except (httpx.HTTPError, TimeoutError, OSError):
        return _result(
            "provider_unavailable", "Провайдер недоступен. Расчётные карточки продолжают работать."
        )

    kind = intent.intent
    if isinstance(intent, NeedsClarification):
        messages = {
            "gid": "Укажите gid клиента или выберите его в графе.",
            "cluster_id": "Укажите номер кластера.",
            "motif_type": "Укажите тип мотива.",
            "gids": "Укажите от двух до десяти gid для сравнения путей.",
            "question": "Уточните, что нужно проверить в сохранённом графе.",
        }
        return _result("needs_clarification", messages[intent.missing], intent=kind)
    if isinstance(intent, Unsupported):
        return _result(
            "unsupported",
            "Этот вопрос пока не поддерживается. Можно спросить о роли, приоритете, seed, кластере, мотиве или схождении путей.",
            intent=kind,
        )

    facts: list[dict[str, Any]] = []
    total = 0
    search_truncated = False
    if isinstance(intent, (ExplainRole, ExplainPriority)):
        requested, ambiguous = _question_gid(question)
        expected = requested or selected_gid
        if ambiguous or expected is None or int(intent.gid) != int(expected):
            return _result(
                "needs_clarification",
                "Уточните gid клиента: он не совпадает с выбранным или указанным в вопросе.",
                intent=kind,
            )
        try:
            node = store.get_node(int(intent.gid))
        except KeyError:
            return _result(
                "entity_not_found",
                f"Клиент с gid {intent.gid} отсутствует в этом запуске.",
                intent=kind,
            )
        details = node["details"]
        facts = [
            {
                "fact_id": f"node:{node['gid']}",
                "gid": node["gid"],
                "role": node["role"],
                "role_score": node["role_score"],
                "priority_score": node["priority_score"],
                "evidence": node["evidence"],
                "contributions": details["priority_contributions"],
                "rule": details["rules"][node["role"]],
                "limitations": details["limitations"],
            }
        ]
        total = 1
    elif isinstance(intent, MultiSeed):
        selected = store.nodes.loc[store.nodes.seed_reach >= 2].sort_values(
            ["seed_reach", "gid"],
            ascending=[False, True],
        )
        total = len(selected)
        facts = [
            {
                "fact_id": f"seed:{int(row.gid)}",
                "gid": str(int(row.gid)),
                "seed_reach": int(row.seed_reach),
                "limitations": [
                    "Достижимость от seed — структурная связь, не происхождение суммы."
                ],
            }
            for row in selected.head(20).itertuples()
        ]
    elif isinstance(intent, ClusterConsolidators):
        selected = store.nodes.loc[
            (store.nodes.cluster_id == intent.cluster_id) & (store.nodes.role == "consolidator")
        ].sort_values(["priority_score", "gid"], ascending=[False, True])
        total = len(selected)
        facts = [
            {
                "fact_id": f"cluster:{intent.cluster_id}:{int(row.gid)}",
                "gid": str(int(row.gid)),
                "priority_score": float(row.priority_score),
                "limitations": ["Роль — соответствие правилу, не вывод о виновности."],
            }
            for row in selected.head(20).itertuples()
        ]
    elif isinstance(intent, MotifParticipants):
        selected = [item for item in store.motifs if item["type"] == intent.motif_type]
        total = len(selected)
        truncated_by_type = store.manifest.get("optional_status", {}).get("motif_truncation", {})
        search_truncated = bool(truncated_by_type.get(intent.motif_type, False))
        facts = [
            {
                "fact_id": item["motif_id"],
                "type": item["type"],
                "node_ids": item["node_ids"],
                "temporal_status": item["temporal_status"],
                "supporting_transaction_ids": item["supporting_transaction_ids"],
                "limitations": item["limitations"],
            }
            for item in selected[:20]
        ]
    elif isinstance(intent, Convergence):
        sources = [int(gid) for gid in intent.gids]
        missing = [gid for gid in sources if gid not in store.graph]
        if missing:
            return _result(
                "entity_not_found",
                "В этом запуске отсутствуют gid: " + ", ".join(map(str, missing)),
                intent=kind,
            )
        common = set.intersection(*(nx.descendants(store.graph, source) for source in sources))
        ranked = sorted(common, key=lambda gid: (-float(store.node_index[gid].priority_score), gid))
        total = len(ranked)
        facts = [
            {
                "fact_id": f"convergence:{gid}",
                "gid": str(gid),
                "paths": [
                    [str(node) for node in nx.shortest_path(store.graph, source, gid)]
                    for source in sources
                ],
                "limitations": [
                    "Путь — структурная достижимость, не трассировка конкретных денег."
                ],
            }
            for gid in ranked[:20]
        ]

    if not facts:
        suffix = (
            " Поиск мотивов был ограничен; отсутствие в результате не доказывает отсутствие мотива."
            if search_truncated
            else ""
        )
        return _result(
            "no_data",
            "В сохранённых результатах совпадений не найдено." + suffix,
            total=total,
            search_truncated=search_truncated,
            intent=kind,
        )

    if kind == "explain_role":
        fact = facts[0]
        rule = fact["rule"]
        measured = ", ".join(f"{key}={value}" for key, value in rule["measured"].items())
        thresholds = ", ".join(f"{key}={value}" for key, value in rule["thresholds"].items())
        message = f"GID {fact['gid']}: признаки роли {fact['role']} (score {fact['role_score']:.3f}). {fact['evidence']} Измерено: {measured}. Пороги: {thresholds}."
    elif kind == "explain_priority":
        fact = facts[0]
        parts = ", ".join(f"{key} {value:.3f}" for key, value in fact["contributions"].items())
        message = f"GID {fact['gid']}: priority {fact['priority_score']:.3f}; вклады: {parts}."
    else:
        label = {
            "multi_seed": "Клиенты, достижимые от нескольких seed",
            "cluster_consolidators": "Клиенты с ролью consolidator в кластере",
            "motif_participants": "Найденные мотивы",
            "convergence": "Общие достижимые узлы",
        }[kind]
        message = f"{label}: показано {len(facts)} из {total} найденных."
    if search_truncated:
        message += " Поиск мотивов в исходном расчёте был ограничен."
    return _result(
        "ok", message, facts=facts, total=total, search_truncated=search_truncated, intent=kind
    )
