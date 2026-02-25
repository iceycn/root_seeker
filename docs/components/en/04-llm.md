# LLM Setup

RootSeeker uses cloud LLMs (DeepSeek, Doubao) for error analysis.

## Config

**DeepSeek:**

```yaml
llm:
  kind: deepseek
  base_url: "https://api.deepseek.com"
  api_key: "sk-xxx"
  model: "deepseek-chat"
  timeout_seconds: 90
```

**Doubao:**

```yaml
llm:
  kind: doubao
  base_url: "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
  api_key: "REPLACE_ME"
  model: "deepseek-v3-1-terminus"
  timeout_seconds: 90
```

## Timeout & Retry

- Default 90s; multi-turn analysis may need more.
- Built-in retry: 2 retries for ReadTimeout/ConnectTimeout.
- Round 3 failure: graceful fallback to partial report from Round 1/2.

[中文](../04-llm.md)
