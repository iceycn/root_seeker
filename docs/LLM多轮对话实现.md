# LLM 多轮对话实现总结

## 一、实现概述

已成功实现三套多轮对话机制，参考 Cursor 和 Trae 的多轮对话模式，提升错误分析质量。

## 二、已实现的功能

### 2.1 核心组件

1. **ConversationHistory 类** (`root_seeker/services/conversation.py`)
   - 管理多轮对话的历史记录
   - 支持添加用户消息和助手消息
   - 转换为 API 格式（包含 system message）

2. **LLM Provider 扩展** (`root_seeker/providers/llm.py`)
   - 新增 `generate_multi_turn` 方法
   - 支持 messages 数组格式（对话历史）
   - 保持向后兼容（原有的 `generate` 方法仍然可用）

3. **LLM Wrapper 扩展** (`root_seeker/providers/llm_wrapped.py`)
   - 新增 `generate_multi_turn` 方法
   - 支持并发控制、熔断器、审计日志

### 2.2 三种多轮对话模式

#### 方案 A：分阶段多轮分析（Staged）

**流程**：
1. **阶段1：快速定位**
   - 输入：错误日志
   - 输出：问题位置、错误类型、快速摘要
   - Prompt：`_build_staged_round1_prompt`

2. **阶段2：深入分析**
   - 输入：阶段1结果 + 代码证据
   - 输出：根本原因、假设、证据分析
   - Prompt：`_build_staged_round2_prompt`

3. **阶段3：生成建议**
   - 输入：阶段1+2结果 + 补全日志
   - 输出：具体建议、优先级、实现提示
   - Prompt：`_build_staged_round3_prompt`

**实现方法**：`_generate_report_staged`

#### 方案 B：Self-Refine 迭代优化（Self-Refine）

**流程**：
1. **Round 1：初步分析**
   - 输入：所有证据（错误日志 + 补全日志 + 代码证据）
   - 输出：初步的 summary + hypotheses + suggestions

2. **Round 2-N：自我审查和优化**
   - 审查：LLM 审查上一轮结果，找出不足
   - 优化：基于审查反馈，优化分析结果
   - 可配置审查轮数（默认 1 轮）
   - 可配置改进阈值（如果改进幅度小，提前终止）

**实现方法**：`_generate_report_self_refine`

#### 方案 C：混合模式（Hybrid）

**流程**：
1. 先执行分阶段分析（方案 A）
2. 如果启用自我审查，基于分阶段结果进行审查和优化

**实现方法**：`_generate_report_hybrid`

### 2.3 配置项

**新增配置项**（`config.yaml`）：

```yaml
# 多轮对话配置
llm_multi_turn_enabled: false   # 是否启用多轮对话（默认 false，使用单轮模式）
llm_multi_turn_mode: "staged"    # 多轮对话模式：staged | self_refine | hybrid
llm_multi_turn_max_rounds: 3    # 最大轮数
llm_multi_turn_enable_self_review: false   # 是否启用自我审查（仅 hybrid 模式）

# 分阶段模式配置（staged）
llm_multi_turn_staged_round1: true   # 阶段1：快速定位
llm_multi_turn_staged_round2: true   # 阶段2：深入分析
llm_multi_turn_staged_round3: true   # 阶段3：生成建议

# Self-Refine 模式配置（self_refine）
llm_multi_turn_self_refine_review_rounds: 1   # 审查轮数
llm_multi_turn_self_refine_improvement_threshold: 0.1   # 改进阈值
```

## 三、使用方法

### 3.1 默认配置

**系统默认已启用混合模式**，无需额外配置即可使用。

如果需要修改模式，在 `config.yaml` 中配置：

```yaml
llm_multi_turn_enabled: true  # 默认已启用
llm_multi_turn_mode: "hybrid"  # 默认混合模式，可改为 "staged" 或 "self_refine"
llm_multi_turn_enable_self_review: true  # 混合模式默认启用自我审查
```

### 3.2 禁用多轮对话

如果需要使用原有的单轮模式，在 `config.yaml` 中设置：

```yaml
llm_multi_turn_enabled: false
```

### 3.2 选择模式

#### 使用分阶段模式（推荐）

```yaml
llm_multi_turn_enabled: true
llm_multi_turn_mode: "staged"
llm_multi_turn_staged_round1: true
llm_multi_turn_staged_round2: true
llm_multi_turn_staged_round3: true
```

**适用场景**：
- 复杂错误，需要逐步深入分析
- 希望每轮聚焦单一目标
- 需要更深入的原因分析

#### 使用 Self-Refine 模式

