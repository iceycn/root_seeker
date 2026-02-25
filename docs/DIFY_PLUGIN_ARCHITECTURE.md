# Dify 插件化架构方案

## 一、插件化思路

将现有系统拆解为多个独立的 Dify 插件，每个插件负责一个特定功能，通过 Dify 工作流串联起来。

### 优势

1. **最大化代码复用**
   - 保留现有核心逻辑
   - 只需封装为 Dify 兼容的插件
   - 减少重写成本

2. **模块化设计**
   - 每个插件独立开发和测试
   - 易于维护和扩展
   - 可以单独升级

3. **灵活组合**
   - 通过 Dify 工作流灵活组合插件
   - 不同场景使用不同插件组合
   - 易于 A/B 测试

4. **渐进式迁移**
   - 可以逐个插件迁移
   - 不影响现有系统运行
   - 降低风险

## 二、插件拆分方案

### 插件清单

| 插件名称 | 功能 | 对应现有组件 | 类型 |
|---------|------|------------|------|
| **zoekt-search-tool** | Zoekt 词法检索 | `ZoektClient` | Tool |
| **vector-search-tool** | 向量检索 | `VectorRetriever` | Tool |
| **call-graph-expander-tool** | 调用链展开 | `CallGraphExpander` | Tool |
| **log-enricher-node** | 日志补全 | `LogEnricher` | Node |
| **service-router-node** | 服务路由 | `ServiceRouter` | Node |
| **evidence-builder-node** | 证据构建 | `EvidenceBuilder` | Node |
| **trace-chain-retriever-tool** | Trace 链查询 | `TraceChainProvider` | Tool |
| **repo-sync-tool** | 仓库同步 | `RepoMirror` | Tool |
| **vector-indexer-tool** | 向量索引 | `VectorIndexer` | Tool |
| **notifier-node** | 通知发送 | `Notifiers` | Node |

## 三、插件详细设计

### 1. Zoekt Search Tool

**功能**：使用 Zoekt 进行代码词法检索

**输入参数**：
```json
{
  "query": "string - 搜索查询",
  "repo_path": "string - 仓库本地路径",
  "service_name": "string - 服务名",
  "max_results": "number - 最大结果数（默认10）"
}
```

**输出**：
```json
{
  "hits": [
    {
      "file_path": "string",
      "line_number": "number",
      "content": "string",
      "score": "number"
    }
  ],
  "total": "number"
}
```

**实现**：
```python
# root_seeker/dify_plugins/tools/zoekt_search.py
from typing import Dict, Any, List
from dify_client import Tool
from root_seeker.providers.zoekt import ZoektClient

class ZoektSearchTool(Tool):
    name = "zoekt_search"
    description = "使用 Zoekt 进行代码词法检索，支持正则表达式和符号搜索"
    
    def __init__(self, zoekt_client: ZoektClient):
        self.zoekt = zoekt_client
    
    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        query = parameters.get("query")
        repo_path = parameters.get("repo_path")
        service_name = parameters.get("service_name")
        max_results = parameters.get("max_results", 10)
        
        # 构建 Zoekt 查询
        zoekt_query = self._build_query(query, service_name)
        
        # 执行搜索
        hits = await self.zoekt.search(query=zoekt_query)
        
        # 过滤和格式化结果
        filtered_hits = self._filter_hits(hits, repo_path)
        
        return {
            "hits": [
                {
                    "file_path": hit.file_path,
                    "line_number": hit.line_number,
                    "content": hit.content[:500],  # 限制长度
                    "score": hit.score if hasattr(hit, 'score') else 1.0,
                }
                for hit in filtered_hits[:max_results]
            ],
            "total": len(filtered_hits),
        }
    
    def _build_query(self, query: str, service_name: str) -> str:
        """构建 Zoekt 查询字符串"""
        # 添加 repo 过滤
        return f'repo:{service_name} {query}'
    
    def _filter_hits(self, hits: List, repo_path: str) -> List:
        """过滤命中结果"""
        # 只返回指定仓库的结果
        return [h for h in hits if repo_path in h.file_path]
```

### 2. Vector Search Tool

**功能**：使用向量检索查找相似代码片段

**输入参数**：
```json
{
  "query": "string - 查询文本",
  "service_name": "string - 服务名",
  "repo_path": "string - 仓库路径",
  "top_k": "number - 返回数量（默认12）"
}
```

