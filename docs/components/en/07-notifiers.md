# Notifiers (WeChat / DingTalk)

RootSeeker sends analysis reports as Markdown to WeChat or DingTalk groups.

## Config

```yaml
wecom:
  webhook_url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"

dingtalk:
  webhook_url: "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"
```

Configure one or both. Webhook URL contains keys; keep it out of version control.

[中文](../07-notifiers.md)
