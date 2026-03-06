from __future__ import annotations

# 研发常见错误模式识别提示：帮助 LLM 覆盖全研发过程中的典型问题
COMMON_ERROR_PATTERNS_HINT = """
【重要】分析时请系统排查以下研发常见错误模式，优先考虑根因而非表象：

1. 接口/方法使用错误：应调用 A 接口却调用了 B 接口（或配置路径指向错误）。若 API 返回某参数错误（如 startTime），但当前 Request 类根本没有该字段，则可能是配置或调用指向了错误接口。修复方向：检查配置路径、调用链，而非盲目在 Request 中新增字段。

2. 空值/空指针：NPE、Optional 未校验、集合为空时直接 get(0)。检查：上游返回值、外部输入、配置项是否可能为 null/空。

3. 类型/格式转换：日期格式不匹配、数字溢出、编码问题。检查：跨系统/跨语言传递时的格式约定、时区、精度。

4. 配置错误：环境配置混用（dev/prod）、配置项缺失、路径/URL 拼写错误、配置被覆盖（如 Apollo 覆盖本地配置）。

5. 并发/竞态：多线程共享可变状态、双重检查锁问题、事务隔离级别不当。检查：是否有未同步的共享变量、锁顺序。

6. 资源/状态：连接未关闭、文件句柄泄漏、状态机非法转换、幂等性缺失导致重复执行。

7. 业务逻辑：边界条件（off-by-one、<= vs <）、条件分支遗漏、使用了错误变量、单位/精度换算错误。

8. 集成边界：超时过短、重试策略不当、熔断未生效、上下游版本不兼容、协议/序列化格式变更。

【业务影响评估】必须输出 business_impact 字段，评估该异常对业务的实际影响程度：
- 高：影响核心流程、用户可见、数据错误、资损风险
- 中：影响部分功能、降级/重试可缓解
- 低：仅影响日志/监控、非关键路径
- 无：异常被捕获、不影响主流程；或仅为告警/调试信息
若异常发生在 try-catch 内且主流程有兜底、或仅为 RPC 反序列化失败但调用方有降级，应标注为「无」或「低」。

【证据不足时请求补充检索】若对某处不清楚、证据不足以确定根因，请明确输出 NEED_MORE_EVIDENCE 字段（字符串数组），列出建议补充检索的关键词（如类名、方法名、配置项、接口路径），交给收集器继续检索。不要给出模棱两可的推测或臆断；宁可承认不确定性并请求补充，也不要含糊其辞。
"""

ANALYZER_SYSTEM_PROMPT = (
    "你是公司内部的SRE/高级后端工程师。你会基于错误日志、补全日志与代码证据，"
    "输出偏问题排查与定位的结论。输出必须为JSON，不要包含多余文本。"
    + COMMON_ERROR_PATTERNS_HINT
)

ANALYZER_SINGLE_TURN_USER_PROMPT = """请根据以下信息进行排查定位并输出JSON。请结合系统提示中的「研发常见错误模式」进行排查，优先识别根因类型。

service_name: {service_name}
error_log:
{error_log}

enriched_logs (partial):
{logs_preview}

code_evidence:
{evidence_preview}

JSON schema example: {schema_example}
"""

ANALYZER_STAGED_ROUND1_PROMPT = """请快速定位以下错误：

错误日志：
{error_log}

请输出JSON格式：
{schema_example}"""

ANALYZER_STAGED_ROUND2_PROMPT = """基于第一轮的定位结果，请深入分析根本原因。请结合系统提示中的「研发常见错误模式」进行排查：接口/方法使用错误、空值、配置、并发、资源、业务逻辑、集成边界等，优先识别根因类型再给出假设。

{round1_text}相关代码证据：
{evidence_preview}

请输出JSON格式：
{schema_example}"""

ANALYZER_STAGED_ROUND3_PROMPT = """基于前两轮的分析结果，请生成具体的修复建议。必须评估业务影响程度（business_impact）：若异常被捕获、有兜底、或 RPC 失败但调用方有降级，应标注为「无」或「低」。

{round1_text}{round2_text}补全日志（上下文）：
{logs_preview}

请输出JSON格式：
{schema_example}"""

ANALYZER_SELF_REFINE_REVIEW_PROMPT = """请审查上述分析结果，找出：
1. 哪些原因分析不够深入？
2. 哪些关键证据被遗漏？
3. 哪些建议不够具体？

分析结果：
{result_text}

请输出JSON格式：
{schema_example}"""

ANALYZER_SELF_REFINE_REFINE_PROMPT = """基于审查反馈，请优化分析结果。必须评估业务影响程度（business_impact）。

审查反馈：
{review_feedback}

上一轮分析结果：
{last_result_text}

错误日志：
{error_log}

补全日志：
{logs_preview}

代码证据：
{evidence_preview}

请输出优化后的JSON格式：
{schema_example}"""

ANALYZER_HYBRID_REVIEW_USER_PROMPT = """以下是分阶段分析的结果：

摘要：{summary}
可能原因：{hypotheses}
建议：{suggestions}
业务影响：{business_impact}

请审查上述分析，找出需要改进的地方。必须评估业务影响程度（business_impact）。"""

ANALYZER_HYBRID_REFINE_USER_PROMPT = """基于以下审查反馈，请优化分析结果：

审查反馈：{review_feedback}

原始错误日志：
{error_log}

请输出优化后的JSON格式分析结果，必须包含 business_impact（高|中|低|无，可附带说明）。"""

ANALYZER_SUPPLEMENTARY_EVIDENCE_PROMPT = """已根据你请求的 NEED_MORE_EVIDENCE 补充检索了 {need_terms}，追加了 {added} 条证据。请基于更新后的证据重新分析。"""

# Enricher Prompts
ENRICHER_TRACE_ID_SYSTEM_PROMPT = """你是一个日志分析专家。你的任务是从错误日志中识别 trace_id 和 request_id。这些标识符通常用于关联分布式系统中的请求调用链。输出必须是 JSON 格式，不要包含多余文本。"""

ENRICHER_TRACE_ID_USER_PROMPT = """请从以下错误日志中识别 trace_id 和 request_id。

错误日志：
{log_preview}

请分析日志内容，找出最可能是 trace_id 和 request_id 的值。
常见的格式包括：
- UUID 格式：36dfc57c26a84cdcbdc608d8e1d31ee3
- 长字符串：0a690987177010502886340281
- 在日志中以 [trace_id: xxx] 或 trace_id=xxx 等形式出现
- 在 JSON 格式的日志中以 trace_id 或 request_id 字段出现

如果找不到，返回 null。

请输出 JSON 格式：
{{"trace_id": "xxx 或 null", "request_id": "xxx 或 null"}}"""