**输出**：
```json
{
  "chunks": [
    {
      "file_path": "string",
      "start_line": "number",
      "end_line": "number",
      "content": "string",
      "score": "number"
    }
  ]
}
```

**实现**：
```python
# root_seeker/dify_plugins/tools/vector_search.py
from typing import Dict, Any
from dify_client import Tool
from root_seeker.services.vector_retriever import VectorRetriever

class VectorSearchTool(Tool):
    name = "vector_search"
    description = "使用向量检索查找语义相似的代码片段"
    
    def __init__(self, vector_retriever: VectorRetriever):
        self.vector = vector_retriever
    
    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        query = parameters.get("query")
        service_name = parameters.get("service_name")
        repo_path = parameters.get("repo_path")
        top_k = parameters.get("top_k", 12)
        
        # 执行向量检索
        hits = await self.vector.search(
            query=query[:2000],  # 限制查询长度
            service_name=service_name,
            repo_local_dir=repo_path,
        )
        
        return {
            "chunks": [
                {
                    "file_path": hit.get("payload", {}).get("file_path", ""),
                    "start_line": hit.get("payload", {}).get("start_line", 0),
                    "end_line": hit.get("payload", {}).get("end_line", 0),
                    "content": hit.get("payload", {}).get("text", ""),
                    "score": hit.get("score", 0.0),
                }
                for hit in hits[:top_k]
            ]
        }
```

### 3. Call Graph Expander Tool

**功能**：展开调用链，查找关联方法

**输入参数**：
```json
{
  "method_name": "string - 方法名",
  "file_path": "string - 文件路径",
  "repo_path": "string - 仓库路径",
  "max_rounds": "number - 最大轮数（默认2）",
  "max_methods": "number - 最大方法数（默认15）"
}
```

**输出**：
```json
{
  "methods": [
    {
      "name": "string",
      "file_path": "string",
      "start_line": "number",
      "end_line": "number",
      "content": "string",
      "round": "number"
    }
  ],
  "total_rounds": "number"
}
```

**实现**：
```python
# root_seeker/dify_plugins/tools/call_graph_expander.py
from typing import Dict, Any
from dify_client import Tool
from root_seeker.services.call_graph_expander import CallGraphExpander

class CallGraphExpanderTool(Tool):
    name = "call_graph_expander"
    description = "展开方法调用链，查找调用方和被调用方"
    
    def __init__(self, call_graph_expander: CallGraphExpander):
        self.expander = call_graph_expander
    
    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        method_name = parameters.get("method_name")
        file_path = parameters.get("file_path")
        repo_path = parameters.get("repo_path")
        max_rounds = parameters.get("max_rounds", 2)
        max_methods = parameters.get("max_methods", 15)
        
        # 构建初始证据
        initial_evidence = EvidencePack(
            files=[
                EvidenceFile(
                    file_path=file_path,
                    source="initial",
                    content="",  # 可以从文件读取
                )
            ]
        )
        
        # 展开调用链
        expanded_evidence = await self.expander.expand_evidence(
            evidence=initial_evidence,
            repo_local_dir=repo_path,
            max_rounds=max_rounds,
            max_total_methods=max_methods,
        )
        
        return {
            "methods": [
                {
                    "name": f.get("symbol", ""),
                    "file_path": f.file_path,
                    "start_line": f.start_line,
                    "end_line": f.end_line,
                    "content": f.content[:500],
                    "round": f.metadata.get("round", 0) if hasattr(f, 'metadata') else 0,
                }
                for f in expanded_evidence.files
            ],
            "total_rounds": max_rounds,
        }
```

### 4. Log Enricher Node

**功能**：从 SLS 补全日志上下文

**输入**：
```json
{
  "service_name": "string",
  "error_log": "string",
  "query_key": "string",
  "timestamp": "string (ISO format)"
}
```

**输出**：
```json
{
  "log_bundle": {
    "records": [
      {
        "message": "string",
        "timestamp": "string",
        "level": "string"
      }
    ],
    "total": "number"
  },
  "trace_id": "string | null",
  "request_id": "string | null"
}
```

