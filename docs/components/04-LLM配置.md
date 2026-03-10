# LLM 配置指南

RootSeeker 使用云端大模型（DeepSeek、豆包等）进行错误分析与根因推断。

## 一、配置项说明

在 `config.yaml` 中：

```yaml
llm:
  kind: deepseek                    # deepseek | doubao
  base_url: "https://api.deepseek.com"
  api_key: "REPLACE_ME"
  model: "deepseek-chat"
  timeout_seconds: 90               # 多轮分析建议 90+ 秒
  temperature: 0.2                  # 可选
  max_tokens: null                  # 可选
```

### 字段说明

| 字段 | 说明 |
|------|------|
| kind | deepseek：base_url 为 API 根地址；doubao：base_url 填完整对话 URL |
| base_url | API 地址 |
| api_key | API Key |
| model | 模型名称 |
| timeout_seconds | 单次请求超时，多轮分析建议 90+ 秒 |
| temperature | 可选，默认 0.2 |
| max_tokens | 可选，不填则不传 |

## 二、DeepSeek 配置

```yaml
llm:
  kind: deepseek
  base_url: "https://api.deepseek.com"
  api_key: "sk-xxx"
  model: "deepseek-chat"
  timeout_seconds: 90
```

## 三、豆包配置

```yaml
llm:
  kind: doubao
  base_url: "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
  api_key: "REPLACE_ME"
  model: "deepseek-v3-1-terminus"
  timeout_seconds: 90
  temperature: 0.7
  max_tokens: 2000
```

豆包时 `base_url` 需填完整对话 URL。

## 四、超时与重试

- 默认 `timeout_seconds: 90`，多轮分析（Round 3 等）可能较慢，建议不低于 90。
- 应用内置：对 `ReadTimeout`、`ConnectTimeout` 自动重试 2 次，每次间隔 2 秒。
- 若 Round 3 仍超时，会优雅降级，基于 Round 1/2 返回部分报告。

## 五、不配置 LLM 时

若不配置 `llm` 块，应用会启动，但分析报告为固定文案「未配置云端LLM，已完成检索与证据收集。配置 llm.base_url/api_key/model 后可生成原因与修复建议。」

[English](en/04-llm.md)
