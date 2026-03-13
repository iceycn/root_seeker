# v2.0.0 架构设计 (Architecture Design)

## 1. 核心模块概览

v2.0.0 将引入 `McpGateway` 和 `AiGateway` 作为核心组件，重构现有的 `AnalyzerService` 为 AI 驱动的编排器。

### 模块划分

*   **`root_seeker.mcp`**: 新增包，包含 MCP 相关实现。
    *   `gateway.py`: `McpGateway` 类，负责工具注册、发现 (`list_tools`) 和调用 (`call_tool`)。
    *   `tools/`: 内部工具实现。
        *   `base.py`: `BaseTool` 抽象基类。
        *   `analysis.py`: `analysis.run` 工具（封装 `AnalyzerService`）。
        *   `code.py`: `code.search`, `code.read` 工具（封装 `ZoektClient`, `EvidenceBuilder`）。
        *   `index.py`: `index.get_status` 工具。
        *   `correlation.py`: `correlation.get_info` 工具（封装 `LogEnricher`）。
        *   `deps.py`: `deps.get_graph` 工具（封装 `ServiceGraph` 和 `CallGraphExpander`）。
    *   `protocol.py`: MCP 协议数据结构定义 (`ToolSchema`, `ToolResult` 等)。

*   **`root_seeker.ai`**: 新增包，包含 AI 网关与编排。
    *   `gateway.py`: `AiGateway` 类，负责多 Provider 管理、动态配置切换。
    *   `orchestrator.py`: `AiOrchestrator` 类（替代原 `AnalyzerService` 的主流程），负责 Plan -> Act -> Synthesize 循环。

*   **`root_seeker.config`**: 扩展配置模型。
    *   新增 `McpConfig` (定义外部 server)。
    *   新增 `AiGatewayConfig` (定义多 AI provider)。

### 数据流

1.  **启动阶段**:
    *   `app.py` 初始化 `AiGateway` 和 `McpGateway`。
    *   `McpGateway` 注册内部 tools，并连接配置的外部 MCP Servers (如 Aliyun MCP)。
2.  **请求阶段 (`/ingest`)**:
    *   接收日志 -> `JobQueue` -> `AiOrchestrator.analyze`.
3.  **分析阶段 (AI 驱动)**:
    *   `AiOrchestrator` 从 `McpGateway.list_tools()` 获取工具列表（摘要）。
    *   `AiOrchestrator` 调用 LLM 生成 **Plan** (JSON)。
    *   `AiOrchestrator` 根据 Plan 调用 `McpGateway.call_tool()`。
        *   `McpGateway` 路由到内部函数或外部 MCP Server。
        *   执行结果封装为 `ToolResult` 返回。
    *   `AiOrchestrator` 汇总结果，调用 LLM 生成最终报告。

## 2. 关键接口定义

### McpGateway

```python
class McpGateway:
    def __init__(self, config: McpConfig): ...
    
    async def startup(self):
        """连接外部 MCP Servers"""
        ...
        
    async def shutdown(self):
        """断开连接"""
        ...

    def register_internal_tool(self, tool: BaseTool):
        """注册内部 Python 函数工具"""
        ...

    async def list_tools(self) -> list[ToolSchema]:
        """返回所有可用工具（内部 + 外部）"""
        ...

    async def call_tool(self, name: str, args: dict, context: dict | None = None) -> ToolResult:
        """
        执行工具
        context: 包含 trace_id, user_id 等，透传给 tool
        """
        ...
```

### AiGateway

```python
class AiGateway:
    def __init__(self, config: AiGatewayConfig): ...
    
    def get_provider(self, name: str = None) -> LLMProvider:
        """获取指定或默认的 LLM Provider"""
        ...
        
    async def chat_completion(self, messages: list, config_name: str = None, **kwargs):
        """统一调用接口"""
        provider = self.get_provider(config_name)
        return await provider.generate(messages, **kwargs)
        
    def add_provider(self, name: str, config: AiProviderConfig):
        """动态新增配置"""
        ...
```

## 3. MCP 工具封装 (Schema 设计)

### 3.1 基础勘探类

*   **`code.search`**
    *   Input: `query` (regex), `repo_id` (optional), `file_pattern` (optional)
    *   Output: 文件路径、行号、代码片段摘要
*   **`code.read`**
    *   Input: `repo_id`, `file_path`, `start_line` (optional), `end_line` (optional)
    *   Output: 完整代码内容

### 3.2 依赖关系类 (新增)

*   **`deps.get_graph`**
    *   Input:
        *   `scope`: "service" (默认) | "method"
        *   `target`: 服务名 或 方法签名
        *   `direction`: "upstream" | "downstream" | "both"
        *   `depth`: 1 (默认)
    *   Output: 图结构 (`nodes`, `edges`)

### 3.3 状态与上下文类

*   **`index.get_status`**: 返回 Qdrant/Zoekt 索引状态。
*   **`correlation.get_info`**: 返回 Trace Chain 信息。

### 3.4 高级分析类

*   **`analysis.run`**: 允许 Agent 递归调用分析能力（例如分析子服务）。
    *   Input: `error_event`
    *   Output: `AnalysisReport`

## 4. 核心文件改动建议

1.  **`root_seeker/config.py`**:
    *   新增 `McpConfig` 类。
    *   新增 `AiGatewayConfig` 类。
2.  **`root_seeker/app.py`**:
    *   初始化 `AiGateway` 和 `McpGateway`。
    *   将 `AnalyzerService` 替换为 `AiOrchestrator` (或重构 `AnalyzerService` 使用 Gateway)。
3.  **`root_seeker/services/analyzer.py`**:
    *   重构 `analyze` 方法，移除硬编码的 `zoekt -> vector -> evidence` 流程。
    *   实现 `Plan -> Act -> Check` 循环。
4.  **`root_seeker/mcp/`**: 新建目录和文件。
5.  **`root_seeker/ai/`**: 新建目录和文件。

## 5. 安全与兼容性

*   **AK/SK**: 仅通过环境变量传递给 `AiGateway` 和 `McpGateway`，不写入代码或日志。
*   **兼容性**: 
    *   保留 `AnalyzerService` 的旧接口用于回退。
    *   `AiOrchestrator` 输出结构保持 `AnalysisReport` 格式不变。
