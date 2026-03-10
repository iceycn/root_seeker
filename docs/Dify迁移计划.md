# Dify.ai 迁移方案

## 一、Dify 简介

Dify 是一个开源的 LLM 应用开发平台，提供：
- **可视化工作流编辑器**：拖拽式界面构建复杂工作流
- **RAG 引擎**：内置向量检索和知识库管理
- **Agent 框架**：支持工具调用和函数调用
- **多模型支持**：支持 OpenAI、DeepSeek、豆包等多种 LLM
- **API 和 SDK**：完整的 REST API 和 Python SDK
- **中文支持**：原生中文界面和文档

## 二、Dify vs Flowise 对比

| 特性 | Dify | Flowise |
|------|------|---------|
| **开源** | ✅ 完全开源 | ✅ 开源 |
| **中文支持** | ✅ 原生中文 | ⚠️ 英文为主 |
| **RAG 功能** | ✅ 内置强大 RAG | ⚠️ 需要配置 |
| **工作流编辑器** | ✅ 功能强大 | ✅ 功能强大 |
| **API 支持** | ✅ REST API + SDK | ✅ REST API |
| **知识库管理** | ✅ 内置 | ❌ 需要外部 |
| **部署方式** | ✅ Docker/云部署 | ✅ Docker |
| **社区活跃度** | ✅ 非常活跃 | ✅ 活跃 |
| **企业功能** | ✅ 权限、审计等 | ⚠️ 基础功能 |

## 三、使用 Dify 的优势

### 1. 更适合中文环境
- 原生中文界面和文档
- 对中文 LLM（如豆包）支持更好
- 中文社区活跃

### 2. 内置 RAG 功能
- 可以直接使用 Dify 的知识库管理代码索引
- 内置向量检索和混合检索
- 减少自建向量库的复杂度

### 3. 更完整的功能
- 内置 Agent 框架
- 支持工具调用（Tool Calling）
- 工作流支持条件分支、循环等

### 4. 更好的企业功能
- 权限管理
- 审计日志
- 多租户支持
- API 密钥管理

### 5. 易于集成
- Python SDK
- REST API
- Webhook 支持

## 四、架构设计

### 当前架构 vs Dify 架构

#### 当前架构
```
Webhook → JobQueue → AnalyzerService
  ↓
LogEnricher → ServiceRouter → EvidenceBuilder
  ↓
LLMProvider (多轮对话)
  ↓
Notifiers
```

#### Dify 架构（推荐）
```
Webhook → FastAPI Endpoint
  ↓
Dify Workflow API
  ├─ Node: 事件归一化
  ├─ Node: 日志补全（调用外部 API）
  ├─ Node: 路由到仓库（调用外部 API）
  ├─ Node: 构建证据（调用 Tools）
  │   ├─ Tool: Zoekt 检索
  │   ├─ Tool: 向量检索（使用 Dify RAG）
  │   └─ Tool: 调用链展开
  ├─ Node: LLM 分析（多轮对话）
  └─ Node: 通知（调用外部 API）
```

## 五、具体实现方案

### 方案 A：完全使用 Dify（推荐）

**优势**：
- 最大化利用 Dify 的功能
- 减少自建组件
- 统一管理界面

**实现步骤**：

#### 1. 部署 Dify

```bash
# 使用 Docker Compose 部署
git clone https://github.com/langgenius/dify.git
cd dify/docker
docker-compose up -d
```

#### 2. 创建知识库（代码索引）

```python
# root_seeker/dify/integration.py
from dify_client import DifyClient

class DifyCodeKnowledgeBase:
    def __init__(self, api_key: str, base_url: str = "http://localhost:8001"):
        self.client = DifyClient(api_key=api_key, base_url=base_url)
        self.kb_id = None
    
    async def create_knowledge_base(self, name: str):
        """创建知识库"""
        kb = await self.client.knowledge_bases.create(
            name=name,
            description="代码知识库",
            embedding_model="text-embedding-3-large",
        )
        self.kb_id = kb.id
        return kb
    
    async def add_repo(self, repo_path: str, service_name: str):
        """添加仓库到知识库"""
        # 使用 Dify 的文件上传 API
        files = await self.client.knowledge_bases.upload_files(
            knowledge_base_id=self.kb_id,
            files=[repo_path],
        )
        return files
```

#### 3. 创建自定义工具（Tools）

Dify 支持自定义工具，我们可以将现有组件封装为工具：

