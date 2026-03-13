"""RuleContextBuilder 测试。"""

from root_seeker.ai.rule_context import (
    build_rule_context_hint,
    extract_paths_from_tool_results,
)


def test_extract_paths_from_code_read():
    results = [
        ("code.read", "content", False, {"file_path": "src/main/Bar.java"}),
    ]
    assert extract_paths_from_tool_results(results) == ["src/main/Bar.java"]


def test_extract_paths_from_code_search():
    results = [
        ("code.search", '{"hits":[{"file_path":"src/foo/A.java"},{"file_path":"src/foo/B.java"}]}', False, {}),
    ]
    paths = extract_paths_from_tool_results(results)
    assert "src/foo/A.java" in paths
    assert "src/foo/B.java" in paths


def test_build_rule_context_hint():
    assert build_rule_context_hint([]) == ""
    assert "src/a.java" in build_rule_context_hint(["src/a.java", "src/b.java"])
