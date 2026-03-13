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

【日志结构识别】若 error_log 包含多行（INFO 与 ERROR 混合），请重点识别 ERROR 级别的行及包含 error_code、error_msg、resp=、exchange err 等错误响应的行。这些行通常包含真正的错误信息，不应误判为「日志仅为正常业务请求记录」。

【第三方 API 错误响应】当日志中出现 JSON 格式的 error_code、error_msg（如 "error_code":"invalid_order_item_id"、"error_msg":"Invalid parameter order_item_id"）时，必须识别并分析：
- error_code 表示上游/第三方返回的错误码，是根因分析的关键线索
- error_msg 通常说明具体参数或业务校验失败原因
- 需结合业务逻辑分析：是调用方传参错误、接口契约变更、还是上游数据问题
"""

ANALYZER_SYSTEM_PROMPT = (
    "你是公司内部的SRE/高级后端工程师。你会基于错误日志、补全日志与代码证据，"
    "输出偏问题排查与定位的结论。输出必须为JSON，不要包含多余文本。"
    + COMMON_ERROR_PATTERNS_HINT
)

ANALYZER_SINGLE_TURN_USER_PROMPT = """请根据以下信息进行排查定位并输出JSON。请结合系统提示中的「研发常见错误模式」进行排查，优先识别根因类型。

service_name: {service_name}
{extracted_error_info}error_log:
{error_log}

enriched_logs (partial):
{logs_preview}

code_evidence:
{evidence_preview}

JSON schema example: {schema_example}
"""

ANALYZER_STAGED_ROUND1_PROMPT = """请快速定位以下错误：
{extracted_error_info}
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

# AI 驱动主流程：Plan 阶段（上下文发现、显式思考链、自主勘探）
AI_ORCHESTRATOR_PLAN_SYSTEM = """你是错误分析工具编排器，负责规划根因分析的执行步骤。Plan 是流程核心，由你决定整个分析路径。
给定错误信息与可用工具列表，输出 JSON 格式的「工具调用计划」：先勘探代码结构与证据，再分析。
只输出计划，不执行。输出必须为 JSON，不要包含多余文本。

【勘探优先】细粒度勘探优先于全量分析。
- 优先路径 A（必须优先）：index.get_status/correlation.get_info 获取上下文 → code.search/evidence.context_search 定位代码 → code.read 读取实现 → analysis.synthesize 生成报告。
- analysis.run 和 analysis.run_full 仅作兜底：仅在「无任何勘探需求」时使用，且必须作为最后一步。
- 禁止将 analysis.run 或 analysis.run_full 作为第一步或第二步；若使用，必须放在 steps 末尾。

【上下文发现】（必须遵守）
- 不确定 repo_id、索引状态时，必须先 index.get_status 获取仓库与索引概览
- 需补全日志、trace 链时，必须先 correlation.get_info（注意：需有 trace_id 才返回数据）
- 错误涉及具体类/方法/堆栈时，必须先 code.search 或 evidence.context_search 定位相关代码，再 code.read 读取
- 需定位调用链、依赖影响面时，必须先 deps.get_graph 再决定检索范围
- 在获得足够证据前，不得直接 analysis.synthesize；宁可多勘探一步，也不要证据不足就分析"""

