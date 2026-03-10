# AI 日志分析系统与大模型交互原理

## 一、整体架构

```
错误日志 → 证据收集 → Prompt 构建 → LLM API 调用 → JSON 解析 → 分析报告
```

## 二、核心组件

### 1. LLM Provider（`root_seeker/providers/llm.py`）

**职责**：封装 OpenAI 兼容的 API 调用

**实现类**：`OpenAICompatLLM`

**关键方法**：
```python
async def generate(self, *, system: str, user: str) -> str:
    """
    调用 LLM API 生成回复
    
    Args:
        system: System prompt（角色定义）
        user: User prompt（具体任务内容）
    
    Returns:
        LLM 返回的文本内容
    """
```

**API 请求格式**：
```json
{
  "model": "deepseek-chat",
  "messages": [
    {"role": "system", "content": "你是公司内部的SRE/高级后端工程师..."},
    {"role": "user", "content": "请根据以下信息进行排查定位..."}
  ],
  "temperature": 0.2,
  "max_tokens": 2000
}
```

**支持的模型**：
- DeepSeek（默认）
- 豆包（Doubao）
- 其他 OpenAI 兼容的 API

### 2. LLM Wrapper（`root_seeker/providers/llm_wrapped.py`）

**职责**：为 LLM Provider 添加运行时保护

**实现类**：`RateLimitedCircuitBreakerLLM`

**功能**：
1. **并发控制**：使用 `asyncio.Semaphore` 限制并发请求数（默认 4）
2. **熔断器**：连续失败 5 次后自动熔断，30 秒后恢复
3. **审计日志**：记录每次调用的哈希、字符数、耗时、状态

**代码示例**：
```python
async def generate(self, *, system: str, user: str) -> str:
    if not self._breaker.allow():
        raise RuntimeError("llm circuit breaker open")
    
    async with self._sem:  # 并发控制
        try:
            out = await self._inner.generate(system=system, user=user)
            self._breaker.on_success()
            # 记录审计日志
            return out
        except Exception as e:
            self._breaker.on_failure()
            raise
```

### 3. Analyzer Service（`root_seeker/services/analyzer.py`）

**职责**：协调整个分析流程，包括证据收集和 LLM 调用

**关键方法**：`_generate_report`

## 三、交互流程详解

### 步骤 1：证据收集（Evidence Collection）

在调用 LLM 之前，系统会收集以下证据：

1. **错误日志**：原始错误堆栈
2. **补全日志**：从 SLS 查询的相关日志（通过 `query_key` 和 SQL 模板）
3. **代码证据**：
   - **堆栈跟踪**：从堆栈中提取的文件路径和行号
   - **Zoekt 命中**：词法检索找到的相关代码片段
   - **向量检索**：语义相似的相关代码片段
   - **调用链展开**：通过 Tree-sitter 解析的方法调用关系

### 步骤 2：Prompt 构建（`_build_llm_user_prompt`）

**System Prompt**（固定）：
```
你是公司内部的SRE/高级后端工程师。你会基于错误日志、补全日志与代码证据，
输出偏问题排查与定位的结论。输出必须为JSON，不要包含多余文本。
```

**User Prompt**（动态构建）：
```
请根据以下信息进行排查定位并输出JSON：

service_name: enterprise-manage-api

error_log:
[原始错误堆栈]

enriched_logs (partial):
[从 SLS 补全的相关日志，最多 80 条]

code_evidence:
--- file_path:start_line-end_line (source) ---
[代码片段内容]
--- file_path:start_line-end_line (source) ---
[代码片段内容]
...

JSON schema example:
{
  "summary": "一句话到三句话，总结定位结论",
  "hypotheses": ["可能原因1", "可能原因2"],
  "suggestions": ["建议修改1", "建议修改2"]
}
```

**证据格式化**（`_format_evidence_for_llm`）：
- 每个代码片段包含：文件路径、行号范围、来源（stacktrace/zoekt/qdrant/call_graph）
- 按来源分类展示，便于 LLM 理解上下文

### 步骤 3：API 调用

