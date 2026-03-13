"""AIPromptContext 与 AIPromptBuilder 测试。"""

from root_seeker.ai.prompt_builder import AIPromptBuilder, AIPromptContext, _post_process


def test_post_process():
    assert _post_process("  a\n\n\n\nb  ") == "a\n\nb"
    assert _post_process("") == ""
    # 去除空 section（仅含 "标签：" 的块）
    assert _post_process("可用工具：\n\n其他内容") == "其他内容"
    # 标题+内容在同一块时保留
    assert _post_process("标题：\n有实质内容") == "标题：\n有实质内容"


def test_aiprompt_builder():
    ctx = AIPromptContext(service_name="svc", error_log="err", tools_summary="- t1: desc")
    from root_seeker import prompts

    result = AIPromptBuilder(prompts.AI_ORCHESTRATOR_PLAN_USER, ctx).build()
    assert "svc" in result
    assert "err" in result
    assert "t1" in result
