# LLM 多轮对话优化方案

## 一、当前问题分析

### 1.1 现状

当前系统采用**单轮对话模式**：
- 一次性发送所有证据（错误日志 + 补全日志 + 代码证据）
- 要求 LLM 一次性输出完整分析（summary + hypotheses + suggestions）
- 没有迭代优化机制

### 1.2 存在的问题

1. **上下文过载**：一次性发送大量证据，可能导致：
   - Token 消耗高
   - LLM 难以聚焦关键信息
   - 分析深度不够

2. **缺乏迭代优化**：
   - 无法基于初步结果深入分析
   - 无法自我审查和纠正
   - 无法逐步细化问题定位

3. **分析质量受限**：
   - 复杂错误需要多角度分析，单轮难以覆盖
   - 无法根据初步结果动态调整证据收集策略
   - 缺乏反馈循环机制

## 二、参考模式：Cursor 和 Trae

### 2.1 Cursor 的多轮对话模式

**核心特点**：
- **上下文累积**：每轮对话都保留历史上下文
- **迭代细化**：从粗到细，逐步深入
- **动态调整**：根据前一轮结果调整策略

**示例流程**：
```
Round 1: "帮我实现用户认证"
  → LLM: [生成基础实现]

Round 2: "添加 JWT token 支持"
  → LLM: [基于 Round 1 的结果，添加 JWT]

Round 3: "增加刷新 token 机制"
  → LLM: [基于 Round 1+2 的结果，添加刷新机制]
```

### 2.2 Trae/Self-Refine 的迭代优化模式

**核心特点**：
- **自我反馈**：LLM 对自己的输出进行审查
- **迭代优化**：生成 → 反馈 → 优化 → 再反馈
- **逐步改进**：每轮都基于前一轮的反馈进行优化

**示例流程**：
```
Round 1: 生成初步分析
  → LLM: [summary, hypotheses, suggestions]

Round 2: 自我审查
  → LLM: "请审查上述分析，找出遗漏或不够深入的地方"
  → LLM: [反馈：哪些地方需要深入，哪些证据需要补充]

Round 3: 基于反馈优化
  → LLM: [基于反馈，优化分析结果]
```

## 三、优化方案设计

### 3.1 方案 A：分阶段多轮分析（推荐）

**设计思路**：将分析过程分为多个阶段，每个阶段聚焦不同目标

**流程设计**：

```
阶段 1：快速定位（Quick Diagnosis）
  输入：错误日志 + 堆栈跟踪
  目标：快速定位问题位置和类型
  输出：{
    "problem_location": "文件路径:行号",
    "error_type": "异常类型",
    "quick_summary": "一句话总结"
  }

阶段 2：深入分析（Deep Analysis）
  输入：阶段1结果 + 相关代码证据（Zoekt + Qdrant）
  目标：深入分析根本原因
  输出：{
    "root_cause": "根本原因分析",
    "hypotheses": ["可能原因1", "可能原因2"],
    "evidence_analysis": "关键证据分析"
  }

阶段 3：生成建议（Solution Generation）
  输入：阶段1+2结果 + 补全日志
  目标：生成具体的修复建议
  输出：{
    "suggestions": ["建议1", "建议2"],
    "priority": "高/中/低",
    "implementation_hints": "实现提示"
  }
```

**优势**：
- 每轮聚焦单一目标，分析更深入
- 可以根据前一轮结果动态调整证据收集
- 降低单次 Token 消耗
- 符合人类分析问题的思维模式

**实现要点**：
- 每轮保留对话历史（messages 数组累积）
- 阶段2可以根据阶段1的结果，有针对性地收集更多证据
- 阶段3可以基于前两轮结果，生成更精准的建议

### 3.2 方案 B：Self-Refine 迭代优化

**设计思路**：生成初步分析后，让模型自我审查并优化

**流程设计**：

```
Round 1：初步分析
  输入：所有证据
  输出：初步的 summary + hypotheses + suggestions

Round 2：自我审查
  输入：Round 1 的输出 + 原始证据
  Prompt: "请审查上述分析，找出：
    1. 哪些原因分析不够深入？
    2. 哪些关键证据被遗漏？
    3. 哪些建议不够具体？
    请指出需要改进的地方。"
  输出：审查反馈

Round 3：优化分析
  输入：Round 1 输出 + Round 2 反馈 + 原始证据
  输出：优化后的 summary + hypotheses + suggestions
```

**优势**：
- 可以自我发现遗漏和不足
- 逐步改进分析质量
- 不需要人工干预

