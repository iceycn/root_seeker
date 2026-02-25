from pathlib import Path

from root_seeker.config import RepoConfig
from root_seeker.services.service_graph import ServiceGraphBuilder


def test_service_graph_builder_detects_http_calls(tmp_path: Path):
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()

    (repo_a / "x.py").write_text('requests.get("http://b-service/api")\n', encoding="utf-8")
    (repo_b / "y.py").write_text("print('ok')\n", encoding="utf-8")

    repos = [
        RepoConfig(service_name="a-service", git_url="x", local_dir=str(repo_a)),
        RepoConfig(service_name="b-service", git_url="y", local_dir=str(repo_b)),
    ]
    graph = ServiceGraphBuilder().build(repos)
    downstreams = graph.downstream_of("a-service")
    assert any(s.service_name == "b-service" for s in downstreams)
