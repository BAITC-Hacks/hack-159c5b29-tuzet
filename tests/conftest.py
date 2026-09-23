from pathlib import Path

import pytest

from money_graph.analytics import run_analysis


@pytest.fixture(scope="session")
def full_artifacts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("supplied-dataset") / "latest"
    run_analysis(Path("data"), target)
    return target