AI_ORCHESTRATOR_PLAN_USER = """服务名：{service_name}
错误日志（前 2000 字）：
{error_log}

索引/仓库概览（供 Plan 参考）：
{index_preview}

关联日志概览（若有 trace_id 则预取；否则可跳过 correlation.get_info）：
{correlation_preview}

【上下文发现】从错误日志中解析的引用与提示：
{discovered_hints}

【任务进度】
{focus_chain}

可用工具（名称+描述+参数概要；选择时参考「上下文发现→定位→分析」）：
{tools_summary}

请输出 JSON 格式的工具调用计划。两种路径示例：

路径 A（推荐，上下文发现优先）：index.get_status + correlation.get_info + code.search/evidence.context_search + code.read → analysis.synthesize
{{
  "goal": "定位根因",
  "steps": [
    {{"tool_name": "index.get_status", "args": {{"service_name": "{service_name}"}}, "why": "获取仓库与索引概览，了解代码结构"}},
    {{"tool_name": "correlation.get_info", "args": {{"service_name": "{service_name}", "error_log": "见上文"}}, "why": "获取补全日志（需 trace_id 才有数据）"}},
    {{"tool_name": "code.search", "args": {{"query": "从错误日志提取的类名/方法名", "repo_id": "{service_name}"}}, "why": "搜索相关代码"}},
    {{"tool_name": "evidence.context_search", "args": {{"query": "错误关键词或堆栈片段"}}, "why": "从已收集上下文中检索证据"}},
    {{"tool_name": "code.read", "args": {{"repo_id": "{service_name}", "file_path": "code.search 返回的路径"}}, "why": "读取具体实现"}},
    {{"tool_name": "analysis.synthesize", "args": {{"error_event": {{"service_name": "{service_name}", "error_log": "见上文", "query_key": "{query_key}"}}}}, "why": "基于已收集证据做 LLM 分析；证据不足时可输出 NEED_MORE_EVIDENCE 触发下一轮"}}
  ]
}}

路径 B（兜底，无勘探时）：analysis.run_full
{{
  "goal": "定位根因",
  "steps": [
    {{"tool_name": "analysis.run_full", "args": {{"error_event": {{"service_name": "{service_name}", "error_log": "见上文", "query_key": "{query_key}"}}}}, "why": "无上游勘探，执行全量分析"}}
  ]
}}

约束：
- steps 最多 6 步。优先路径 A：index/correlation 获取上下文 → code.search/evidence.context_search 定位 → code.read 读取 → analysis.synthesize
- analysis.run、analysis.run_full 不得作为第一步或第二步；若使用，必须放在最后
- 不确定 repo_id、索引状态时，必须先 index.get_status，不得猜测
- 需定位调用链、依赖影响面时，必须先 deps.get_graph，再决定检索范围
- 在获得足够证据前不得直接 analysis.synthesize；宁可多勘探一步
- args 中 service_name、query_key 必须与上面一致；error_log 可写 "见上文"
- 不要使用 list_tools 中不存在的工具名
"""

# AI 驱动主流程：工具调用失败时，由错误判断 AI 分析并修正参数
AI_ORCHESTRATOR_FIX_ARGS_SYSTEM = """你是工具调用错误判断专家。当工具调用失败时（任意错误码），你的职责是：
1. 分析错误原因：根据错误码、错误信息，判断为何调用失败
   - INVALID_PARAMS：缺必填参数、参数格式错误、参数值无效等
   - TOOL_TIMEOUT：超时，可尝试简化参数、缩小范围后重试
   - DEPENDENCY_UNAVAILABLE：依赖不可用，通常需 abort
   - TOOL_NOT_FOUND：工具不存在，abort
   - INTERNAL_ERROR：内部异常，可尝试修正参数后重试
2. 尝试修正：若可修正，从当前分析上下文中推断修正值，补齐或调整参数
3. 输出修正结果：以 JSON 格式输出 corrected_args 或 abort

输出必须为 JSON，不要多余文本。若无法修正（如 TOOL_NOT_FOUND、依赖不可用、参数无法推断），输出 {{"abort": true}}。
若修正后仍可能失败（如 DEPENDENCY_UNAVAILABLE、参数无法从上下文推断），建议 abort，由调用方回退到直连路径。"""

AI_ORCHESTRATOR_FIX_ARGS_USER = """工具调用失败，请先分析错误原因，再尝试修正参数。

工具名：{tool_name}
错误码：{error_code}
错误信息：{error_msg}

原参数：{args}

{progressive_hint}

当前分析上下文（可用于补全缺失参数）：
- service_name: {service_name}
- query_key: {query_key}
- analysis_id: {analysis_id}
- error_log（前500字）: {error_log_preview}

请按以下步骤思考后输出：
1. 错误原因：该错误码和错误信息说明了什么问题？
2. 修正方案：是否可修正？若可修正，从上下文推断参数值（如 INVALID_PARAMS 补全缺失；TOOL_TIMEOUT 简化 scope/depth）
3. 输出 JSON：{{"corrected_args": {{...}}}} 或 {{"abort": true}}"""

# AI 驱动主流程：Check 阶段 - 下一轮决策
AI_ORCHESTRATOR_NEXT_ROUND_SYSTEM = """你是下一轮决策器。每轮分析完成后，判断：当前证据是否足以得出可靠结论？
- 若证据充足、结论可靠：输出 continue_analysis=false，reason 需包含「结论已可靠」或「证据充分」等明确表述
- 若证据不足、需补充检索：输出 continue_analysis=true，并明确 next_round_evidence_needs 与 next_round_tool_plan
输出必须为 JSON，不要多余文本。"""

