# LangChain/LangGraph + Flowise 迁移方案

## 一、可行性分析

### ✅ 优势

1. **工作流可视化**
   - Flowise 提供拖拽式界面，非技术人员也能理解和调整分析流程
   - 便于团队协作和知识传承

2. **标准化组件**
   - LangChain 提供大量预构建组件（Retrievers, Chains, Agents）
   - 减少重复代码，提高可维护性

3. **状态管理**
   - LangGraph 天然支持多步骤、有状态的工作流
   - 完美匹配当前的多轮对话需求（staged/self_refine/hybrid）

4. **生态集成**
   - 丰富的集成（向量数据库、LLM提供商、工具等）
   - 社区支持好，文档完善

5. **可扩展性**
   - 易于添加新的工具和步骤
   - 支持条件分支和循环，适合复杂的分析流程

### ⚠️ 挑战

1. **自定义逻辑**
   - 当前系统有大量自定义逻辑（调用链展开、证据构建、跨仓库检索）
   - 需要封装为 LangChain 兼容的组件

2. **性能考虑**
   - LangChain 可能增加一些抽象层开销
   - 需要评估对现有性能的影响

3. **学习曲线**
   - 团队需要学习 LangChain/LangGraph 概念
   - Flowise 的使用需要培训

4. **迁移成本**
   - 需要重构大量现有代码
   - 需要充分测试确保功能一致性

## 二、架构对比

### 当前架构

```
Webhook → JobQueue → AnalyzerService
  ↓
LogEnricher (日志补全)
  ↓
ServiceRouter (路由到仓库)
  ↓
EvidenceBuilder (构建证据包)
  ├─ ZoektClient (词法检索)
  ├─ VectorRetriever (向量检索)
  └─ CallGraphExpander (调用链展开)
  ↓
LLMProvider (多轮对话)
  ├─ staged (分阶段)
  ├─ self_refine (自我优化)
  └─ hybrid (混合模式)
  ↓
Notifiers (通知)
```

### LangGraph 架构（建议）

```
Webhook → FastAPI Endpoint
  ↓
LangGraph Workflow
  ├─ Node: NormalizeEvent (事件归一化)
  ├─ Node: EnrichLogs (日志补全)
  ├─ Node: RouteToRepo (路由到仓库)
  ├─ Node: BuildEvidence (构建证据)
  │   ├─ Tool: ZoektSearch
  │   ├─ Tool: VectorSearch
  │   └─ Tool: ExpandCallGraph
  ├─ Node: AnalyzeWithLLM (LLM分析)
  │   └─ Conditional: MultiTurnDecision
  │       ├─ Branch: StagedMode
  │       ├─ Branch: SelfRefineMode
  │       └─ Branch: HybridMode
  └─ Node: Notify (通知)
```

## 三、迁移策略

### 阶段1：混合模式（推荐）

**目标**：保留现有核心逻辑，逐步引入 LangChain

1. **保留现有组件**
   - 保持 `ZoektClient`, `VectorRetriever`, `CallGraphExpander` 等核心组件
   - 将它们封装为 LangChain Tools

2. **引入 LangGraph 工作流**
   - 使用 LangGraph 管理多轮对话流程
   - 保留现有的单轮对话逻辑作为 fallback

3. **逐步迁移**
   - 先迁移多轮对话部分
   - 再迁移证据构建部分
   - 最后迁移整个流程

### 阶段2：完整迁移

**目标**：完全使用 LangChain/LangGraph 重构

1. **自定义 Tools**
   ```python
   from langchain.tools import BaseTool
   
   class ZoektSearchTool(BaseTool):
       name = "zoekt_search"
       description = "Search code using Zoekt lexical search"
       
       def _run(self, query: str, repo_path: str) -> str:
           # 调用现有的 ZoektClient
           pass
   ```

2. **自定义 Retrievers**
   ```python
   from langchain.retrievers import BaseRetriever
   
   class HybridCodeRetriever(BaseRetriever):
       def __init__(self, zoekt_client, vector_retriever):
           self.zoekt = zoekt_client
           self.vector = vector_retriever
       
       def _get_relevant_documents(self, query: str):
           # 混合检索逻辑
           pass
   ```

3. **LangGraph 工作流**
   ```python
   from langgraph.graph import StateGraph, END
   
   def create_analysis_graph():
       workflow = StateGraph(AnalysisState)
       
       # 添加节点
       workflow.add_node("normalize", normalize_event)
       workflow.add_node("enrich", enrich_logs)
       workflow.add_node("route", route_to_repo)
       workflow.add_node("build_evidence", build_evidence)
       workflow.add_node("analyze", analyze_with_llm)
       workflow.add_node("notify", send_notification)
       
       # 添加边
       workflow.set_entry_point("normalize")
       workflow.add_edge("normalize", "enrich")
       workflow.add_edge("enrich", "route")
       workflow.add_edge("route", "build_evidence")
       workflow.add_edge("build_evidence", "analyze")
       workflow.add_edge("analyze", "notify")
       workflow.add_edge("notify", END)
       
       return workflow.compile()
   ```

