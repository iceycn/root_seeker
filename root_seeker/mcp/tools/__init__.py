"""MCP 内部工具实现。"""

from root_seeker.mcp.tools.base import BaseTool
from root_seeker.mcp.tools.analysis import AnalysisRunTool
from root_seeker.mcp.tools.code import CodeReadTool, CodeResolveSymbolTool, CodeSearchTool
from root_seeker.mcp.tools.correlation import CorrelationInfoTool
from root_seeker.mcp.tools.cmd import CmdRunBuildAnalysisTool
from root_seeker.mcp.tools.deps import DepsGraphTool
from root_seeker.mcp.tools.deps_external import (
    DepsDiffDeclaredVsResolvedTool,
    DepsParseExternalTool,
    DepsScanBinariesTool,
)
from root_seeker.mcp.tools.deps_sources import DepsFetchJavaSourcesTool, DepsIndexDependencySourcesTool
from root_seeker.mcp.tools.index import IndexStatusTool
from root_seeker.mcp.tools.lsp import (
    LspDefinitionTool,
    LspDocumentSymbolsTool,
    LspHoverTool,
    LspReferencesTool,
    LspStartTool,
    LspStopTool,
    LspWorkspaceSymbolTool,
)

__all__ = [
    "BaseTool",
    "AnalysisRunTool",
    "CodeSearchTool",
    "CodeReadTool",
    "CodeResolveSymbolTool",
    "IndexStatusTool",
    "CorrelationInfoTool",
    "DepsGraphTool",
    "DepsParseExternalTool",
    "DepsDiffDeclaredVsResolvedTool",
    "DepsScanBinariesTool",
    "DepsFetchJavaSourcesTool",
    "DepsIndexDependencySourcesTool",
    "CmdRunBuildAnalysisTool",
    "LspStartTool",
    "LspStopTool",
    "LspWorkspaceSymbolTool",
    "LspDefinitionTool",
    "LspReferencesTool",
    "LspHoverTool",
    "LspDocumentSymbolsTool",
]
