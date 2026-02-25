# Notifiers (WeChat / DingTalk)

RootSeeker sends analysis reports as Markdown to WeChat or DingTalk groups via **AnalysisCompletedEvent** listeners.

## Event-Driven

Notifications are driven by `AnalysisCompletedEvent`: when a task completes, `NotifierCompletionListener` pushes to configured Notifiers (WeCom, DingTalk, Console, File).

## Config

```yaml
wecom:
  webhook_url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
  security_mode: ip   # sign | keyword | ip

dingtalk:
  webhook_url: "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"
  security_mode: sign   # sign | keyword | ip
  secret: "SEC..."     # required when security_mode=sign
```

Configure one or both. See [DingTalk docs](https://open.dingtalk.com/document/robots/custom-robot-access). Webhook URL contains keys; keep it out of version control.

## Custom Listener

Register via `app.state.event_bus.add_listener()` to run custom logic on completion.

[中文](../07-notifiers.md)
