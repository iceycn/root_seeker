# Dify 下的 LLM 多轮补充数据调用方案

## 一、问题分析

### 当前系统的多轮对话模式

当前系统支持三种多轮对话模式：

1. **Staged（分阶段）**：分3个阶段逐步深入
   - Round 1: 快速定位（phenomenon）
   - Round 2: 深入分析（root_cause, hypotheses）
   - Round 3: 生成建议（suggestions）

2. **Self-Refine（自我优化）**：LLM 自我审查和改进
   - Round 1: 初步分析
   - Round 2-N: 审查 → 优化 → 评估改进

3. **Hybrid（混合）**：结合分阶段和自我优化
   - 先分阶段分析
   - 再自我审查和优化

### 核心需求

在多轮对话中，LLM 可能需要：
1. **补充检索**：根据初步分析结果，决定是否需要更多代码证据
2. **动态调整**：根据每轮结果决定是否继续下一轮
3. **条件分支**：根据分析质量选择不同的后续流程

## 二、Dify 实现方案

### 方案 A：使用 Dify 的循环和条件节点（推荐）

Dify 支持 **Loop（循环）** 和 **If-Else（条件分支）** 节点，可以完美实现多轮对话。

#### 架构设计

```
开始
  ↓
初步分析（LLM）
  ↓
判断是否需要补充数据（If-Else）
  ├─ 是 → 补充检索（调用 Tools）
  │        ↓
  │    继续分析（LLM）
  │        ↓
  │    回到判断节点（Loop）
  └─ 否 → 最终输出
```

#### 具体实现

**1. 工作流节点配置**

```json
{
  "nodes": [
    {
      "id": "start",
      "type": "start",
      "data": {
        "title": "开始",
        "variables": [
          {"variable": "error_log", "type": "string"},
          {"variable": "evidence", "type": "object"}
        ]
      }
    },
    {
      "id": "initial_analysis",
      "type": "llm",
      "data": {
        "title": "初步分析",
        "model": "deepseek-chat",
        "prompt": "基于以下错误日志和代码证据，进行初步分析。\n\n错误日志：\n{{error_log}}\n\n代码证据：\n{{evidence}}\n\n请输出 JSON 格式：\n{\n  \"summary\": \"初步摘要\",\n  \"needs_more_data\": true/false,\n  \"missing_info\": [\"需要的信息1\", \"需要的信息2\"],\n  \"confidence\": 0.0-1.0\n}",
        "response_format": "json_object"
      }
    },
    {
      "id": "check_needs_more_data",
      "type": "if-else",
      "data": {
        "title": "判断是否需要补充数据",
        "conditions": [
          {
            "variable": "{{initial_analysis.outputs.needs_more_data}}",
            "comparison_operator": "is",
            "value": true
          }
        ]
      }
    },
    {
      "id": "supplemental_search",
      "type": "code",
      "data": {
        "title": "补充检索",
        "code": "// 根据 missing_info 动态调用检索工具\nconst missingInfo = initial_analysis.outputs.missing_info;\nconst results = [];\n\nfor (const info of missingInfo) {\n  // 调用 Zoekt 检索\n  const zoektResult = await fetch('http://localhost:8000/dify/tools/zoekt_search', {\n    method: 'POST',\n    body: JSON.stringify({\n      query: info,\n      repo_path: repo.local_dir,\n      service_name: service_name\n    })\n  });\n  \n  // 调用向量检索\n  const vectorResult = await fetch('http://localhost:8000/dify/tools/vector_search', {\n    method: 'POST',\n    body: JSON.stringify({\n      query: info,\n      repo_path: repo.local_dir,\n      service_name: service_name\n    })\n  });\n  \n  results.push({\n    query: info,\n    zoekt: await zoektResult.json(),\n    vector: await vectorResult.json()\n  });\n}\n\nreturn { supplemental_evidence: results };"
      }
    },
    {
      "id": "refined_analysis",
      "type": "llm",
      "data": {
        "title": "深入分析",
        "model": "deepseek-chat",
        "prompt": "基于初步分析和补充证据，进行深入分析。\n\n初步分析：\n{{initial_analysis.outputs}}\n\n补充证据：\n{{supplemental_search.outputs.supplemental_evidence}}\n\n请输出 JSON 格式：\n{\n  \"summary\": \"最终摘要\",\n  \"hypotheses\": [\"可能原因1\", \"可能原因2\"],\n  \"suggestions\": [\"修复建议1\", \"修复建议2\"],\n  \"needs_more_data\": false\n}",
        "response_format": "json_object"
      }
    },
    {
      "id": "loop_control",
      "type": "loop",
      "data": {
        "title": "循环控制",
        "max_iterations": 3,
        "loop_variable": "iteration_count",
        "condition": "{{refined_analysis.outputs.needs_more_data}} === true && iteration_count < 3"
      }
    },
    {
      "id": "final_output",
      "type": "code",
      "data": {
        "title": "最终输出",
        "code": "return {\n  analysis: refined_analysis.outputs,\n  iteration_count: loop_control.outputs.iteration_count\n};"
      }
    }
  ],
  "edges": [
    {"source": "start", "target": "initial_analysis"},
    {"source": "initial_analysis", "target": "check_needs_more_data"},
    {"source": "check_needs_more_data", "target": "supplemental_search", "condition": "true"},
    {"source": "check_needs_more_data", "target": "final_output", "condition": "false"},
    {"source": "supplemental_search", "target": "refined_analysis"},
    {"source": "refined_analysis", "target": "loop_control"},
    {"source": "loop_control", "target": "check_needs_more_data", "condition": "continue"},
    {"source": "loop_control", "target": "final_output", "condition": "break"}
  ]
}
```