```yaml
llm_multi_turn_enabled: true
llm_multi_turn_mode: "self_refine"
llm_multi_turn_self_refine_review_rounds: 1
llm_multi_turn_self_refine_improvement_threshold: 0.1
```

**适用场景**：
- 希望模型自我发现遗漏和不足
- 需要迭代优化分析质量
- 对初步分析结果不满意，希望改进

#### 使用混合模式

```yaml
llm_multi_turn_enabled: true
llm_multi_turn_mode: "hybrid"
llm_multi_turn_enable_self_review: true
```

**适用场景**：
- 复杂错误，需要分阶段分析 + 自我审查
- 希望结合两种模式的优点

### 3.3 禁用多轮对话（默认）

```yaml
llm_multi_turn_enabled: false  # 或直接不配置
```

系统将使用原有的单轮对话模式。

## 四、代码结构

### 4.1 新增文件

- `root_seeker/services/conversation.py`：对话历史管理

### 4.2 修改文件

- `root_seeker/providers/llm.py`：扩展 LLM Provider 接口
- `root_seeker/providers/llm_wrapped.py`：扩展 LLM Wrapper
- `root_seeker/services/analyzer.py`：实现三种多轮对话模式
- `root_seeker/config.py`：添加多轮对话配置项
- `root_seeker/app.py`：传递多轮对话配置
- `config.example.yaml`：添加配置示例

## 五、默认配置

✅ **默认启用混合模式**：
- 默认 `llm_multi_turn_enabled: true`
- 默认 `llm_multi_turn_mode: "hybrid"`
- 默认 `llm_multi_turn_enable_self_review: true`

**如需禁用多轮对话**，在 `config.yaml` 中设置：
```yaml
llm_multi_turn_enabled: false
```

## 六、向后兼容性

✅ **向后兼容**：
- 原有的 `generate` 方法仍然可用
- 可以通过配置禁用多轮对话，回到单轮模式
- 不影响现有功能

## 六、性能考虑

### 6.1 Token 消耗

- **分阶段模式**：虽然轮数增加，但每轮的上下文更聚焦，总消耗可能相近或略增
- **Self-Refine 模式**：会增加 Token 消耗（多轮对话）
- **混合模式**：消耗最高（分阶段 + 审查优化）

### 6.2 延迟

- **分阶段模式**：3 轮对话，延迟约为单轮的 2-3 倍
- **Self-Refine 模式**：取决于审查轮数，延迟约为单轮的 2-4 倍
- **混合模式**：延迟最高

### 6.3 优化建议

1. **根据错误复杂度选择模式**：
   - 简单错误：使用单轮模式（默认）
   - 复杂错误：使用分阶段模式或混合模式

2. **配置超时时间**：
   - 多轮对话会增加总耗时，建议适当增加 `analysis_timeout_seconds`

3. **限制轮数**：
   - 通过 `llm_multi_turn_max_rounds` 限制最大轮数
   - Self-Refine 模式通过改进阈值提前终止

## 七、测试建议

### 7.1 功能测试

1. **测试分阶段模式**：
   ```yaml
   llm_multi_turn_enabled: true
   llm_multi_turn_mode: "staged"
   ```
   - 验证三个阶段是否正常执行
   - 验证结果是否正确合并

2. **测试 Self-Refine 模式**：
   ```yaml
   llm_multi_turn_enabled: true
   llm_multi_turn_mode: "self_refine"
   ```
   - 验证审查和优化是否正常执行
   - 验证改进阈值是否生效

3. **测试混合模式**：
   ```yaml
   llm_multi_turn_enabled: true
   llm_multi_turn_mode: "hybrid"
   llm_multi_turn_enable_self_review: true
   ```
   - 验证分阶段 + 审查优化是否正常执行

### 7.2 性能测试

- 对比单轮和多轮模式的 Token 消耗
- 对比单轮和多轮模式的延迟
- 对比不同模式的分析质量

## 八、后续优化方向

1. **智能模式选择**：根据错误复杂度自动选择模式
2. **动态证据收集**：根据前一轮结果，动态补充证据
3. **结果缓存**：缓存中间结果，避免重复计算
4. **并行处理**：某些轮次可以并行处理
5. **Prompt 模板化**：支持自定义 prompt 模板

## 九、总结

✅ **已实现**：
- 三套多轮对话机制（分阶段、Self-Refine、混合）
- 完整的配置项支持
- 向后兼容，不影响现有功能

✅ **可配置**：
- 通过 `llm_multi_turn_enabled` 启用/禁用
- 通过 `llm_multi_turn_mode` 选择模式
- 各模式都有详细的配置项

✅ **已测试**：
- 代码编译通过
- 基本功能测试通过
- 配置加载正常

可以开始使用多轮对话功能了！