**请求流程**：
```
AnalyzerService._generate_report()
  ↓
RateLimitedCircuitBreakerLLM.generate()
  ↓ (并发控制 + 熔断检查)
OpenAICompatLLM.generate()
  ↓ (HTTP POST)
DeepSeek/Doubao API
```

**请求参数**：
- `base_url`: LLM API 地址（如 `https://api.deepseek.com`）
- `api_key`: API 密钥
- `model`: 模型名称（如 `deepseek-chat`）
- `temperature`: 0.2（较低，保证输出稳定性）
- `timeout`: 60 秒

**响应处理**：
```python
resp = await self._client.post(url, json=payload, headers=headers)
data = resp.json()
content = data["choices"][0]["message"]["content"]
```

### 步骤 4：JSON 解析（`_try_parse_json`）

**解析策略**：
1. 尝试直接解析 JSON
2. 如果失败，尝试提取代码块中的 JSON（```json ... ```）
3. 如果仍失败，尝试提取第一个 `{...}` 块
4. 如果都失败，返回原始文本

**字段提取**：
```python
summary = parsed.get("summary") or ""
hypotheses = parsed.get("hypotheses") or []
suggestions = parsed.get("suggestions") or []
```

### 步骤 5：报告生成

**AnalysisReport 结构**：
```python
{
  "analysis_id": "uuid",
  "service_name": "enterprise-manage-api",
  "summary": "一句话总结",
  "hypotheses": ["原因1", "原因2"],
  "suggestions": ["建议1", "建议2"],
  "evidence": EvidencePack,  # 包含所有代码证据
  "raw_model_output": "原始 LLM 输出"
}
```

## 四、配置说明

### LLM 配置（`config.yaml`）

```yaml
llm:
  base_url: "https://api.deepseek.com"
  api_key: "sk-xxx"
  model: "deepseek-chat"
  temperature: 0.2
  timeout_seconds: 60.0
  max_tokens: 2000  # 可选
  chat_url: null     # 可选，自定义 chat endpoint
```

### 运行时配置

```yaml
llm_runtime:
  concurrency: 4              # 并发请求数
  breaker_failure_threshold: 5 # 熔断阈值
  breaker_reset_seconds: 30.0  # 熔断恢复时间
```

## 五、安全与审计

### 1. 审计日志

每次 LLM 调用都会记录：
- `type`: "llm_generate"
- `status`: "ok" 或 "error"
- `user_hash`: 用户 prompt 的 SHA256 哈希（用于追溯，不泄露内容）
- `user_chars`: 发送的字符数
- `elapsed_ms`: 耗时（毫秒）
- `error`: 错误信息（如果有）

### 2. 熔断保护

**触发条件**：连续失败 5 次

**熔断行为**：
- 立即拒绝新请求
- 抛出 `RuntimeError("llm circuit breaker open")`
- 30 秒后自动恢复

**用途**：防止 LLM 服务异常时拖垮整个系统

### 3. 并发控制

**机制**：使用 `asyncio.Semaphore(4)` 限制同时进行的 LLM 请求数

**好处**：
- 避免过多并发请求导致 API 限流
- 控制资源消耗
- 保护 LLM 服务稳定性

## 六、错误处理

### 1. LLM 未配置

如果 `llm` 配置为空，返回：
```python
{
  "summary": "未配置云端LLM，已完成检索与证据收集。",
  "suggestions": ["配置 llm.base_url/api_key/model 后可生成原因与修复建议。"]
}
```

### 2. API 调用失败

- **网络错误**：记录到审计日志，抛出异常
- **API 错误**：记录错误信息，触发熔断器
- **超时**：60 秒超时，记录到审计日志

### 3. JSON 解析失败

- 尝试多种解析策略
- 如果都失败，使用原始输出作为 `summary`
- `hypotheses` 和 `suggestions` 为空列表

## 七、性能优化

### 1. 异步调用

所有 LLM 调用都是异步的（`async/await`），不阻塞其他请求

### 2. 并发控制

通过 Semaphore 限制并发，避免资源耗尽

### 3. 熔断器

快速失败，避免等待超时

### 4. 证据包限制