### 方案 B：使用 Dify 的 Agent 模式（更智能）

Dify 支持 **Agent** 模式，LLM 可以自主决定调用哪些工具。

#### 架构设计

```
开始
  ↓
Agent（LLM + Tools）
  ├─ 可以调用：Zoekt 检索
  ├─ 可以调用：向量检索
  ├─ 可以调用：调用链展开
  └─ 可以调用：Trace 链查询
  ↓
Agent 自主决定：
  - 是否需要更多数据？
  - 调用哪个工具？
  - 何时停止？
  ↓
最终输出
```

#### 具体实现

**1. 创建 Agent 工作流**

```json
{
  "name": "智能错误分析 Agent",
  "type": "agent",
  "model": {
    "provider": "openai",
    "name": "deepseek-chat",
    "base_url": "https://api.deepseek.com"
  },
  "prompt": "你是一个资深的 SRE 工程师，负责分析错误日志并找出根本原因。\n\n你可以使用以下工具：\n1. zoekt_search: 使用 Zoekt 进行代码词法检索\n2. vector_search: 使用向量检索查找相似代码\n3. call_graph_expander: 展开方法调用链\n4. trace_chain_retriever: 查询调用链日志\n\n工作流程：\n1. 首先分析错误日志，识别关键信息\n2. 根据分析结果，决定需要哪些代码证据\n3. 调用相应的工具获取证据\n4. 基于证据进行深入分析\n5. 如果发现信息不足，继续调用工具补充\n6. 直到有足够信息后，输出最终分析结果\n\n输出格式（JSON）：\n{\n  \"summary\": \"错误摘要\",\n  \"hypotheses\": [\"可能原因1\", \"可能原因2\"],\n  \"suggestions\": [\"修复建议1\", \"修复建议2\"],\n  \"evidence_used\": [\"使用的证据来源\"]\n}",
  "tools": [
    {
      "type": "custom",
      "name": "zoekt_search",
      "endpoint": "http://localhost:8000/dify/tools/zoekt_search",
      "parameters": {
        "query": {"type": "string", "description": "搜索查询"},
        "repo_path": {"type": "string", "description": "仓库路径"},
        "service_name": {"type": "string", "description": "服务名"}
      }
    },
    {
      "type": "custom",
      "name": "vector_search",
      "endpoint": "http://localhost:8000/dify/tools/vector_search",
      "parameters": {
        "query": {"type": "string", "description": "查询文本"},
        "repo_path": {"type": "string", "description": "仓库路径"},
        "service_name": {"type": "string", "description": "服务名"},
        "top_k": {"type": "number", "description": "返回数量", "default": 12}
      }
    },
    {
      "type": "custom",
      "name": "call_graph_expander",
      "endpoint": "http://localhost:8000/dify/tools/call_graph_expander",
      "parameters": {
        "method_name": {"type": "string", "description": "方法名"},
        "file_path": {"type": "string", "description": "文件路径"},
        "repo_path": {"type": "string", "description": "仓库路径"}
      }
    },
    {
      "type": "custom",
      "name": "trace_chain_retriever",
      "endpoint": "http://localhost:8000/dify/tools/trace_chain_retriever",
      "parameters": {
        "trace_id": {"type": "string", "description": "Trace ID"},
        "request_id": {"type": "string", "description": "Request ID"},
        "service_name": {"type": "string", "description": "服务名"}
      }
    }
  ],
  "max_iterations": 5,
  "stop_condition": "当分析结果置信度 >= 0.8 或达到最大迭代次数时停止"
}
```

