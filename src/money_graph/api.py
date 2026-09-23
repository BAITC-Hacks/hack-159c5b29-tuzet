"""Read-only API bound to one completed analytical run."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import networkx as nx
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from .assistant import AssistantQuestion, answer, provider_status


class RunResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    run_id: str


class ItemsResponse(RunResponse):
    items: list[dict[str, Any]]


class NodeResponse(RunResponse):
    item: dict[str, Any]


class ArtifactStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        needed = ["manifest.json", "node_features.parquet", "graph_edges.parquet", "transactions.parquet", "node_details.json", "clusters.csv", "top_nodes.csv", "nodes_roles.csv"]
        missing = [name for name in needed if not (self.directory / name).exists()]
        if missing:
            raise ValueError(f"Каталог артефактов неполный: {', '.join(missing)}")
        self.manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
        self.run_id = str(self.manifest["run_id"])
        self.nodes = pd.read_parquet(self.directory / "node_features.parquet")
        self.edges = pd.read_parquet(self.directory / "graph_edges.parquet")
        self.transactions = pd.read_parquet(self.directory / "transactions.parquet")
        self.transactions["date"] = pd.to_datetime(self.transactions.date)
        self.details = json.loads((self.directory / "node_details.json").read_text(encoding="utf-8"))
        self.clusters = pd.read_csv(self.directory / "clusters.csv")
        self.motifs = self._json("typologies.json", [])
        self.disruption = self._json("disruption.json", [])
        self.sensitivity = self._json("sensitivity.json", [])
        self.sensitivity_summary = self._json("sensitivity_summary.json", {"position_ranges": {}})
        self.node_index = {int(row.gid): row for row in self.nodes.itertuples(index=False)}
        self.motif_index = {item["motif_id"]: item for item in self.motifs}
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(self.node_index)
        self.graph.add_edges_from((int(row.src), int(row.dst)) for row in self.edges.itertuples(index=False))

    def _json(self, name: str, default: Any) -> Any:
        path = self.directory / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    @staticmethod
    def _scalar(value: Any) -> Any:
        if isinstance(value, (list, dict, str, bool)) or value is None:
            return value
        if hasattr(value, "tolist") and getattr(value, "ndim", 0):
            return value.tolist()
        if pd.isna(value):
            return None
        return value.item() if hasattr(value, "item") else value

    def node_summary(self, gid: int) -> dict[str, Any]:
        row = self.node_index.get(gid)
        if row is None:
            raise KeyError(gid)
        value = {key: self._scalar(item) for key, item in row._asdict().items()}
        value["gid"] = str(gid)
        return value

    def get_node(self, gid: int) -> dict[str, Any]:
        result = self.node_summary(gid)
        result["details"] = self.details.get(str(gid), {})
        return result

    def cluster(self, cluster_id: int) -> dict[str, Any]:
        selected = self.clusters.loc[self.clusters.cluster_id == cluster_id]
        if selected.empty:
            raise KeyError(cluster_id)
        result = {key: self._scalar(value) for key, value in selected.iloc[0].to_dict().items()}
        result["top_gids"] = [str(gid) for gid in json.loads(result["top_gids"])]
        result["top_nodes"] = [self.node_summary(int(gid)) for gid in result["top_gids"]]
        return result

    def neighborhood(self, gid: int, hops: int, max_nodes: int, max_edges: int) -> dict[str, Any]:
        self.node_summary(gid)
        frontier, all_nodes = {gid}, {gid}
        for _ in range(hops):
            linked = self.edges[self.edges.src.isin(frontier) | self.edges.dst.isin(frontier)]
            frontier = set(linked.src.astype(int)).union(linked.dst.astype(int)) - all_nodes
            all_nodes.update(frontier)
        available_edges = self.edges[self.edges.src.isin(all_nodes) & self.edges.dst.isin(all_nodes)].copy()
        available_edges["incident"] = (available_edges.src == gid) | (available_edges.dst == gid)
        available_edges = available_edges.sort_values(["incident", "sum_kzt", "src", "dst"], ascending=[False, False, True, True])
        chosen = {gid}
        edge_rows = []
        for row in available_edges.itertuples(index=False):
            endpoints = {int(row.src), int(row.dst)}
            if len(chosen | endpoints) > max_nodes or len(edge_rows) >= max_edges:
                continue
            chosen.update(endpoints)
            edge_rows.append(row)
        # An isolated selected client is still a complete one-node neighborhood.
        edges = [{"source": str(int(row.src)), "target": str(int(row.dst)), "sum_kzt": float(row.sum_kzt), "n_tx": int(row.n_tx), "depth": int(row.depth)} for row in edge_rows]
        return {"run_id": self.run_id, "nodes": [self.node_summary(node_id) for node_id in sorted(chosen)], "edges": edges,
                "available_nodes": len(all_nodes), "shown_nodes": len(chosen), "available_edges": len(available_edges), "shown_edges": len(edges),
                "truncated": len(chosen) < len(all_nodes) or len(edges) < len(available_edges)}


def frontend_directory() -> Path:
    package_dist = Path(__file__).resolve().parent / "web"
    source_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    frontend = package_dist if (package_dist / "index.html").exists() else source_dist
    if not (frontend / "index.html").exists():
        raise ValueError("Собранный frontend не найден. Выполните: cd frontend && npm ci && npm run build")
    return frontend


def create_app(artifacts: Path, *, serve_frontend: bool = False) -> FastAPI:
    store = ArtifactStore(artifacts)
    app = FastAPI(title="Граф денег API", version="0.2.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/api/health", response_model=RunResponse)
    def health() -> dict[str, Any]:
        return {"run_id": store.run_id, "ready": True, "methodology_version": store.manifest.get("methodology_version")}

    @app.get("/api/summary", response_model=RunResponse)
    def summary() -> dict[str, Any]:
        return {**store.manifest, "roles": ["consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"]}

    @app.get("/api/nodes", response_model=ItemsResponse)
    def nodes(q: str | None = None, role: str | None = None, cluster_id: int | None = None,
              depth: int | None = Query(default=None, ge=0, le=4), min_priority: float = Query(default=0, ge=0, le=1),
              include_seed: bool = True, offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200),
              sort: Literal["priority", "gid", "role"] = "priority") -> dict[str, Any]:
        result = store.nodes[store.nodes.priority_score >= min_priority]
        if q:
            result = result[result.gid.astype(str).str.contains(q, regex=False)]
        if role:
            result = result[result.role == role]
        if cluster_id is not None:
            result = result[result.cluster_id == cluster_id]
        if depth is not None:
            result = result[result.depth == depth]
        if not include_seed:
            result = result[~result.is_seed]
        columns, ascending = ({"priority": (["priority_score", "gid"], [False, True]), "gid": (["gid"], [True]), "role": (["role", "priority_score", "gid"], [True, False, True])})[sort]
        result = result.sort_values(columns, ascending=ascending)
        return {"run_id": store.run_id, "total": len(result), "offset": offset, "limit": limit,
                "items": [store.node_summary(int(gid)) for gid in result.iloc[offset:offset + limit].gid]}

    @app.get("/api/nodes/{gid}", response_model=NodeResponse)
    def node(gid: int) -> dict[str, Any]:
        try:
            return {"run_id": store.run_id, "item": store.get_node(gid)}
        except KeyError as error:
            raise HTTPException(status_code=404, detail="gid не найден") from error

    @app.get("/api/nodes/{gid}/neighborhood", response_model=RunResponse)
    def neighborhood(gid: int, hops: int = Query(default=1, ge=1, le=2), max_nodes: int = Query(default=200, ge=1, le=200), max_edges: int = Query(default=500, ge=1, le=500)) -> dict[str, Any]:
        try:
            return store.neighborhood(gid, hops, max_nodes, max_edges)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="gid не найден") from error

    @app.get("/api/nodes/{gid}/transactions", response_model=ItemsResponse)
    def transactions(gid: int) -> dict[str, Any]:
        try:
            detail = store.get_node(gid)["details"]
        except KeyError as error:
            raise HTTPException(status_code=404, detail="gid не найден") from error
        selected = store.transactions[(store.transactions.src == gid) | (store.transactions.dst == gid)].copy()
        selected["direction"] = selected.src.eq(gid).map({True: "out", False: "in"})
        selected["date"] = selected.date.dt.strftime("%Y-%m-%d")
        daily = selected.groupby(["date", "direction"], as_index=False).sum_tiyn.sum()
        items = [{"transaction_id": str(row.transaction_id), "src": str(int(row.src)), "dst": str(int(row.dst)), "date": row.date,
                  "sum_kzt": float(row.sum_kzt), "direction": row.direction, "counterparty_gid": str(int(row.dst if row.src == gid else row.src))}
                 for row in selected.sort_values(["date", "src", "dst", "transaction_id"]).itertuples(index=False)]
        return {"run_id": store.run_id, "items": items,
                "daily": [{"date": row.date, "direction": row.direction, "sum_kzt": int(row.sum_tiyn) / 100} for row in daily.itertuples(index=False)],
                "daily_features": detail.get("daily", {}), "temporal_matches": detail.get("temporal_matches", [])}

    @app.get("/api/clusters", response_model=ItemsResponse)
    def clusters() -> dict[str, Any]:
        return {"run_id": store.run_id, "items": [store.cluster(int(gid)) for gid in store.clusters.cluster_id]}

    @app.get("/api/clusters/{cluster_id}", response_model=NodeResponse)
    def cluster(cluster_id: int) -> dict[str, Any]:
        try:
            return {"run_id": store.run_id, "item": store.cluster(cluster_id)}
        except KeyError as error:
            raise HTTPException(status_code=404, detail="cluster_id не найден") from error

    @app.get("/api/top", response_model=ItemsResponse)
    def top(limit: int = Query(default=50, ge=1, le=50)) -> dict[str, Any]:
        result = store.nodes.sort_values(["priority_score", "gid"], ascending=[False, True]).head(limit)
        return {"run_id": store.run_id, "items": [store.node_summary(int(gid)) for gid in result.gid]}

    @app.get("/api/typologies", response_model=ItemsResponse)
    def typologies(type: str | None = None, gid: str | None = None, offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        selected = [item for item in store.motifs if (type is None or item["type"] == type) and (gid is None or gid in item["node_ids"])]
        return {"run_id": store.run_id, "total": len(selected), "offset": offset, "limit": limit, "items": selected[offset:offset + limit]}

    @app.get("/api/typologies/{motif_id}", response_model=NodeResponse)
    def typology(motif_id: str) -> dict[str, Any]:
        if motif_id not in store.motif_index:
            raise HTTPException(status_code=404, detail="мотив не найден")
        return {"run_id": store.run_id, "item": store.motif_index[motif_id]}

    @app.get("/api/disruption", response_model=ItemsResponse)
    def disruption() -> dict[str, Any]:
        return {"run_id": store.run_id, "items": store.disruption}

    @app.get("/api/sensitivity", response_model=ItemsResponse)
    def sensitivity() -> dict[str, Any]:
        return {"run_id": store.run_id, "items": store.sensitivity, **store.sensitivity_summary}

    @app.get("/api/assistant/status", response_model=RunResponse)
    def assistant_status() -> dict[str, Any]:
        return {"run_id": store.run_id, **provider_status()}

    @app.post("/api/assistant/query", response_model=RunResponse)
    async def assistant(question: AssistantQuestion) -> dict[str, Any]:
        if question.expected_run_id is not None and question.expected_run_id != store.run_id:
            raise HTTPException(status_code=409, detail="Запуск изменился; обновите страницу.")
        return {"run_id": store.run_id, **await answer(question.question, store, question.selected_gid)}

    @app.get("/api/exports/{name}")
    def export(name: Literal["nodes_roles", "clusters", "top_nodes"]) -> FileResponse:
        return FileResponse(store.directory / f"{name}.csv", media_type="text/csv", filename=f"{name}.csv")

    if serve_frontend:
        frontend = frontend_directory()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="API endpoint не найден")
            target = (frontend / path).resolve()
            if target.is_file() and target.is_relative_to(frontend.resolve()):
                return FileResponse(target)
            return FileResponse(frontend / "index.html")

    return app