```python
# root_seeker/dify/tools/zoekt_tool.py
from typing import Dict, Any
from dify_client import Tool

class ZoektSearchTool(Tool):
    name = "zoekt_search"
    description = "使用 Zoekt 进行代码词法检索"
    
    def __init__(self, zoekt_client):
        self.zoekt = zoekt_client
    
    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """执行 Zoekt 搜索"""
        query = parameters.get("query")
        repo_path = parameters.get("repo_path")
        service_name = parameters.get("service_name")
        
        # 调用现有的 ZoektClient
        hits = await self.zoekt.search(query=query)
        
        return {
            "hits": [
                {
                    "file_path": hit.file_path,
                    "line_number": hit.line_number,
                    "content": hit.content,
                }
                for hit in hits[:10]
            ]
        }
```

#### 4. 在 Dify 中创建工作流

**工作流节点配置**：

1. **开始节点**：接收 Webhook 事件
   ```json
   {
     "type": "start",
     "inputs": {
       "event": "{{event}}",
       "service_name": "{{service_name}}",
       "error_log": "{{error_log}}"
     }
   }
   ```

2. **HTTP 请求节点**：日志补全
   ```json
   {
     "type": "http-request",
     "name": "enrich_logs",
     "method": "POST",
     "url": "http://localhost:8000/internal/enrich",
     "headers": {
       "Content-Type": "application/json"
     },
     "body": {
       "event": "{{event}}",
       "query_key": "{{query_key}}"
     }
   }
   ```

3. **代码检索节点**：使用 RAG + Tools
   ```json
   {
     "type": "knowledge-retrieval",
     "name": "retrieve_code",
     "knowledge_base_id": "{{kb_id}}",
     "query": "{{error_log}}",
     "top_k": 10,
     "retrieval_mode": "hybrid"
   }
   ```

4. **工具调用节点**：Zoekt 检索
   ```json
   {
     "type": "tool",
     "name": "zoekt_search",
     "tool_name": "zoekt_search",
     "parameters": {
       "query": "{{extracted_keywords}}",
       "repo_path": "{{repo.local_dir}}",
       "service_name": "{{service_name}}"
     }
   }
   ```

5. **LLM 节点**：多轮对话分析
   ```json
   {
     "type": "llm",
     "name": "analyze_error",
     "model": "deepseek-chat",
     "provider": "openai",
     "base_url": "https://api.deepseek.com",
     "temperature": 0.7,
     "prompt": "基于以下错误日志和代码证据，分析错误原因...",
     "context": {
       "error_log": "{{error_log}}",
       "evidence": "{{evidence}}",
       "logs": "{{log_bundle}}"
     }
   }
   ```

6. **HTTP 请求节点**：发送通知
   ```json
   {
     "type": "http-request",
     "name": "send_notification",
     "method": "POST",
     "url": "http://localhost:8000/internal/notify",
     "body": {
       "report": "{{analysis_result}}"
     }
   }
   ```

### 方案 B：混合模式（更灵活）

**优势**：
- 保留现有核心组件
- 只使用 Dify 的工作流和 LLM 部分
- 更灵活的定制

**实现**：

```python
# root_seeker/dify/hybrid_integration.py
from dify_client import DifyClient, WorkflowClient

class HybridAnalyzer:
    def __init__(self, dify_client: DifyClient):
        self.dify = dify_client
        self.workflow_id = None
    
    async def create_workflow(self):
        """创建 Dify 工作流"""
        workflow = await self.dify.workflows.create(
            name="错误分析工作流",
            description="分析错误日志并生成报告",
        )
        self.workflow_id = workflow.id
        return workflow
    
    async def analyze(self, event: NormalizedErrorEvent):
        """执行分析（混合模式）"""
        # 1. 使用现有组件进行日志补全和路由
        log_bundle = await self.enricher.enrich(event)
        repo = self.router.route(event.service_name)[0]
        
        # 2. 使用现有组件构建部分证据
        evidence = await self.evidence_builder.build(...)
        
        # 3. 使用 Dify 进行 LLM 分析
        result = await self.dify.workflows.run(
            workflow_id=self.workflow_id,
            inputs={
                "error_log": event.error_log,
                "log_bundle": log_bundle.to_dict(),
                "evidence": evidence.to_dict(),
                "service_name": event.service_name,
            }
        )
        
        return result
```

## 六、Dify 工作流配置示例

### 完整工作流 JSON