**实现要点**：
- 需要设计好的审查 prompt
- 可能需要限制迭代轮数（避免无限循环）
- 可以设置质量阈值（如果改进幅度小，提前终止）

### 3.3 方案 C：混合模式（推荐用于复杂错误）

**设计思路**：结合方案 A 和 B，先分阶段分析，再迭代优化

**流程设计**：

```
阶段 1：快速定位（同方案 A）
阶段 2：深入分析（同方案 A）
阶段 3：生成建议（同方案 A）

阶段 4：自我审查（可选，仅当错误复杂度高时）
  - 审查前三个阶段的分析
  - 找出遗漏或不够深入的地方

阶段 5：优化分析（可选）
  - 基于审查反馈，优化分析结果
```

**优势**：
- 结合两种模式的优点
- 对于简单错误，3 阶段即可
- 对于复杂错误，可以启用 4-5 阶段

**实现要点**：
- 需要定义"错误复杂度"的评估标准
- 可以配置是否启用 4-5 阶段

## 四、技术实现方案

### 4.1 LLM Provider 扩展

**当前接口**：
```python
async def generate(self, *, system: str, user: str) -> str
```

**扩展为多轮对话**：
```python
async def generate_multi_turn(
    self,
    *,
    system: str,
    messages: list[dict[str, str]],  # [{"role": "user", "content": "..."}, ...]
) -> str

# 或者保持向后兼容，新增方法
async def generate_with_history(
    self,
    *,
    system: str,
    conversation_history: list[dict[str, str]],
    user: str,
) -> str
```

**消息格式**：
```python
[
    {"role": "system", "content": "..."},
    {"role": "user", "content": "Round 1 prompt"},
    {"role": "assistant", "content": "Round 1 response"},
    {"role": "user", "content": "Round 2 prompt"},
    {"role": "assistant", "content": "Round 2 response"},
    {"role": "user", "content": "Round 3 prompt"},
]
```

### 4.2 AnalyzerService 重构

**新增方法**：
```python
async def _generate_report_multi_turn(
    self,
    *,
    analysis_id: str,
    event: NormalizedErrorEvent,
    log_bundle: LogBundle,
    evidence: EvidencePack,
) -> AnalysisReport:
    """
    多轮对话生成报告
    
    流程：
    1. Round 1: 快速定位
    2. Round 2: 深入分析（基于 Round 1 结果，可能需要补充证据）
    3. Round 3: 生成建议
    4. （可选）Round 4-5: 自我审查和优化
    """
```

**对话历史管理**：
```python
class ConversationHistory:
    def __init__(self):
        self.messages: list[dict[str, str]] = []
    
    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})
    
    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})
    
    def to_api_format(self, system: str) -> list[dict[str, str]]:
        return [{"role": "system", "content": system}] + self.messages
```

### 4.3 配置项扩展

**新增配置**：
```yaml
llm:
  # ... 现有配置 ...
  
  # 多轮对话配置
  multi_turn:
    enabled: true                    # 是否启用多轮对话
    mode: "staged"                   # "staged" | "self_refine" | "hybrid"
    max_rounds: 3                    # 最大轮数
    enable_self_review: false        # 是否启用自我审查（仅 hybrid 模式）
    
    # 分阶段模式配置
    staged:
      round1_quick_diagnosis: true   # 阶段1：快速定位
      round2_deep_analysis: true     # 阶段2：深入分析
      round3_solution_gen: true      # 阶段3：生成建议
      
    # Self-Refine 模式配置
    self_refine:
      review_rounds: 1               # 审查轮数
      improvement_threshold: 0.1     # 改进阈值（如果改进幅度小于此值，提前终止）
```

### 4.4 Prompt 设计

#### Round 1: 快速定位 Prompt

```
你是公司内部的SRE/高级后端工程师。请快速定位以下错误：

错误日志：
{error_log}

请输出JSON格式：
{
  "problem_location": "文件路径:行号（从堆栈中提取）",
  "error_type": "异常类型",
  "quick_summary": "一句话总结问题"
}
```

#### Round 2: 深入分析 Prompt

```
基于第一轮的定位结果，请深入分析根本原因：

第一轮定位结果：
{round1_result}

相关代码证据：
{code_evidence}

请输出JSON格式：
{
  "root_cause": "根本原因分析（2-3句话）",
  "hypotheses": ["可能原因1", "可能原因2", "可能原因3"],
  "evidence_analysis": "关键证据分析（说明哪些代码片段支持上述假设）"
}
```

#### Round 3: 生成建议 Prompt

