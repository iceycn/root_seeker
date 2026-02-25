# 企业微信 / 钉钉配置

分析完成后，RootSeeker 可将报告以 Markdown 形式推送到企业微信群或钉钉群。

## 1. 二选一配置

在 `config.yaml` 中只配置其中一种即可（应用内优先使用企业微信，若未配置则用钉钉）：

**企业微信：**

```yaml
wecom:
  webhook_url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
```

**钉钉：**

```yaml
dingtalk:
  webhook_url: "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"
```

## 2. 企业微信

- 在群聊中添加「群机器人」→ 选择「Webhook」→ 复制 URL，将 `key=xxx` 部分填入上述 `webhook_url`。
- 机器人会以 Markdown 消息形式发送，内容包含：analysis_id、时间、摘要、可能原因、修改建议、关键证据等（见 analyzer 中 `_to_markdown`）。

## 3. 钉钉

- 在群设置中添加「自定义」机器人，安全设置可选「加签」或「关键词」；若用关键词，报告内容中已包含「错误分析」等词即可。
- 将机器人提供的 `access_token` 拼成完整 URL 填入 `dingtalk.webhook_url`。
- 发送格式为 Markdown 类型消息，内容结构与企业微信一致。

## 4. 验证

配置完成后，触发一次分析（如 `POST /ingest/aliyun-sls` 提交一条事件），在对应群中应收到一条 Markdown 消息。若未收到，可查看应用日志或审计日志中是否有通知发送错误。

## 5. 安全

- Webhook URL 内含密钥，不要提交到代码库；仅放在 config 或密钥管理服务中。
- 可在企业微信/钉钉侧限制机器人仅被指定群使用，并设置访问 IP 白名单（若厂商支持）。