**实现**：
```python
# root_seeker/dify_plugins/nodes/log_enricher.py
from typing import Dict, Any
from dify_client import Node
from root_seeker.services.enricher import LogEnricher
from root_seeker.domain import NormalizedErrorEvent

class LogEnricherNode(Node):
    name = "log_enricher"
    description = "从 SLS 补全错误日志的上下文"
    
    def __init__(self, log_enricher: LogEnricher):
        self.enricher = log_enricher
    
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        # 构建事件
        event = NormalizedErrorEvent(
            service_name=inputs.get("service_name"),
            error_log=inputs.get("error_log"),
            query_key=inputs.get("query_key", "default_error_context"),
            timestamp=inputs.get("timestamp"),
        )
        
        # 补全日志
        log_bundle = await self.enricher.enrich(event)
        
        # 提取 trace_id/request_id
        trace_id, request_id = await self.enricher._extract_trace_ids(event)
        
        return {
            "log_bundle": {
                "records": [
                    {
                        "message": r.message,
                        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                        "level": r.level if hasattr(r, 'level') else "INFO",
                    }
                    for r in log_bundle.records[:200]  # 限制数量
                ],
                "total": len(log_bundle.records),
            },
            "trace_id": trace_id,
            "request_id": request_id,
        }
```

### 5. Service Router Node

**功能**：根据服务名路由到仓库

**输入**：
```json
{
  "service_name": "string"
}
```

**输出**：
```json
{
  "repo": {
    "service_name": "string",
    "local_dir": "string",
    "git_url": "string",
    "confidence": "number"
  },
  "alternatives": [
    {
      "service_name": "string",
      "local_dir": "string",
      "confidence": "number"
    }
  ]
}
```

**实现**：
```python
# root_seeker/dify_plugins/nodes/service_router.py
from typing import Dict, Any
from dify_client import Node
from root_seeker.services.router import ServiceRouter

class ServiceRouterNode(Node):
    name = "service_router"
    description = "根据服务名路由到对应的代码仓库"
    
    def __init__(self, router: ServiceRouter):
        self.router = router
    
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        service_name = inputs.get("service_name")
        
        # 路由到仓库
        candidates = self.router.route(service_name)
        
        if not candidates:
            return {
                "repo": None,
                "alternatives": [],
                "error": f"未找到服务 {service_name} 对应的仓库",
            }
        
        # 返回最佳匹配和备选
        best = candidates[0]
        return {
            "repo": {
                "service_name": best.service_name,
                "local_dir": best.local_dir,
                "git_url": best.git_url,
                "confidence": best.confidence,
            },
            "alternatives": [
                {
                    "service_name": c.service_name,
                    "local_dir": c.local_dir,
                    "confidence": c.confidence,
                }
                for c in candidates[1:3]  # 最多返回2个备选
            ],
        }
```

### 6. Evidence Builder Node

**功能**：构建证据包，整合多种检索结果

**输入**：
```json
{
  "error_log": "string",
  "repo": {
    "service_name": "string",
    "local_dir": "string"
  },
  "zoekt_hits": "array (from zoekt_search tool)",
  "vector_hits": "array (from vector_search tool)",
  "call_graph_methods": "array (from call_graph_expander tool)",
  "log_bundle": "object (from log_enricher node)"
}
```

**输出**：
```json
{
  "evidence": {
    "files": [
      {
        "file_path": "string",
        "start_line": "number",
        "end_line": "number",
        "content": "string",
        "source": "string"
      }
    ],
    "summary": {
      "total_files": "number",
      "total_chars": "number",
      "sources": {
        "zoekt": "number",
        "vector": "number",
        "call_graph": "number"
      }
    }
  }
}
```