## 四、具体实现方案

### 1. 自定义 Tools 封装

```python
# root_seeker/langchain_tools/zoekt_tool.py
from langchain.tools import BaseTool
from typing import Optional
from pydantic import BaseModel, Field

class ZoektSearchInput(BaseModel):
    query: str = Field(description="Search query")
    repo_path: str = Field(description="Repository local path")
    service_name: str = Field(description="Service name")

class ZoektSearchTool(BaseTool):
    name = "zoekt_search"
    description = "Search code using Zoekt lexical search engine"
    args_schema = ZoektSearchInput
    
    def __init__(self, zoekt_client):
        super().__init__()
        self.zoekt = zoekt_client
    
    def _run(self, query: str, repo_path: str, service_name: str) -> str:
        """Execute Zoekt search"""
        hits = await self.zoekt.search(query=query)
        # 过滤和格式化结果
        return format_hits(hits)
    
    async def _arun(self, query: str, repo_path: str, service_name: str) -> str:
        """Async execute Zoekt search"""
        return await self._run(query, repo_path, service_name)
```

### 2. LangGraph State 定义

```python
# root_seeker/langgraph/state.py
from typing import TypedDict, List, Optional
from langgraph.graph.message import add_messages

class AnalysisState(TypedDict):
    # 输入
    event: NormalizedErrorEvent
    analysis_id: str
    
    # 中间状态
    log_bundle: Optional[LogBundle]
    repo: Optional[CandidateRepo]
    evidence: Optional[EvidencePack]
    
    # LLM 相关
    llm_messages: List[dict]
    current_round: int
    analysis_mode: str  # staged | self_refine | hybrid
    
    # 输出
    report: Optional[AnalysisReport]
    error: Optional[str]
```

### 3. LangGraph 节点实现

```python
# root_seeker/langgraph/nodes.py
from langgraph.graph import StateGraph

async def enrich_logs_node(state: AnalysisState) -> AnalysisState:
    """日志补全节点"""
    enricher = state.get("enricher")
    event = state["event"]
    
    log_bundle = await enricher.enrich(event)
    return {"log_bundle": log_bundle}

async def build_evidence_node(state: AnalysisState) -> AnalysisState:
    """构建证据包节点"""
    evidence_builder = state.get("evidence_builder")
    event = state["event"]
    repo = state["repo"]
    log_bundle = state["log_bundle"]
    
    # 使用 LangChain Tools
    tools = [
        ZoektSearchTool(zoekt_client),
        VectorSearchTool(vector_retriever),
        CallGraphExpandTool(call_graph_expander),
    ]
    
    evidence = await evidence_builder.build(
        event=event,
        repo=repo,
        log_bundle=log_bundle,
        tools=tools,
    )
    
    return {"evidence": evidence}

async def analyze_node(state: AnalysisState) -> AnalysisState:
    """LLM 分析节点"""
    llm = state.get("llm")
    mode = state.get("analysis_mode", "hybrid")
    
    if mode == "staged":
        return await staged_analysis(state)
    elif mode == "self_refine":
        return await self_refine_analysis(state)
    else:  # hybrid
        return await hybrid_analysis(state)
```

### 4. Flowise 集成

```python
# root_seeker/flowise/integration.py
from langchain.agents import AgentExecutor
from langchain.agents.openai_functions_agent.base import create_openai_functions_agent
from langchain_openai import ChatOpenAI

def create_flowise_agent():
    """创建 Flowise 兼容的 Agent"""
    llm = ChatOpenAI(
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        temperature=0.7,
    )
    
    tools = [
        ZoektSearchTool(zoekt_client),
        VectorSearchTool(vector_retriever),
        CallGraphExpandTool(call_graph_expander),
    ]
    
    agent = create_openai_functions_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)
```

## 五、迁移步骤建议

### 第一步：准备阶段（1-2周）

1. **安装依赖**
   ```bash
   pip install langchain langchain-openai langgraph flowise
   ```

2. **创建新模块**
   ```
   root_seeker/
   ├── langchain_tools/     # 自定义 Tools
   ├── langgraph/           # LangGraph 工作流
   └── flowise/             # Flowise 集成
   ```

3. **封装现有组件为 Tools**
   - ZoektSearchTool
   - VectorSearchTool
   - CallGraphExpandTool
   - LogEnrichTool

### 第二步：试点迁移（2-3周）

1. **创建 LangGraph 版本的分析流程**
   - 先实现单轮对话版本
   - 测试功能一致性

2. **并行运行**
   - 保留现有系统
   - 新系统作为可选路径
   - 通过配置切换

### 第三步：完整迁移（3-4周）

1. **迁移多轮对话**
   - 使用 LangGraph 的条件分支实现
   - 测试三种模式（staged/self_refine/hybrid）

2. **Flowise 可视化**
   - 导入工作流到 Flowise
   - 配置可视化界面
   - 团队培训

### 第四步：优化和清理（1-2周）

1. **性能优化**
   - 减少抽象层开销
   - 优化状态管理

2. **文档更新**
   - 更新架构文档
   - Flowise 使用指南