**2. Agent 工作流程**

```
Agent 接收输入（错误日志 + 初始证据）
  ↓
LLM 分析并决定需要什么工具
  ↓
调用工具（Zoekt/Vector/CallGraph/Trace）
  ↓
LLM 基于工具结果继续分析
  ↓
判断：是否需要更多数据？
  ├─ 是 → 继续调用工具（循环）
  └─ 否 → 输出最终结果
```

### 方案 C：混合模式（Staged + Self-Refine）

结合分阶段和自我优化的优势。

#### 架构设计

```
开始
  ↓
阶段1：快速定位（LLM）
  ↓
判断是否需要深入分析（If-Else）
  ├─ 是 → 阶段2：深入分析（LLM + Tools）
  │        ↓
  │    阶段3：生成建议（LLM）
  │        ↓
  │    自我审查（LLM）
  │        ↓
  │    判断是否需要优化（If-Else）
  │        ├─ 是 → 优化分析（LLM）
  │        │        ↓
  │        │    回到自我审查（Loop）
  │        └─ 否 → 最终输出
  └─ 否 → 直接输出
```

#### 具体实现

```json
{
  "nodes": [
    {
      "id": "stage1_quick_locate",
      "type": "llm",
      "data": {
        "title": "阶段1：快速定位",
        "model": "deepseek-chat",
        "prompt": "快速定位错误的位置和类型。\n\n错误日志：\n{{error_log}}\n\n输出 JSON：\n{\n  \"phenomenon\": \"错误现象\",\n  \"location\": \"错误位置\",\n  \"needs_deep_analysis\": true/false\n}"
      }
    },
    {
      "id": "check_needs_deep",
      "type": "if-else",
      "data": {
        "conditions": [
          {
            "variable": "{{stage1_quick_locate.outputs.needs_deep_analysis}}",
            "operator": "is",
            "value": true
          }
        ]
      }
    },
    {
      "id": "stage2_deep_analysis",
      "type": "llm",
      "data": {
        "title": "阶段2：深入分析",
        "model": "deepseek-chat",
        "prompt": "基于快速定位结果，进行深入分析。\n\n快速定位：\n{{stage1_quick_locate.outputs}}\n\n代码证据：\n{{evidence}}\n\n请调用工具补充必要的代码证据，然后分析根本原因。\n\n输出 JSON：\n{\n  \"root_cause\": \"根本原因\",\n  \"hypotheses\": [\"可能原因1\", \"可能原因2\"]\n}",
        "tools": ["zoekt_search", "vector_search", "call_graph_expander"]
      }
    },
    {
      "id": "stage3_suggestions",
      "type": "llm",
      "data": {
        "title": "阶段3：生成建议",
        "model": "deepseek-chat",
        "prompt": "基于深入分析结果，生成修复建议。\n\n根本原因：\n{{stage2_deep_analysis.outputs.root_cause}}\n\n可能原因：\n{{stage2_deep_analysis.outputs.hypotheses}}\n\n输出 JSON：\n{\n  \"suggestions\": [\"修复建议1\", \"修复建议2\"],\n  \"summary\": \"完整摘要\"\n}"
      }
    },
    {
      "id": "self_review",
      "type": "llm",
      "data": {
        "title": "自我审查",
        "model": "deepseek-chat",
        "prompt": "审查上述分析结果，找出需要改进的地方。\n\n分析结果：\n{{stage3_suggestions.outputs}}\n\n输出 JSON：\n{\n  \"review_feedback\": \"审查反馈\",\n  \"needs_improvement\": true/false,\n  \"improvement_areas\": [\"需要改进的方面\"]\n}"
      }
    },
    {
      "id": "check_needs_improvement",
      "type": "if-else",
      "data": {
        "conditions": [
          {
            "variable": "{{self_review.outputs.needs_improvement}}",
            "operator": "is",
            "value": true
          }
        ]
      }
    },
    {
      "id": "refine_analysis",
      "type": "llm",
      "data": {
        "title": "优化分析",
        "model": "deepseek-chat",
        "prompt": "基于审查反馈，优化分析结果。\n\n审查反馈：\n{{self_review.outputs.review_feedback}}\n\n原分析结果：\n{{stage3_suggestions.outputs}}\n\n输出优化后的 JSON：\n{\n  \"summary\": \"优化后的摘要\",\n  \"hypotheses\": [\"优化后的可能原因\"],\n  \"suggestions\": [\"优化后的修复建议\"]\n}"
      }
    },
    {
      "id": "improvement_loop",
      "type": "loop",
      "data": {
        "max_iterations": 2,
        "condition": "{{self_review.outputs.needs_improvement}} === true"
      }
    }
  ],
  "edges": [
    {"source": "start", "target": "stage1_quick_locate"},
    {"source": "stage1_quick_locate", "target": "check_needs_deep"},
    {"source": "check_needs_deep", "target": "stage2_deep_analysis", "condition": "true"},
    {"source": "check_needs_deep", "target": "final_output", "condition": "false"},
    {"source": "stage2_deep_analysis", "target": "stage3_suggestions"},
    {"source": "stage3_suggestions", "target": "self_review"},
    {"source": "self_review", "target": "check_needs_improvement"},
    {"source": "check_needs_improvement", "target": "refine_analysis", "condition": "true"},
    {"source": "check_needs_improvement", "target": "final_output", "condition": "false"},
    {"source": "refine_analysis", "target": "improvement_loop"},
    {"source": "improvement_loop", "target": "self_review", "condition": "continue"},
    {"source": "improvement_loop", "target": "final_output", "condition": "break"}
  ]
}
```