**实现**：
```python
# root_seeker/dify_plugins/nodes/evidence_builder.py
from typing import Dict, Any
from dify_client import Node
from root_seeker.services.evidence import EvidenceBuilder

class EvidenceBuilderNode(Node):
    name = "evidence_builder"
    description = "整合多种检索结果，构建证据包"
    
    def __init__(self, evidence_builder: EvidenceBuilder):
        self.builder = evidence_builder
    
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        error_log = inputs.get("error_log")
        repo = inputs.get("repo")
        zoekt_hits = inputs.get("zoekt_hits", [])
        vector_hits = inputs.get("vector_hits", [])
        call_graph_methods = inputs.get("call_graph_methods", [])
        
        # 转换为内部格式
        zoekt_hits_internal = self._convert_zoekt_hits(zoekt_hits)
        vector_hits_internal = self._convert_vector_hits(vector_hits)
        
        # 构建证据包
        evidence = self.builder.build_from_zoekt_hits(
            repo_local_dir=repo["local_dir"],
            hits=zoekt_hits_internal,
            level="L3",
        )
        
        # 添加向量检索结果
        if vector_hits_internal:
            self.builder.append_vector_hits(
                evidence=evidence,
                repo_local_dir=repo["local_dir"],
                vector_hits=vector_hits_internal,
            )
        
        # 添加调用链方法
        if call_graph_methods:
            self._add_call_graph_methods(evidence, call_graph_methods)
        
        return {
            "evidence": {
                "files": [
                    {
                        "file_path": f.file_path,
                        "start_line": f.start_line,
                        "end_line": f.end_line,
                        "content": f.content,
                        "source": f.source,
                    }
                    for f in evidence.files
                ],
                "summary": {
                    "total_files": len(evidence.files),
                    "total_chars": sum(len(f.content) for f in evidence.files),
                    "sources": self._count_sources(evidence.files),
                },
            }
        }
    
    def _convert_zoekt_hits(self, hits: list) -> list:
        """转换 Zoekt 命中结果为内部格式"""
        from root_seeker.domain import ZoektHit
        return [
            ZoektHit(
                file_path=h["file_path"],
                line_number=h.get("line_number"),
                content=h.get("content", ""),
            )
            for h in hits
        ]
    
    def _convert_vector_hits(self, hits: list) -> list:
        """转换向量检索结果为内部格式"""
        return hits  # 已经是字典格式
    
    def _add_call_graph_methods(self, evidence, methods: list):
        """添加调用链方法到证据包"""
        from root_seeker.domain import EvidenceFile
        for method in methods:
            evidence.files.append(
                EvidenceFile(
                    file_path=method["file_path"],
                    start_line=method["start_line"],
                    end_line=method["end_line"],
                    content=method["content"],
                    source="call_graph",
                )
            )
    
    def _count_sources(self, files: list) -> dict:
        """统计来源分布"""
        sources = {}
        for f in files:
            sources[f.source] = sources.get(f.source, 0) + 1
        return sources
```

### 7. Trace Chain Retriever Tool

**功能**：通过 trace_id 查询调用链日志

**输入参数**：
```json
{
  "trace_id": "string",
  "request_id": "string | null",
  "service_name": "string",
  "time_window_seconds": "number (默认300)"
}
```

**输出**：
```json
{
  "logs": [
    {
      "message": "string",
      "timestamp": "string",
      "service": "string"
    }
  ],
  "total": "number"
}
```

**实现**：
```python
# root_seeker/dify_plugins/tools/trace_chain_retriever.py
from typing import Dict, Any
from dify_client import Tool
from root_seeker.providers.trace_chain import TraceChainProvider

class TraceChainRetrieverTool(Tool):
    name = "trace_chain_retriever"
    description = "通过 trace_id/request_id 查询完整的调用链日志"
    
    def __init__(self, trace_chain_provider: TraceChainProvider):
        self.provider = trace_chain_provider
    
    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        trace_id = parameters.get("trace_id")
        request_id = parameters.get("request_id")
        service_name = parameters.get("service_name")
        time_window = parameters.get("time_window_seconds", 300)
        
        # 查询调用链
        logs = await self.provider.query_trace_chain(
            trace_id=trace_id,
            request_id=request_id,
            service_name=service_name,
            time_window_seconds=time_window,
        )
        
        return {
            "logs": [
                {
                    "message": log.message,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                    "service": log.service if hasattr(log, 'service') else service_name,
                }
                for log in logs[:500]  # 限制数量
            ],
            "total": len(logs),
        }
```

### 8. Notifier Node

**功能**：发送分析结果通知

**输入**：
```json
{
  "report": {
    "analysis_id": "string",
    "service_name": "string",
    "summary": "string",
    "hypotheses": ["string"],
    "suggestions": ["string"]
  },
  "channels": ["wecom", "dingtalk"]  // 可选，默认使用配置
}
```

**输出**：
```json
{
  "sent": ["wecom", "dingtalk"],
  "failed": [],
  "total": 2
}
```