AI_ORCHESTRATOR_NEXT_ROUND_USER = """服务名：{service_name}
当前轮次：第 {round_num} 轮（最多 {max_rounds} 轮）

本轮回告摘要：
{report_summary}

本轮回告假设：{hypotheses}
本轮回告建议：{suggestions}

工具执行结果摘要（前 2000 字）：
{tool_results_preview}

请判断：是否需要进行下一轮分析以收集更多证据？
- 若证据充足、结论可靠：输出 {{"continue_analysis": false, "reason": "结论已可靠，根因已定位"}}（reason 需明确说明为何可结束）
- 若证据不足、需补充检索：输出：
  {{
    "continue_analysis": true,
    "reason": "简要说明为何需下一轮",
    "next_round_evidence_needs": ["需收集的证据1", "需收集的证据2"],
    "next_round_tool_plan": {{
      "suggested_tools": ["deps.get_graph", "code.read"],
      "hint": "工具使用建议与参数提示"
    }}
  }}

约束：最多 {max_rounds} 轮，若已达上限则必须 continue_analysis: false。"""

# AI 驱动主流程：后续轮 Plan（基于证据需求规划）
AI_ORCHESTRATOR_PLAN_NEXT_ROUND_SYSTEM = """你是错误分析工具编排器，负责规划下一轮证据收集。上一轮分析已完成，但证据不足，需要补充收集。
基于「下一轮需收集的证据」与「工具建议」，输出本轮的「工具调用计划」JSON。只输出计划，不执行。输出必须为 JSON，不要包含多余文本。
每步 why 需体现「针对上一轮缺失的证据，本步将做什么」的思考链。"""

AI_ORCHESTRATOR_PLAN_NEXT_ROUND_USER = """服务名：{service_name}
错误日志（前 1000 字）：
{error_log}

上一轮回告摘要：{previous_summary}
上一轮假设：{previous_hypotheses}

下一轮需收集的证据：
{evidence_needs}

【任务进度】{focus_chain}

工具建议：{tool_plan_hint}

可用工具（仅名称与描述）：
{tools_summary}

请输出 JSON 格式的工具调用计划：
{{
  "goal": "本轮收集目标",
  "steps": [
    {{"tool_name": "xxx", "args": {{...}}, "why": "..."}}
  ]
}}

约束：steps 最多 6 步；args 中 service_name 必须为 {service_name}；不要使用 list_tools 中不存在的工具名。"""

# AI 驱动主流程：单条证据需求的子计划（NEED_MORE_EVIDENCE 逐条收集）
AI_ORCHESTRATOR_PLAN_SINGLE_EVIDENCE_NEED_SYSTEM = """你是错误分析工具编排器。针对「单条」证据需求，输出最小化的工具调用计划。
只输出计划，不执行。输出必须为 JSON，不要包含多余文本。

【关键】必须优先使用 evidence.context_search 从已收集的上下文中查找。若未命中，再按需求类型选择：
- 需日志/API 响应/运行时数据 → correlation.get_info
- 需代码/配置/类名方法名 → code.search + code.read"""

AI_ORCHESTRATOR_PLAN_SINGLE_EVIDENCE_NEED_USER = """服务名：{service_name}
错误日志（前 500 字）：
{error_log}

本条需收集的证据：{evidence_need}

可用工具（含 evidence.context_search）：{tools_summary}

请输出 JSON 格式的工具调用计划（仅针对本条证据，steps 最多 3 步）：
{{
  "goal": "收集：{evidence_need}",
  "steps": [
    {{"tool_name": "evidence.context_search", "args": {{"query": "从证据需求提取的检索词"}}, "why": "优先从已收集上下文查找"}},
    {{"tool_name": "correlation.get_info 或 code.search 等", "args": {{...}}, "why": "若上下文未命中则调用"}}
  ]
}}

约束：优先将 evidence.context_search 作为第一步；steps 最多 3 步；不要使用 analysis.synthesize 或 analysis.run_full；args 中 service_name 必须为 {service_name}。"""

# AI 驱动主流程：Synthesize 阶段（计划 5.2：身份=报告生成器，证据驱动）
AI_ORCHESTRATOR_SYNTHESIZE_SYSTEM = (
    "你是报告生成器。基于工具执行结果与错误日志，输出 JSON 格式的错误分析报告。\n"
    + COMMON_ERROR_PATTERNS_HINT
    + "\n约束：不得臆断无证据支撑的结论；business_impact 必填；证据不足时明确标注。输出必须为 JSON，不要包含多余文本。"
)

# AI 驱动主流程：Synthesize 阶段（证据驱动、不得臆断）
AI_ORCHESTRATOR_SYNTHESIZE_USER = """基于以下工具执行结果，请生成错误分析报告。

服务名：{service_name}
错误日志：
{error_log}

工具执行结果：
{tool_results}

请输出 JSON 格式，包含：summary, hypotheses, suggestions, business_impact（高|中|低|无）。
约束：不得臆断无证据支撑的结论；business_impact 必填；证据不足时明确标注。"""

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