## 三、动态补充数据的实现

### 场景1：根据初步分析结果补充检索

**实现思路**：
1. LLM 分析错误日志，识别关键信息（类名、方法名、异常类型等）
2. LLM 判断是否需要更多代码证据
3. 如果需要，LLM 生成检索查询
4. 调用检索工具获取证据
5. 基于新证据继续分析

**Dify 工作流节点**：

```json
{
  "id": "dynamic_search",
  "type": "code",
  "data": {
    "title": "动态补充检索",
    "code": "// 从 LLM 分析结果中提取需要检索的关键词\nconst analysis = initial_analysis.outputs;\nconst searchQueries = [];\n\n// 提取类名和方法名\nconst classMatches = error_log.match(/class\\s+(\\w+)/gi);\nconst methodMatches = error_log.match(/(\\w+)\\s*\\(/g);\n\n// 提取异常类型\nconst exceptionMatches = error_log.match(/(\\w+Exception|\\w+Error)/g);\n\n// 构建检索查询\nif (classMatches) {\n  searchQueries.push(...classMatches.map(m => m.replace(/class\\s+/i, '')));\n}\nif (methodMatches) {\n  searchQueries.push(...methodMatches.map(m => m.replace(/\\s*\\(.*/, '')));\n}\nif (exceptionMatches) {\n  searchQueries.push(...exceptionMatches);\n}\n\n// 调用检索工具\nconst results = [];\nfor (const query of searchQueries.slice(0, 5)) { // 最多5个查询\n  const zoektResult = await fetch('http://localhost:8000/dify/tools/zoekt_search', {\n    method: 'POST',\n    headers: {'Content-Type': 'application/json'},\n    body: JSON.stringify({\n      query: query,\n      repo_path: repo.local_dir,\n      service_name: service_name\n    })\n  }).then(r => r.json());\n  \n  results.push({\n    query: query,\n    hits: zoektResult.result.hits\n  });\n}\n\nreturn { supplemental_results: results };"
  }
}
```

