from pathlib import Path

from fastapi.testclient import TestClient

from money_graph.api import create_app


def test_api_finds_any_generated_node(full_artifacts: Path) -> None:
    client = TestClient(create_app(full_artifacts))
    top = client.get("/api/top").json()["items"][0]
    assert client.get(f"/api/nodes/{top['gid']}").status_code == 200
    neighborhood = client.get(f"/api/nodes/{top['gid']}/neighborhood").json()
    assert any(item["gid"] == top["gid"] for item in neighborhood["nodes"])
    assert client.get("/api/nodes/999999999999").status_code == 404