**实现**：
```python
# root_seeker/dify_plugins/nodes/notifier.py
from typing import Dict, Any, List
from dify_client import Node
from root_seeker.providers.notifiers import Notifier
from root_seeker.domain import AnalysisReport

class NotifierNode(Node):
    name = "notifier"
    description = "发送分析结果通知到企业微信/钉钉等渠道"
    
    def __init__(self, notifiers: List[Notifier]):
        self.notifiers = notifiers
    
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        report_dict = inputs.get("report")
        channels = inputs.get("channels", [])
        
        # 转换为 AnalysisReport 对象
        report = AnalysisReport.model_validate(report_dict)
        
        # 发送通知
        sent = []
        failed = []
        
        for notifier in self.notifiers:
            # 如果指定了渠道，只发送到指定渠道
            if channels and not self._should_send(notifier, channels):
                continue
            
            try:
                markdown = self._to_markdown(report)
                await notifier.send_markdown(
                    title=f"错误分析：{report.service_name}",
                    markdown=markdown,
                )
                sent.append(self._get_channel_name(notifier))
            except Exception as e:
                failed.append({
                    "channel": self._get_channel_name(notifier),
                    "error": str(e),
                })
        
        return {
            "sent": sent,
            "failed": failed,
            "total": len(sent),
        }
    
    def _should_send(self, notifier, channels: List[str]) -> bool:
        """判断是否应该发送到该通知器"""
        name = self._get_channel_name(notifier)
        return name in channels
    
    def _get_channel_name(self, notifier) -> str:
        """获取通知器名称"""
        name = type(notifier).__name__.lower()
        if "wecom" in name:
            return "wecom"
        elif "dingtalk" in name:
            return "dingtalk"
        elif "console" in name:
            return "console"
        elif "file" in name:
            return "file"
        return "unknown"
    
    def _to_markdown(self, report: AnalysisReport) -> str:
        """转换为 Markdown"""
        lines = [
            f"## 错误分析报告",
            f"**服务名**：{report.service_name}",
            f"**分析ID**：{report.analysis_id}",
            "",
            f"### 摘要",
            report.summary,
        ]
        
        if report.hypotheses:
            lines.extend([
                "",
                "### 可能原因",
                *[f"- {h}" for h in report.hypotheses[:8]],
            ])
        
        if report.suggestions:
            lines.extend([
                "",
                "### 修复建议",
                *[f"- {s}" for s in report.suggestions[:10]],
            ])
        
        return "\n".join(lines)
```

## 四、插件注册和部署

### 1. 插件注册结构

```
root_seeker/
├── dify_plugins/
│   ├── __init__.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── zoekt_search.py
│   │   ├── vector_search.py
│   │   ├── call_graph_expander.py
│   │   ├── trace_chain_retriever.py
│   │   ├── repo_sync.py
│   │   └── vector_indexer.py
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── log_enricher.py
│   │   ├── service_router.py
│   │   ├── evidence_builder.py
│   │   └── notifier.py
│   └── registry.py  # 插件注册中心
```

### 2. 插件注册器

```python
# root_seeker/dify_plugins/registry.py
from typing import Dict, List, Type
from dify_client import Tool, Node

class PluginRegistry:
    """插件注册中心"""
    
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self.nodes: Dict[str, Node] = {}
    
    def register_tool(self, tool: Tool):
        """注册工具"""
        self.tools[tool.name] = tool
    
    def register_node(self, node: Node):
        """注册节点"""
        self.nodes[node.name] = node
    
    def get_tool(self, name: str) -> Tool:
        """获取工具"""
        return self.tools.get(name)
    
    def get_node(self, name: str) -> Node:
        """获取节点"""
        return self.nodes.get(name)
    
    def list_tools(self) -> List[str]:
        """列出所有工具"""
        return list(self.tools.keys())
    
    def list_nodes(self) -> List[str]:
        """列出所有节点"""
        return list(self.nodes.keys())

# 全局注册器实例
registry = PluginRegistry()
```

### 3. 插件初始化

