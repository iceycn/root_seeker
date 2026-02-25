from pathlib import Path

import pytest

from root_seeker.indexing.chunker import TreeSitterChunker


def test_tree_sitter_chunk_python(tmp_path: Path):
    try:
        import tree_sitter_python  # noqa: F401
    except Exception:
        pytest.skip("tree-sitter-python is not installed")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def foo(x):\n    return x + 1\n", encoding="utf-8")
    chunker = TreeSitterChunker()
    chunks = chunker.chunk_file(repo_local_dir=str(repo), file_path="a.py")
    assert chunks
    assert chunks[0].language == "python"
