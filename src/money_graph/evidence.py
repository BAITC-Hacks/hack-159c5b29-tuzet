"""Human-readable role evidence, cluster summaries and detailed node cards."""
from __future__ import annotations

import json
from typing import Any

import networkx as nx
import pandas as pd

from .features import independent_seed_branches
from .ingestion import InputData
from .scoring import ROLES


def build_evidence(frame: pd.DataFrame, data: InputData, graph: nx.DiGraph, config: dict[str, Any], community_sets: list[set[int]], seeds: list[int], paths: dict[int, list[list[int]]], matches: list[dict[str, Any]], daily: dict[int, dict[str, Any]], hits_warning: str | None, motif_ids: dict[int, list[str]], motif_truncation: dict[str, bool], role_context: dict[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[int, dict[str, Any]]]:
    roles_cfg = config["roles"]
    transit_allowed = role_context["transit_allowed"]
    coordinator_allowed = role_context["coordinator_allowed"]
    terminal_allowed = role_context["terminal_allowed"]
    betweenness_threshold = role_context["betweenness_threshold"]
    def evidence(row: pd.Series) -> str:
        if row.is_isolate:
            return f"0 входящих и 0 исходящих связей; {'seed' if row.is_seed else 'не seed'}; данных для выраженной структурной роли недостаточно."
        base = {
            "consolidator": f"Получает от {row.in_deg} контрагентов; входящий оборот {row.in_kzt:,.0f} KZT; достижим от {row.seed_reach} seed.",
            "distributor": f"Направляет {row.out_kzt:,.0f} KZT {row.out_deg} получателям; {row.out_tx} исходящих операций.",
            "transit": f"Вход {row.in_kzt:,.0f} KZT, выход {row.out_kzt:,.0f} KZT; совпадение потока за 1–2 дня: {row.temporal_ratio:.0%}.",
            "coordinator": f"Betweenness {row.betweenness:.4f}; достижим от {row.seed_reach} seed; межкластерный поток {row.cross_cluster_ratio:.0%}.",
            "terminal": f"Получил {row.in_kzt:,.0f} KZT от {row.in_deg} контрагентов; исходящих в выборке нет {row.days_after_last_in} дн.",
            "peripheral": f"Входящих: {row.in_deg}, исходящих: {row.out_deg}; выраженные признаки основной структурной роли не достигли порога.",
        }[row.role]
        limitation = " Граница depth=4: дальнейшие переводы не наблюдаются." if row.truncated_by_depth else ""
        text = base + limitation
        if len(text) <= 200:
            return text
        return base if len(base) <= 200 else base.split(";", 1)[0] + "."

    frame["evidence"] = frame.apply(evidence, axis=1)
    frame["gid"] = frame.index.astype("int64")

    clusters: list[dict[str, Any]] = []
    for cluster_id, members in enumerate(community_sets):
        sub_edges = data.edges[data.edges.src.isin(members) & data.edges.dst.isin(members)]
        sub = frame.loc[sorted(members)].reset_index(drop=True)
        top = sub.sort_values(["priority_score", "gid"], ascending=[False, True]).head(5).gid.astype(int).tolist()
        role_counts = sub.role.value_counts()
        multi_seed_nodes = sub.loc[sub.seed_reach >= 2]
        if not multi_seed_nodes.empty:
            max_seed_reach = int(multi_seed_nodes.seed_reach.max())
            hypothesis = (
                f"Узлов с достижимостью от 2+ seed: {len(multi_seed_nodes)} "
                f"(максимальный охват: {max_seed_reach}); независимость маршрутов не проверена."
            )
        elif role_counts.get("consolidator", 0) > role_counts.get("distributor", 0):
            hypothesis = (
                "Больше кандидатов на консолидацию, чем на распределение: "
                f"{role_counts.get('consolidator', 0)} против {role_counts.get('distributor', 0)}."
            )
        elif role_counts.get("distributor", 0) > 0:
            hypothesis = (
                "Есть кандидаты на веерное распределение: "
                f"{role_counts.get('distributor', 0)} узл."
            )
        else:
            hypothesis = (
                "Локальный фрагмент наблюдаемой сети; кандидатов на "
                f"консолидацию {role_counts.get('consolidator', 0)}, "
                f"на распределение {role_counts.get('distributor', 0)}."
            )
        clusters.append({
            "cluster_id": cluster_id,
            "n_nodes": len(members),
            "n_seed": int(sub.is_seed.sum()),
            "sum_kzt_internal": int(sub_edges.sum_tiyn.sum()) / 100,
            "top_gids": json.dumps(top, ensure_ascii=False),
            "hypothesis": hypothesis,
        })

    details: dict[int, dict[str, Any]] = {}
    for gid, row in frame.iterrows():
        details[int(gid)] = {
            "gid": str(int(gid)),
            "role_scores": {role: float(row[f"{role}_score"]) for role in ROLES},
            "priority_contributions": {
                "structural": float(row.structural_contrib), "seed_exposure": float(row.seed_contrib),
                "flow": float(row.flow_contrib), "typology": float(row.typology_contrib),
                "temporal": float(row.temporal_contrib),
            },
            "seed_paths": [[str(value) for value in path] for path in paths.get(int(gid), [])[:5]],
            "typologies": row.typologies,
            "motif_ids": motif_ids.get(int(gid), []),
            "daily": daily.get(int(gid), {"days": []}),
            "hits": {"hub": None if pd.isna(row.hits_hub) else float(row.hits_hub), "authority": None if pd.isna(row.hits_authority) else float(row.hits_authority), "warning": hits_warning},
            "independent_seed_branches": None,
            "rules": {
                "consolidator": {"score": float(row.consolidator_score), "eligible": bool(row.in_deg >= int(roles_cfg["consolidator_min_in_degree"])), "selected": row.role == "consolidator", "measured": {"in_degree": int(row.in_deg)}, "thresholds": {"in_degree_min": int(roles_cfg["consolidator_min_in_degree"])}},
                "distributor": {"score": float(row.distributor_score), "eligible": bool(row.out_deg >= int(roles_cfg["distributor_min_out_degree"])), "selected": row.role == "distributor", "measured": {"out_degree": int(row.out_deg)}, "thresholds": {"out_degree_min": int(roles_cfg["distributor_min_out_degree"])}},
                "transit": {"score": float(row.transit_score), "eligible": bool(transit_allowed.loc[gid]), "selected": row.role == "transit", "measured": {"out_to_in_ratio": None if pd.isna(row.pass_through) else float(row.pass_through), "temporal_ratio": float(row.temporal_ratio), "is_seed": bool(row.is_seed)}, "thresholds": {"ratio_min": float(roles_cfg["transit_min_ratio"]), "ratio_max": float(roles_cfg["transit_max_ratio"])}},
                "coordinator": {"score": float(row.coordinator_score), "eligible": bool(coordinator_allowed.loc[gid]), "selected": row.role == "coordinator", "measured": {"betweenness": float(row.betweenness), "seed_reach": int(row.seed_reach), "neighbor_clusters": int(row.neighbor_cluster_count)}, "thresholds": {"betweenness_top_percentile": float(roles_cfg["coordinator_betweenness_percentile"]), "betweenness_value": betweenness_threshold}, "threshold_status": role_context["betweenness_threshold_status"]},
                "terminal": {"score": float(row.terminal_score), "eligible": bool(terminal_allowed.loc[gid]), "selected": row.role == "terminal", "measured": {"in_kzt": float(row.in_kzt), "out_degree": int(row.out_deg), "depth": int(row.depth), "days_after_last_in": int(row.days_after_last_in)}, "thresholds": {"max_depth_exclusive": 4, "min_days_after_last_in": int(roles_cfg["terminal_min_days_after_last_in"])}},
                "peripheral": {"score": float(row.peripheral_score), "eligible": row.role == "peripheral", "selected": row.role == "peripheral", "measured": {"max_other_role_score": float(max(row[f"{role}_score"] for role in ROLES if role != "peripheral"))}, "thresholds": {"minimum_other_role_score": float(roles_cfg["minimum_score"])}},
            },
            "limitations": [message for message, applies in [
                ("Граф ограничен исходящими внутрибанковскими переводами от seed.", True),
                ("Узел находится на границе depth=4; дальнейшие исходящие переводы не наблюдаются.", bool(row.truncated_by_depth)),
                ("Входящие seed вне выгрузки не наблюдаются; pass-through не интерпретируется как полный баланс.", bool(row.is_seed)),
                ("Последние поступления имеют неполное двухдневное окно наблюдения.", bool(row.incomplete_observation_window)),
            ] if applies],
        }
    for gid in frame.reset_index(drop=True).sort_values(["priority_score", "gid"], ascending=[False, True]).head(50).gid:
        details[int(gid)]["independent_seed_branches"] = independent_seed_branches(graph, set(seeds), int(gid))
    for detail in details.values():
        detail["motif_search_truncated"] = motif_truncation
        detail["temporal_matches"] = [match for match in matches if match["node_id"] == detail["gid"]]
    return frame.reset_index(drop=True), clusters, details