```python
# root_seeker/dify_plugins/__init__.py
from root_seeker.dify_plugins.registry import registry
from root_seeker.dify_plugins.tools import (
    ZoektSearchTool,
    VectorSearchTool,
    CallGraphExpanderTool,
    TraceChainRetrieverTool,
)
from root_seeker.dify_plugins.nodes import (
    LogEnricherNode,
    ServiceRouterNode,
    EvidenceBuilderNode,
    NotifierNode,
)

def initialize_plugins(
    zoekt_client=None,
    vector_retriever=None,
    call_graph_expander=None,
    trace_chain_provider=None,
    log_enricher=None,
    router=None,
    evidence_builder=None,
    notifiers=None,
):
    """初始化所有插件"""
    
    # 注册工具
    if zoekt_client:
        registry.register_tool(ZoektSearchTool(zoekt_client))
    
    if vector_retriever:
        registry.register_tool(VectorSearchTool(vector_retriever))
    
    if call_graph_expander:
        registry.register_tool(CallGraphExpanderTool(call_graph_expander))
    
    if trace_chain_provider:
        registry.register_tool(TraceChainRetrieverTool(trace_chain_provider))
    
    # 注册节点
    if log_enricher:
        registry.register_node(LogEnricherNode(log_enricher))
    
    if router:
        registry.register_node(ServiceRouterNode(router))
    
    if evidence_builder:
        registry.register_node(EvidenceBuilderNode(evidence_builder))
    
    if notifiers:
        registry.register_node(NotifierNode(notifiers))
    
    return registry
```

### 4. Dify 集成端点

```python
# root_seeker/app.py
from root_seeker.dify_plugins import initialize_plugins, registry

@app.post("/dify/tools/{tool_name}")
async def dify_tool_endpoint(
    tool_name: str,
    request: ToolRequest,
    _: None = Depends(require_api_key),
):
    """Dify 工具调用端点"""
    tool = registry.get_tool(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool {tool_name} not found")
    
    try:
        result = await tool.execute(request.parameters)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dify/nodes/{node_name}")
async def dify_node_endpoint(
    node_name: str,
    request: NodeRequest,
    _: None = Depends(require_api_key),
):
    """Dify 节点调用端点"""
    node = registry.get_node(node_name)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {node_name} not found")
    
    try:
        result = await node.execute(request.inputs)
        return {"outputs": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dify/plugins")
async def list_plugins(_: None = Depends(require_api_key)):
    """列出所有可用插件"""
    return {
        "tools": registry.list_tools(),
        "nodes": registry.list_nodes(),
    }
```

## 五、Dify 工作流配置

### 完整工作流示例

```json
{
  "name": "错误分析工作流（插件版）",
  "description": "使用自定义插件进行错误分析",
  "nodes": [
    {
      "id": "start",
      "type": "start",
      "data": {
        "title": "开始",
        "variables": [
          {"variable": "service_name", "type": "string"},
          {"variable": "error_log", "type": "string"},
          {"variable": "query_key", "type": "string"}
        ]
      }
    },
    {
      "id": "log_enricher",
      "type": "custom-node",
      "data": {
        "title": "日志补全",
        "node_type": "log_enricher",
        "endpoint": "http://localhost:8000/dify/nodes/log_enricher",
        "inputs": {
          "service_name": "{{service_name}}",
          "error_log": "{{error_log}}",
          "query_key": "{{query_key}}"
        }
      }
    },
    {
      "id": "service_router",
      "type": "custom-node",
      "data": {
        "title": "服务路由",
        "node_type": "service_router",
        "endpoint": "http://localhost:8000/dify/nodes/service_router",
        "inputs": {
          "service_name": "{{service_name}}"
        }
      }
    },
    {
      "id": "zoekt_search",
      "type": "tool",
      "data": {
        "title": "Zoekt 检索",
        "tool_name": "zoekt_search",
        "endpoint": "http://localhost:8000/dify/tools/zoekt_search",
        "parameters": {
          "query": "{{error_log}}",
          "repo_path": "{{service_router.outputs.repo.local_dir}}",
          "service_name": "{{service_name}}"
        }
      }
    },
    {
      "id": "vector_search",
      "type": "tool",
      "data": {
        "title": "向量检索",
        "tool_name": "vector_search",
        "endpoint": "http://localhost:8000/dify/tools/vector_search",
        "parameters": {
          "query": "{{error_log}}",
          "repo_path": "{{service_router.outputs.repo.local_dir}}",
          "service_name": "{{service_name}}"
        }
      }
    },
    {
      "id": "trace_chain",
      "type": "tool",
      "data": {
        "title": "Trace 链查询",
        "tool_name": "trace_chain_retriever",
        "endpoint": "http://localhost:8000/dify/tools/trace_chain_retriever",
        "parameters": {
          "trace_id": "{{log_enricher.outputs.trace_id}}",
          "request_id": "{{log_enricher.outputs.request_id}}",
          "service_name": "{{service_name}}"
        }
      }
    },
    {
      "id": "evidence_builder",
      "type": "custom-node",
      "data": {
        "title": "构建证据包",
        "node_type": "evidence_builder",
        "endpoint": "http://localhost:8000/dify/nodes/evidence_builder",
        "inputs": {
          "error_log": "{{error_log}}",
          "repo": "{{service_router.outputs.repo}}",
          "zoekt_hits": "{{zoekt_search.outputs.hits}}",
          "vector_hits": "{{vector_search.outputs.chunks}}",
          "log_bundle": "{{log_enricher.outputs.log_bundle}}"
        }
      }
    },
    {
      "id": "llm_analyze",
      "type": "llm",
      "data": {
        "title": "LLM 分析",
        "model": "deepseek-chat",
        "provider": "openai",
        "base_url": "https://api.deepseek.com",
        "prompt": "基于以下错误日志和代码证据，分析错误原因并给出修复建议...",
        "context": {
          "error_log": "{{error_log}}",
          "evidence": "{{evidence_builder.outputs.evidence}}",
          "logs": "{{log_enricher.outputs.log_bundle}}"
        }
      }
    },
    {
      "id": "notifier",
      "type": "custom-node",
      "data": {
        "title": "发送通知",
        "node_type": "notifier",
        "endpoint": "http://localhost:8000/dify/nodes/notifier",
        "inputs": {
          "report": {
            "analysis_id": "{{$workflow.id}}",
            "service_name": "{{service_name}}",
            "summary": "{{llm_analyze.outputs.summary}}",
            "hypotheses": "{{llm_analyze.outputs.hypotheses}}",
            "suggestions": "{{llm_analyze.outputs.suggestions}}"
          }
        }
      }
    }
  ],
  "edges": [
    {"source": "start", "target": "log_enricher"},
    {"source": "start", "target": "service_router"},
    {"source": "service_router", "target": "zoekt_search"},
    {"source": "service_router", "target": "vector_search"},
    {"source": "log_enricher", "target": "trace_chain"},
    {"source": "zoekt_search", "target": "evidence_builder"},
    {"source": "vector_search", "target": "evidence_builder"},
    {"source": "trace_chain", "target": "evidence_builder"},
    {"source": "evidence_builder", "target": "llm_analyze"},
    {"source": "llm_analyze", "target": "notifier"}
  ]
}
```