```
基于前两轮的分析结果，请生成具体的修复建议：

定位结果：
{round1_result}

原因分析：
{round2_result}

补全日志（上下文）：
{enriched_logs}

请输出JSON格式：
{
  "suggestions": ["建议1（具体可操作）", "建议2", "建议3"],
  "priority": "高/中/低",
  "implementation_hints": "实现提示（可选）"
}
```

#### Round 4: 自我审查 Prompt（可选）

```
请审查上述分析结果，找出：
1. 哪些原因分析不够深入？
2. 哪些关键证据被遗漏？
3. 哪些建议不够具体？

请输出JSON格式：
{
  "review_feedback": ["反馈1", "反馈2"],
  "needs_improvement": ["需要改进的地方1", "需要改进的地方2"]
}
```

## 五、实施计划

### 5.1 阶段 1：基础扩展（1-2 天）

1. **扩展 LLM Provider 接口**
   - 添加 `generate_multi_turn` 方法
   - 支持 messages 数组格式
   - 保持向后兼容

2. **实现 ConversationHistory 类**
   - 管理对话历史
   - 转换为 API 格式

3. **配置项扩展**
   - 添加多轮对话配置
   - 默认禁用（保持现有行为）

### 5.2 阶段 2：实现分阶段模式（2-3 天）

1. **实现 `_generate_report_staged` 方法**
   - Round 1: 快速定位
   - Round 2: 深入分析
   - Round 3: 生成建议

2. **动态证据收集**
   - Round 2 可以根据 Round 1 结果，补充收集相关证据

3. **结果合并**
   - 将三轮结果合并为最终的 AnalysisReport

### 5.3 阶段 3：实现 Self-Refine 模式（2-3 天）

1. **实现 `_generate_report_self_refine` 方法**
   - Round 1: 初步分析
   - Round 2: 自我审查
   - Round 3: 优化分析

2. **质量评估**
   - 评估改进幅度
   - 提前终止机制

### 5.4 阶段 4：混合模式与优化（1-2 天）

1. **实现混合模式**
   - 结合分阶段和 Self-Refine

2. **错误复杂度评估**
   - 根据错误类型、证据数量等评估复杂度
   - 决定是否启用 Self-Refine

3. **性能优化**
   - 缓存中间结果
   - 并行处理（如果可能）

### 5.5 阶段 5：测试与调优（2-3 天）

1. **单元测试**
   - 测试各轮对话
   - 测试结果合并

2. **集成测试**
   - 端到端测试
   - 对比单轮和多轮的效果

3. **Prompt 调优**
   - 根据实际效果调整 prompt
   - A/B 测试不同 prompt

## 六、预期效果

### 6.1 分析质量提升

- **更深入的原因分析**：多轮对话可以逐步深入，不会一次性处理所有信息
- **更精准的建议**：基于前两轮结果，第三轮可以生成更具体的建议
- **更少的遗漏**：自我审查可以发现遗漏的问题

### 6.2 成本优化

- **Token 消耗**：虽然总轮数增加，但每轮的上下文更聚焦，可能总消耗相近或略增
- **时间成本**：多轮对话会增加延迟，但可以通过并行优化

### 6.3 灵活性提升

- **可配置**：可以选择不同的模式
- **可扩展**：易于添加新的对话轮次
- **向后兼容**：默认禁用，不影响现有功能

## 七、风险评估

### 7.1 技术风险

- **API 兼容性**：需要确保所有 LLM Provider 都支持多轮对话
- **Token 限制**：多轮对话可能导致总 Token 数增加
- **延迟增加**：多轮对话会增加总耗时

### 7.2 缓解措施

- **渐进式实施**：先实现基础功能，再逐步优化
- **配置开关**：默认禁用，可以逐步启用
- **超时控制**：每轮设置超时，避免无限等待
- **降级机制**：如果多轮失败，降级到单轮模式

## 八、后续优化方向

1. **智能证据收集**：根据前一轮结果，智能决定需要补充哪些证据
2. **并行处理**：某些轮次可以并行处理
3. **结果缓存**：缓存中间结果，避免重复计算
4. **Prompt 模板化**：支持自定义 prompt 模板
5. **A/B 测试**：对比不同模式的效果

## 九、总结

多轮对话优化可以显著提升分析质量，但需要：
1. **渐进式实施**：分阶段实现，逐步验证效果
2. **配置灵活**：提供多种模式，适应不同场景
3. **向后兼容**：不影响现有功能
4. **性能平衡**：在质量和性能之间找到平衡

建议**优先实施方案 A（分阶段多轮分析）**，因为：
- 实现相对简单
- 效果提升明显
- 风险可控
- 符合人类分析问题的思维模式