### 场景2：根据分析置信度决定是否继续

**实现思路**：
1. LLM 输出分析结果和置信度
2. 如果置信度 < 阈值，触发补充检索
3. 基于新证据重新分析
4. 重复直到置信度达标或达到最大轮数

**Dify 工作流节点**：

```json
{
  "id": "confidence_check",
  "type": "if-else",
  "data": {
    "title": "置信度检查",
    "conditions": [
      {
        "variable": "{{analysis.outputs.confidence}}",
        "comparison_operator": "less_than",
        "value": 0.8
      }
    ]
  }
},
{
  "id": "confidence_loop",
  "type": "loop",
  "data": {
    "title": "置信度提升循环",
    "max_iterations": 3,
    "condition": "{{analysis.outputs.confidence}} < 0.8 && iteration_count < 3"
  }
}
```

### 场景3：根据缺失信息类型调用不同工具

**实现思路**：
1. LLM 分析并识别缺失的信息类型
2. 根据信息类型选择相应的工具：
   - 需要代码位置 → Zoekt 检索
   - 需要语义理解 → 向量检索
   - 需要调用关系 → 调用链展开
   - 需要日志上下文 → Trace 链查询

**Dify 工作流节点**：

```json
{
  "id": "smart_tool_selection",
  "type": "code",
  "data": {
    "title": "智能工具选择",
    "code": "const missingInfo = analysis.outputs.missing_info;\nconst toolCalls = [];\n\nfor (const info of missingInfo) {\n  // 判断信息类型并选择工具\n  if (info.includes('方法') || info.includes('函数') || info.includes('调用')) {\n    // 需要调用关系，使用调用链展开\n    toolCalls.push({\n      tool: 'call_graph_expander',\n      query: info\n    });\n  } else if (info.includes('日志') || info.includes('trace') || info.includes('request')) {\n    // 需要日志上下文，使用 Trace 链查询\n    toolCalls.push({\n      tool: 'trace_chain_retriever',\n      query: info\n    });\n  } else if (info.match(/[A-Z]\\w+Exception|[A-Z]\\w+Error/)) {\n    // 异常类型，使用 Zoekt 精确检索\n    toolCalls.push({\n      tool: 'zoekt_search',\n      query: info\n    });\n  } else {\n    // 其他情况，使用向量检索\n    toolCalls.push({\n      tool: 'vector_search',\n      query: info\n    });\n  }\n}\n\n// 执行工具调用\nconst results = [];\nfor (const call of toolCalls) {\n  const result = await fetch(`http://localhost:8000/dify/tools/${call.tool}`, {\n    method: 'POST',\n    headers: {'Content-Type': 'application/json'},\n    body: JSON.stringify({\n      query: call.query,\n      repo_path: repo.local_dir,\n      service_name: service_name\n    })\n  }).then(r => r.json());\n  \n  results.push({\n    tool: call.tool,\n    query: call.query,\n    result: result.result\n  });\n}\n\nreturn { tool_results: results };"
  }
}
```

## 四、最佳实践方案

### 推荐：Agent 模式 + 条件循环

**优势**：
1. **智能化**：LLM 自主决定何时调用工具
2. **灵活性**：可以根据实际情况动态调整
3. **可控性**：设置最大迭代次数和停止条件

**实现步骤**：

1. **创建 Agent 工作流**
   ```python
   # 使用 Dify Python SDK
   from dify_client import DifyClient
   
   workflow = await client.workflows.create(
       name="智能错误分析 Agent",
       type="agent",
       model={
           "provider": "openai",
           "name": "deepseek-chat",
           "base_url": "https://api.deepseek.com"
       },
       tools=[
           "zoekt_search",
           "vector_search",
           "call_graph_expander",
           "trace_chain_retriever",
       ],
       max_iterations=5,
   )
   ```

2. **配置 Agent Prompt**
   ```
   你是一个资深的 SRE 工程师，负责分析错误日志。
   
   工作流程：
   1. 分析错误日志，识别关键信息（类名、方法名、异常类型等）
   2. 判断是否需要更多代码证据
   3. 如果需要，调用相应的工具获取证据：
      - zoekt_search: 精确查找代码位置
      - vector_search: 语义相似代码
      - call_graph_expander: 展开调用链
      - trace_chain_retriever: 查询日志链
   4. 基于证据进行深入分析
   5. 如果置信度不足（< 0.8），继续调用工具补充
   6. 直到有足够信息后，输出最终分析结果
   
   输出格式（JSON）：
   {
     "summary": "错误摘要",
     "hypotheses": ["可能原因1", "可能原因2"],
     "suggestions": ["修复建议1", "修复建议2"],
     "confidence": 0.0-1.0,
     "evidence_used": ["使用的证据来源"]
   }
   ```

3. **设置停止条件**
   ```json
   {
     "stop_conditions": [
       {
         "type": "confidence",
         "operator": ">=",
         "value": 0.8
       },
       {
         "type": "max_iterations",
         "value": 5
       }
     ]
   }
   ```

## 五、代码示例：完整的 Dify 多轮对话工作流

```python
# root_seeker/dify_workflows/multi_turn_analysis.py
from dify_client import DifyClient
from typing import Dict, Any

