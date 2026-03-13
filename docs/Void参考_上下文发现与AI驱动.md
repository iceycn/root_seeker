# Void 参考：上下文发现与 AI 驱动逻辑

参考 [voideditor/void](https://github.com/voideditor/void) 的上下文发现与 AI 驱动设计，用于优化 RootSeeker 的提示词与实现。

## 1. Void 核心设计

### 1.1 ChatMode 三模式

| 模式 | 能力 | 工具范围 |
|------|------|----------|
| **normal** | 普通对话 | 无工具 |
| **gather** | 只读勘探 | read_file, ls_dir, get_dir_tree, search_pathnames_only, search_for_files, search_in_file（排除 edit/delete/terminal） |
| **agent** | 完整代理 | 全部内置工具 + MCP 工具 |

### 1.2 上下文注入：目录树（directoryStr）

Void 在 **System Message 末尾** 注入工作区目录树：

```
Here is an overview of the user's file system:
Directory of /path/to/workspace:
├── src/
│   ├── main.ts
│   └── utils/
└── package.json
```

- `getAllDirectoriesStr()`：会话开始时注入，字符上限约 20k
- `get_dir_tree` 工具：AI 可主动请求某目录的树形结构
- 排除：.git、node_modules、dist、build 等

### 1.3 内置工具（Agent/Gather 共用读类）

| 工具 | 用途 |
|------|------|
| **read_file** | 读取文件，支持 start_line/end_line 分页 |
| **ls_dir** | 列出目录内容，分页 |
| **get_dir_tree** | 返回目录树，用于快速了解代码结构 |
| **search_pathnames_only** | 仅按路径/文件名搜索 |
| **search_for_files** | 按内容搜索（子串或正则） |
| **search_in_file** | 在单文件内搜索行号 |

### 1.4 Agent 模式关键提示

```
ALWAYS use tools to take actions and implement changes.
Prioritize taking as many steps as you need to complete your request over stopping early.
You will OFTEN need to gather context before making a change. Do not immediately make a change unless you have ALL relevant context.
ALWAYS have maximal certainty in a change BEFORE you make it. If you need more information, you should inspect it, search it, or take all required actions to maximize your certainty.
Only use ONE tool call at a time.
```

### 1.5 Gather 模式关键提示

```
You are in Gather mode, so you MUST use tools to gather information, files, and context to help the user answer their query.
You should extensively read files, types, content, etc, gathering full context to solve the problem.
```

## 2. 与 RootSeeker 的对应关系

| Void | RootSeeker |
|------|------------|
| directoryStr（目录树） | index.get_status（索引状态 + 仓库列表） |
| get_dir_tree | 无直接对应，可考虑 index.get_status 扩展 |
| search_for_files | code.search（Zoekt） |
| read_file | code.read |
| gather 模式 | Plan 中的「勘探」步骤 |
| agent 模式 | Plan→Act→Synthesize 全流程 |

## 3. 可借鉴点

1. **先注入代码结构概览**：Plan 前可先调用 index.get_status，将仓库/索引状态注入 Plan 上下文
2. **强化「先勘探再分析」**：借鉴 Void 的 "gather context before making a change"、"maximal certainty BEFORE"
3. **单次单工具**：Void 限制 "Only use ONE tool call at a time"，便于流式与调试
4. **evidence.context_search**：类似 search_for_files，按内容检索，应在 Plan 中明确推荐
