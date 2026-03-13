# RootSeeker Hook 体系

在分析生命周期中注入自定义脚本。

## 支持的 Hook 类型

| Hook | 触发时机 | 可取消 |
|------|----------|--------|
| **AnalysisStart** | 分析开始前 | 是（取消则中止分析） |
| **AnalysisComplete** | 分析结束（成功或异常） | 否 |
| **PreToolUse** | 每次工具调用前 | 是（取消则跳过该工具） |
| **PostToolUse** | 每次工具调用后 | 否 |

## 目录与脚本

- **全局**：`~/.rootseek/hooks/`
- **配置**：`config.hooks.dirs` 可添加额外目录
- **脚本命名**：
  - Unix/macOS：`PreToolUse`、`AnalysisStart` 等（无扩展名，需 `chmod +x`）
  - Windows：`PreToolUse.ps1`、`AnalysisStart.ps1`

## 输入输出

**输入**：JSON 通过 stdin 传入，包含：

```json
{
  "root_seeker_version": "2.0",
  "hook_name": "PreToolUse",
  "timestamp": "1234567890000",
  "analysis_id": "abc123",
  "service_name": "order-svc",
  "tool_name": "code.read",
  "parameters": {"file_path": "src/OrderService.java"}
}
```

**输出**：stdout 最后一行需为 JSON：

```json
{
  "cancel": false,
  "contextModification": "可选：注入上下文的文本",
  "errorMessage": "可选：错误信息"
}
```

- `cancel: true` 时，PreToolUse 跳过该工具，AnalysisStart 中止分析
- `contextModification` 可向后续流程注入额外上下文（当前版本暂未使用）

## 配置

```yaml
hooks:
  enabled: true
  dirs: ["data/hooks"]  # 可选，额外目录
```

## 示例脚本

```bash
#!/usr/bin/env python3
# ~/.rootseek/hooks/PreToolUse
import sys, json
data = json.load(sys.stdin)
# 禁止 code.read 读取敏感文件
if data.get("tool_name") == "code.read":
    fp = data.get("parameters", {}).get("file_path", "")
    if "secret" in fp or "password" in fp:
        print(json.dumps({"cancel": True, "errorMessage": "禁止读取敏感文件"}))
        sys.exit(0)
print(json.dumps({"cancel": False}))
```

## 实现细节

- **PreToolUse**：传入 `_fill_step_args` 后的实际参数（含从 code.search 注入的 file_path）
- **有效 JSON 优先**：脚本非零退出但 stdout 含有效 JSON 时，仍使用 JSON 结果
- **contextModification 限制**：超 50KB 时自动截断
- **多行 JSON**：从 stdout 末尾扫描括号匹配，支持 debug 输出与 JSON 混合
- **DEBUG_HOOKS**：环境变量 `DEBUG_HOOKS=true` 时输出发现过程日志

## 实现文件

| 文件 | 职责 |
|------|------|
| `root_seeker/hooks/types.py` | Hook 类型定义 |
| `root_seeker/hooks/discovery.py` | HookDiscoveryCache、目录扫描、异常时返回空 |
| `root_seeker/hooks/executor.py` | 脚本执行、JSON 解析、context 截断 |
| `root_seeker/hooks/hub.py` | HookHub 调度、参数序列化（嵌套值 json.dumps） |