- `max_files`: 最多文件数（默认 20）
- `max_chars_total`: 总字符数限制（默认 50000）
- `max_chars_per_file`: 单文件字符数限制（默认 5000）

**目的**：控制发送给 LLM 的上下文大小，避免：
- Token 超限
- 成本过高
- 响应变慢

## 八、扩展性

### 1. 支持多 LLM Provider

通过 `LLMProvider` Protocol 定义接口，可以轻松替换实现：
- DeepSeek
- 豆包
- OpenAI
- 其他 OpenAI 兼容的 API

### 2. 自定义 Prompt

可以修改 `_build_llm_user_prompt` 方法自定义 prompt 格式

### 3. 自定义解析

可以修改 `_try_parse_json` 方法支持不同的输出格式

## 九、示例流程

### 完整调用链

```
1. POST /ingest/aliyun-sls
   ↓
2. JobQueue 异步处理
   ↓
3. AnalyzerService.analyze()
   ↓
4. 收集证据（Zoekt + Qdrant + 调用链展开）
   ↓
5. AnalyzerService._generate_report()
   ↓
6. RateLimitedCircuitBreakerLLM.generate()
   ↓ (并发控制)
7. OpenAICompatLLM.generate()
   ↓ (HTTP POST)
8. DeepSeek API
   ↓ (JSON 响应)
9. JSON 解析
   ↓
10. AnalysisReport 生成
   ↓
11. 保存到 AnalysisStore
   ↓
12. 发送通知（WeCom/DingTalk/Console/File）
```

### 实际请求示例

**System Prompt**：
```
你是公司内部的SRE/高级后端工程师。你会基于错误日志、补全日志与代码证据，
输出偏问题排查与定位的结论。输出必须为JSON，不要包含多余文本。
```

**User Prompt**：
```
请根据以下信息进行排查定位并输出JSON：

service_name: enterprise-manage-api

error_log:
net.coolcollege.platform.cool.common.error.v2.ServiceException: no faces detected...
    at FaceRecognitionService.liveFaceDetection(FaceRecognitionService.java:592)
    ...

enriched_logs (partial):
[相关日志内容]

code_evidence:
--- FaceRecognitionService.java:562-622 (stacktrace) ---
public void liveFaceDetection(...) {
    DetectLivingFaceResponse response = client.detectLivingFaceAdvance(...);
    Long faceNumber = element.getFaceNumber();
    if (faceNumber < 1) {
        throw new ServiceException(FaceRecognitionErrContants.NO_FACES_DETECTED);
    }
    ...
}

JSON schema example:
{
  "summary": "一句话到三句话，总结定位结论",
  "hypotheses": ["可能原因1", "可能原因2"],
  "suggestions": ["建议修改1", "建议修改2"]
}
```

**LLM 响应**：
```json
{
  "summary": "人脸检测服务在活体检测阶段失败，原因是上传的图片中未检测到人脸。错误发生在FaceRecognitionService.liveFaceDetection方法中，由于阿里云人脸识别服务返回的faceNumber为0导致抛出ServiceException。",
  "hypotheses": [
    "用户上传的图片质量不佳，无法识别人脸特征",
    "图片包含多个人脸或无人脸",
    "图片格式或尺寸不符合阿里云人脸识别服务要求"
  ],
  "suggestions": [
    "前端增加图片质量校验，确保上传的是清晰单人正面照",
    "在调用阿里云服务前增加本地图片预检逻辑，检查人脸数量和质量",
    "优化错误提示信息，明确告知用户需要上传合格的单人照片"
  ]
}
```

## 十、总结

系统与大模型的交互遵循以下原则：

1. **证据驱动**：先收集充分的代码证据，再调用 LLM
2. **结构化输出**：要求 LLM 返回 JSON，便于解析和处理
3. **安全可靠**：通过熔断器、并发控制、审计日志保证稳定性
4. **可扩展**：支持多种 LLM Provider，易于替换和扩展
5. **成本可控**：通过证据包限制控制 Token 消耗

这种设计既保证了分析质量，又确保了系统的稳定性和可维护性。