## 六、实施步骤

### 第一步：创建插件框架（3-5天）

1. 创建插件目录结构
2. 实现基础 Tool 和 Node 基类
3. 创建插件注册器
4. 添加 API 端点

### 第二步：实现核心插件（1-2周）

1. **优先级1**：LogEnricherNode, ServiceRouterNode
2. **优先级2**：ZoektSearchTool, VectorSearchTool
3. **优先级3**：EvidenceBuilderNode, NotifierNode
4. **优先级4**：CallGraphExpanderTool, TraceChainRetrieverTool

### 第三步：测试和集成（1周）

1. 单元测试每个插件
2. 集成测试完整工作流
3. 性能测试
4. 文档编写

### 第四步：Dify 集成（3-5天）

1. 在 Dify 中注册自定义工具和节点
2. 创建工作流
3. 测试端到端流程
4. 团队培训

## 七、优势总结

### 插件化架构的优势

1. **代码复用最大化**
   - 保留现有核心逻辑
   - 只需封装接口
   - 减少重写成本

2. **模块化设计**
   - 每个插件独立
   - 易于测试和维护
   - 可以单独升级

3. **灵活组合**
   - 通过 Dify 工作流灵活组合
   - 不同场景使用不同插件
   - 易于 A/B 测试

4. **渐进式迁移**
   - 可以逐个插件迁移
   - 不影响现有系统
   - 降低风险

5. **易于扩展**
   - 添加新插件只需实现接口
   - 不影响其他插件
   - 社区可以贡献插件

## 八、总结

**推荐方案**：将项目拆解为多个 Dify 插件

**理由**：
1. ✅ 最大化代码复用
2. ✅ 模块化设计，易于维护
3. ✅ 灵活组合，适应不同场景
4. ✅ 渐进式迁移，风险低
5. ✅ 易于扩展和社区贡献

**下一步**：
1. 先实现核心插件（LogEnricher, ServiceRouter, ZoektSearch）
2. 在 Dify 中测试基础工作流
3. 逐步添加其他插件
4. 完善文档和测试

---

这种插件化架构既能享受 Dify 的优势，又能最大化保留现有代码，是最佳的迁移方案！