class MultiTurnAnalysisWorkflow:
    def __init__(self, dify_client: DifyClient):
        self.client = dify_client
        self.workflow_id = None
    
    async def create_workflow(self):
        """创建多轮对话分析工作流"""
        workflow_config = {
            "name": "多轮错误分析工作流",
            "type": "workflow",
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "data": {
                        "variables": [
                            {"variable": "error_log", "type": "string"},
                            {"variable": "service_name", "type": "string"},
                            {"variable": "initial_evidence", "type": "object"}
                        ]
                    }
                },
                {
                    "id": "initial_analysis",
                    "type": "llm",
                    "data": {
                        "model": "deepseek-chat",
                        "prompt": self._get_initial_prompt(),
                        "response_format": "json_object"
                    }
                },
                {
                    "id": "tool_selection",
                    "type": "code",
                    "data": {
                        "code": self._get_tool_selection_code()
                    }
                },
                {
                    "id": "supplemental_search",
                    "type": "parallel-tool-call",
                    "data": {
                        "tools": ["zoekt_search", "vector_search"],
                        "parallel": True
                    }
                },
                {
                    "id": "refined_analysis",
                    "type": "llm",
                    "data": {
                        "model": "deepseek-chat",
                        "prompt": self._get_refined_prompt(),
                        "response_format": "json_object"
                    }
                },
                {
                    "id": "confidence_check",
                    "type": "if-else",
                    "data": {
                        "conditions": [
                            {
                                "variable": "{{refined_analysis.outputs.confidence}}",
                                "operator": "<",
                                "value": 0.8
                            }
                        ]
                    }
                },
                {
                    "id": "iteration_loop",
                    "type": "loop",
                    "data": {
                        "max_iterations": 3,
                        "condition": "{{refined_analysis.outputs.confidence}} < 0.8"
                    }
                }
            ],
            "edges": [
                {"source": "start", "target": "initial_analysis"},
                {"source": "initial_analysis", "target": "tool_selection"},
                {"source": "tool_selection", "target": "supplemental_search"},
                {"source": "supplemental_search", "target": "refined_analysis"},
                {"source": "refined_analysis", "target": "confidence_check"},
                {"source": "confidence_check", "target": "tool_selection", "condition": "true"},
                {"source": "confidence_check", "target": "end", "condition": "false"},
                {"source": "iteration_loop", "target": "tool_selection", "condition": "continue"},
                {"source": "iteration_loop", "target": "end", "condition": "break"}
            ]
        }
        
        workflow = await self.client.workflows.create(**workflow_config)
        self.workflow_id = workflow.id
        return workflow
    
    def _get_initial_prompt(self) -> str:
        return """分析错误日志，识别关键信息。

错误日志：
{{error_log}}

初始证据：
{{initial_evidence}}

请输出 JSON：
{
  "key_info": {
    "class_names": ["类名1", "类名2"],
    "method_names": ["方法名1", "方法名2"],
    "exception_types": ["异常类型1"]
  },
  "needs_more_data": true/false,
  "missing_info": ["需要的信息1", "需要的信息2"],
  "confidence": 0.0-1.0
}"""
    
    def _get_tool_selection_code(self) -> str:
        return """
const analysis = initial_analysis.outputs;
const toolCalls = [];

// 根据缺失信息选择工具
for (const info of analysis.missing_info || []) {
  if (info.includes('调用') || info.includes('方法')) {
    toolCalls.push({tool: 'call_graph_expander', query: info});
  } else if (info.includes('日志') || info.includes('trace')) {
    toolCalls.push({tool: 'trace_chain_retriever', query: info});
  } else if (info.match(/Exception|Error/)) {
    toolCalls.push({tool: 'zoekt_search', query: info});
  } else {
    toolCalls.push({tool: 'vector_search', query: info});
  }
}

return { tool_calls: toolCalls };
"""
    
    def _get_refined_prompt(self) -> str:
        return """基于初步分析和补充证据，进行深入分析。

初步分析：
{{initial_analysis.outputs}}

补充证据：
{{supplemental_search.outputs}}

请输出 JSON：
{
  "summary": "最终摘要",
  "hypotheses": ["可能原因1", "可能原因2"],
  "suggestions": ["修复建议1", "修复建议2"],
  "confidence": 0.0-1.0,
  "needs_more_data": false
}"""
    
    async def run(self, error_log: str, service_name: str, initial_evidence: Dict) -> Dict:
        """执行多轮分析"""
        result = await self.client.workflows.run(
            workflow_id=self.workflow_id,
            inputs={
                "error_log": error_log,
                "service_name": service_name,
                "initial_evidence": initial_evidence,
            },
            user="system",
        )
        return result.outputs
```

## 六、总结

### Dify 实现多轮补充数据的三种方案

1. **循环 + 条件节点**（方案A）
   - ✅ 完全可控
   - ✅ 易于调试
   - ⚠️ 需要手动配置每个步骤

2. **Agent 模式**（方案B，推荐）
   - ✅ LLM 自主决策
   - ✅ 最灵活
   - ✅ 最接近当前系统的智能程度

3. **混合模式**（方案C）
   - ✅ 结合分阶段和自我优化
   - ✅ 适合复杂场景
   - ⚠️ 配置较复杂

### 推荐方案：Agent 模式

**理由**：
1. LLM 可以自主决定何时调用工具
2. 根据分析结果动态补充数据
3. 设置停止条件（置信度、最大迭代次数）
4. 最接近当前系统的多轮对话能力

**实施建议**：
1. 先实现 Agent 模式的基础版本
2. 测试工具调用的准确性
3. 优化 Agent Prompt 和停止条件
4. 逐步添加更多工具和功能

---

详细方案已保存在 `docs/DIFY_MULTI_TURN_LLM.md`，包含完整的代码示例和工作流配置。