3. **移除旧代码**
   - 确认新系统稳定后
   - 逐步移除旧实现

## 六、代码示例：完整 LangGraph 工作流

```python
# root_seeker/langgraph/workflow.py
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing import Literal

def create_analysis_workflow():
    """创建完整的分析工作流"""
    
    workflow = StateGraph(AnalysisState)
    
    # 添加节点
    workflow.add_node("normalize", normalize_event_node)
    workflow.add_node("enrich", enrich_logs_node)
    workflow.add_node("route", route_to_repo_node)
    workflow.add_node("build_evidence", build_evidence_node)
    workflow.add_node("analyze_staged", staged_analysis_node)
    workflow.add_node("analyze_refine", self_refine_analysis_node)
    workflow.add_node("analyze_hybrid", hybrid_analysis_node)
    workflow.add_node("notify", notify_node)
    
    # 设置入口
    workflow.set_entry_point("normalize")
    
    # 添加边
    workflow.add_edge("normalize", "enrich")
    workflow.add_edge("enrich", "route")
    workflow.add_edge("route", "build_evidence")
    
    # 条件分支：根据模式选择分析路径
    def route_analysis(state: AnalysisState) -> Literal["analyze_staged", "analyze_refine", "analyze_hybrid"]:
        mode = state.get("analysis_mode", "hybrid")
        if mode == "staged":
            return "analyze_staged"
        elif mode == "self_refine":
            return "analyze_refine"
        else:
            return "analyze_hybrid"
    
    workflow.add_conditional_edges(
        "build_evidence",
        route_analysis,
        {
            "analyze_staged": "analyze_staged",
            "analyze_refine": "analyze_refine",
            "analyze_hybrid": "analyze_hybrid",
        }
    )
    
    # 所有分析路径都指向通知
    workflow.add_edge("analyze_staged", "notify")
    workflow.add_edge("analyze_refine", "notify")
    workflow.add_edge("analyze_hybrid", "notify")
    workflow.add_edge("notify", END)
    
    # 添加检查点（支持状态持久化）
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)
```

## 七、Flowise 配置

### 1. 导出工作流配置

```json
{
  "nodes": [
    {
      "id": "normalize",
      "type": "custom",
      "data": {
        "name": "NormalizeEvent",
        "description": "Normalize error event"
      }
    },
    {
      "id": "enrich",
      "type": "custom",
      "data": {
        "name": "EnrichLogs",
        "description": "Enrich logs from SLS"
      }
    },
    {
      "id": "build_evidence",
      "type": "custom",
      "data": {
        "name": "BuildEvidence",
        "description": "Build evidence package",
        "tools": ["ZoektSearch", "VectorSearch", "CallGraphExpand"]
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "data": {
        "model": "deepseek-chat",
        "temperature": 0.7
      }
    }
  ],
  "edges": [
    {"from": "normalize", "to": "enrich"},
    {"from": "enrich", "to": "build_evidence"},
    {"from": "build_evidence", "to": "analyze"}
  ]
}
```

### 2. Flowise 部署

```bash
# 使用 Docker 部署 Flowise
docker run -d \
  --name flowise \
  -p 3000:3000 \
  -v flowise_data:/root/.flowise \
  flowiseai/flowise
```

## 八、优势总结

### 使用 LangChain/LangGraph + Flowise 后：

1. **可视化工作流**
   - 非技术人员也能理解和调整流程
   - 便于团队协作

2. **标准化**
   - 使用业界标准框架
   - 易于招聘和培训

3. **可扩展性**
   - 易于添加新工具和步骤
   - 社区支持好

4. **状态管理**
   - LangGraph 天然支持复杂状态
   - 便于调试和监控

5. **工具生态**
   - 丰富的预构建工具
   - 易于集成第三方服务

## 九、建议

### 推荐方案：渐进式迁移

1. **第一阶段**：保持现有系统，添加 LangGraph 作为可选路径
2. **第二阶段**：逐步迁移核心功能到 LangGraph
3. **第三阶段**：完全迁移，使用 Flowise 可视化

### 不推荐：完全重写

- 风险太高
- 现有系统已经稳定运行
- 渐进式迁移更安全

## 十、下一步行动

1. **评估**：团队讨论是否采用此方案
2. **试点**：选择一个简单场景先试点
3. **培训**：团队学习 LangChain/LangGraph
4. **迁移**：按阶段逐步迁移

---

**结论**：使用 LangChain/LangGraph + Flowise 是可行的，建议采用渐进式迁移策略，既能享受新框架的优势，又能保证系统稳定性。

---

## 十一、Dify 替代方案

**注意**：如果考虑使用 Dify.ai 替代 Flowise，请参考 [DIFY_MIGRATION_PLAN.md](./DIFY_MIGRATION_PLAN.md)。

**Dify 的优势**：
- ✅ 原生中文支持
- ✅ 内置 RAG 功能
- ✅ 企业级功能更完善
- ✅ 更适合中文团队

**对比**：
- **Dify**：更适合需要中文支持和内置 RAG 的场景
- **Flowise**：更适合需要轻量级和 LangChain 深度集成的场景