```json
{
  "name": "错误分析工作流",
  "description": "分析错误日志并生成修复建议",
  "nodes": [
    {
      "id": "start",
      "type": "start",
      "data": {
        "title": "开始",
        "variables": [
          {
            "variable": "service_name",
            "label": "服务名",
            "type": "string",
            "required": true
          },
          {
            "variable": "error_log",
            "label": "错误日志",
            "type": "string",
            "required": true
          }
        ]
      }
    },
    {
      "id": "enrich",
      "type": "http-request",
      "data": {
        "title": "日志补全",
        "method": "POST",
        "url": "http://localhost:8000/internal/enrich",
        "headers": {
          "Content-Type": "application/json"
        },
        "body": {
          "service_name": "{{service_name}}",
          "error_log": "{{error_log}}"
        }
      }
    },
    {
      "id": "retrieve_code",
      "type": "knowledge-retrieval",
      "data": {
        "title": "代码检索",
        "knowledge_base_id": "code_kb",
        "query": "{{error_log}}",
        "top_k": 10,
        "retrieval_mode": "hybrid"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "data": {
        "title": "LLM 分析",
        "model": "deepseek-chat",
        "provider": "openai",
        "base_url": "https://api.deepseek.com",
        "temperature": 0.7,
        "prompt": "你是一个资深的 SRE 工程师。基于以下错误日志和代码证据，分析错误原因并给出修复建议。\n\n错误日志：\n{{error_log}}\n\n代码证据：\n{{retrieve_code.result}}\n\n请输出 JSON 格式：\n{\n  \"summary\": \"错误摘要\",\n  \"hypotheses\": [\"可能原因1\", \"可能原因2\"],\n  \"suggestions\": [\"修复建议1\", \"修复建议2\"]\n}"
      }
    },
    {
      "id": "notify",
      "type": "http-request",
      "data": {
        "title": "发送通知",
        "method": "POST",
        "url": "http://localhost:8000/internal/notify",
        "body": {
          "service_name": "{{service_name}}",
          "analysis": "{{analyze.result}}"
        }
      }
    }
  ],
  "edges": [
    {"source": "start", "target": "enrich"},
    {"source": "enrich", "target": "retrieve_code"},
    {"source": "retrieve_code", "target": "analyze"},
    {"source": "analyze", "target": "notify"}
  ]
}
```

## 七、集成步骤

### 第一步：部署 Dify（1天）

```bash
# 1. 克隆 Dify 仓库
git clone https://github.com/langgenius/dify.git
cd dify/docker

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，配置数据库、Redis 等

# 3. 启动服务
docker-compose up -d

# 4. 访问 Web UI
# http://localhost:3000
```

### 第二步：创建知识库（1-2天）

1. **在 Dify UI 中创建知识库**
   - 名称：代码知识库
   - 向量模型：选择支持的 embedding 模型
   - 索引方式：混合检索（向量 + 关键词）

2. **批量导入代码**
   ```python
   # 使用 Python SDK 批量导入
   from dify_client import DifyClient
   
   client = DifyClient(api_key="your-api-key")
   
   # 为每个仓库创建知识库
   for repo in repos:
       kb = await client.knowledge_bases.create(
           name=f"{repo.service_name}_code",
           embedding_model="text-embedding-3-large",
       )
       
       # 上传代码文件
       await client.knowledge_bases.upload_files(
           knowledge_base_id=kb.id,
           files=[f"{repo.local_dir}/**/*.py"],
       )
   ```

### 第三步：创建自定义工具（2-3天）

1. **注册 Zoekt 工具**
   ```python
   # 在 Dify 中注册自定义工具
   tool = await client.tools.create(
       name="zoekt_search",
       description="使用 Zoekt 进行代码词法检索",
       parameters={
           "type": "object",
           "properties": {
               "query": {"type": "string"},
               "repo_path": {"type": "string"},
               "service_name": {"type": "string"},
           },
           "required": ["query", "repo_path"]
       },
       # 工具执行端点
       endpoint="http://localhost:8000/tools/zoekt",
   )
   ```

2. **实现工具执行端点**
   ```python
   # root_seeker/app.py
   @app.post("/tools/zoekt")
   async def zoekt_tool_endpoint(request: ToolRequest):
       """Dify 工具调用端点"""
       query = request.parameters.get("query")
       repo_path = request.parameters.get("repo_path")
       
       hits = await zoekt_client.search(query=query)
       return {
           "result": format_hits(hits)
       }
   ```

### 第四步：创建工作流（2-3天）

1. **在 Dify UI 中创建工作流**
   - 使用可视化编辑器拖拽节点
   - 配置每个节点的参数
   - 连接节点形成工作流

2. **或者使用 API 创建工作流**
   ```python
   workflow = await client.workflows.create(
       name="错误分析工作流",
       graph_config=workflow_config,  # JSON 配置
   )
   ```

### 第五步：集成到现有系统（3-5天）

