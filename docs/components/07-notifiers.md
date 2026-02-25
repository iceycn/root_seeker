# 通知配置指南（企业微信 / 钉钉）

分析完成后，RootSeeker 可将报告以 Markdown 形式推送到企业微信群或钉钉群。

## 一、配置项说明

在 `config.yaml` 中，二选一或同时配置：

```yaml
# 企业微信
wecom:
  webhook_url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"

# 钉钉
dingtalk:
  webhook_url: "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"
```

应用优先使用企业微信，若未配置则用钉钉。两者都配置时都会发送。

## 二、企业微信

1. 在群聊中添加「群机器人」→ 选择「Webhook」
2. 复制 URL，将 `key=xxx` 部分填入 `webhook_url`
3. 机器人会以 Markdown 消息发送，内容含：analysis_id、时间、摘要、可能原因、修改建议、关键证据等

## 三、钉钉

1. 在群设置中添加「自定义」机器人
2. 安全设置可选「加签」或「关键词」；若用关键词，报告内容中已包含「错误分析」等词
3. 将机器人提供的 `access_token` 拼成完整 URL 填入 `dingtalk.webhook_url`
4. 发送格式为 Markdown 类型消息

## 四、验证

配置完成后，触发一次分析（如 `POST /ingest/aliyun-sls` 提交一条事件），在对应群中应收到一条 Markdown 消息。

## 五、安全

- Webhook URL 内含密钥，不要提交到代码库
- 仅放在 config 或密钥管理服务中
- 可在企业微信/钉钉侧限制机器人仅被指定群使用，并设置 IP 白名单（若支持）

[English](en/07-notifiers.md)