```python
# root_seeker/services/dify_analyzer.py
from dify_client import DifyClient

class DifyAnalyzerService:
    def __init__(self, dify_client: DifyClient, workflow_id: str):
        self.dify = dify_client
        self.workflow_id = workflow_id
    
    async def analyze(self, event: NormalizedErrorEvent) -> AnalysisReport:
        """使用 Dify 工作流进行分析"""
        # 调用 Dify 工作流
        result = await self.dify.workflows.run(
            workflow_id=self.workflow_id,
            inputs={
                "service_name": event.service_name,
                "error_log": event.error_log,
                "query_key": event.query_key,
                "timestamp": event.timestamp.isoformat(),
            },
            user="system",
        )
        
        # 解析结果
        return AnalysisReport(
            analysis_id=result.id,
            service_name=event.service_name,
            summary=result.outputs.get("summary"),
            hypotheses=result.outputs.get("hypotheses", []),
            suggestions=result.outputs.get("suggestions", []),
            evidence=parse_evidence(result.outputs.get("evidence")),
        )
```

## 八、Dify vs Flowise 选择建议

### 选择 Dify 如果：
- ✅ 需要中文界面和文档
- ✅ 需要内置 RAG 功能
- ✅ 需要企业级功能（权限、审计）
- ✅ 团队更熟悉中文工具
- ✅ 需要知识库管理功能

### 选择 Flowise 如果：
- ✅ 更偏好英文工具
- ✅ 需要更轻量级的解决方案
- ✅ 已经有自己的 RAG 系统
- ✅ 团队更熟悉 LangChain 生态

## 九、推荐方案

### 推荐：使用 Dify

**理由**：
1. **更好的中文支持**：原生中文界面，更适合中文团队
2. **内置 RAG**：可以直接使用 Dify 管理代码知识库，减少自建组件
3. **更完整的功能**：企业级功能更完善
4. **活跃的中文社区**：问题更容易解决

### 实施建议

**阶段1：试点（1-2周）**
- 部署 Dify
- 创建一个简单的知识库
- 创建基础工作流
- 测试功能

**阶段2：迁移（2-3周）**
- 迁移代码索引到 Dify 知识库
- 创建工作流
- 集成自定义工具
- 并行运行测试

**阶段3：优化（1-2周）**
- 优化工作流性能
- 完善错误处理
- 团队培训
- 文档更新

## 十、代码示例：完整集成

```python
# root_seeker/dify/integration.py
from dify_client import DifyClient, WorkflowClient
from root_seeker.domain import NormalizedErrorEvent, AnalysisReport

class DifyIntegration:
    def __init__(self, api_key: str, base_url: str = "http://localhost:8001"):
        self.client = DifyClient(api_key=api_key, base_url=base_url)
        self.workflow_id = None
    
    async def initialize(self):
        """初始化：创建工作流和知识库"""
        # 1. 创建知识库
        kb = await self.client.knowledge_bases.create(
            name="代码知识库",
            embedding_model="text-embedding-3-large",
        )
        
        # 2. 创建工作流（通过 API 或 UI）
        workflow = await self.client.workflows.create(
            name="错误分析工作流",
            graph_config=self._get_workflow_config(),
        )
        self.workflow_id = workflow.id
    
    async def analyze_error(self, event: NormalizedErrorEvent) -> AnalysisReport:
        """执行错误分析"""
        result = await self.client.workflows.run(
            workflow_id=self.workflow_id,
            inputs={
                "service_name": event.service_name,
                "error_log": event.error_log,
                "query_key": event.query_key,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            },
            user="system",
        )
        
        return self._parse_result(result, event)
    
    def _get_workflow_config(self) -> dict:
        """获取工作流配置"""
        return {
            "nodes": [...],  # 节点配置
            "edges": [...],  # 边配置
        }
    
    def _parse_result(self, result, event) -> AnalysisReport:
        """解析 Dify 返回结果"""
        outputs = result.outputs
        return AnalysisReport(
            analysis_id=result.id,
            service_name=event.service_name,
            summary=outputs.get("summary", ""),
            hypotheses=outputs.get("hypotheses", []),
            suggestions=outputs.get("suggestions", []),
        )
```

## 十一、总结

使用 Dify 的优势：
1. ✅ **更好的中文支持**
2. ✅ **内置 RAG 功能**
3. ✅ **企业级功能完善**
4. ✅ **易于集成和扩展**

建议采用 Dify 作为工作流平台，可以：
- 减少自建组件的复杂度
- 提供更好的可视化界面
- 利用内置的 RAG 功能
- 享受活跃的中文社区支持

---

**下一步**：可以先部署 Dify 进行试点，评估效果后再决定是否全面迁移。
