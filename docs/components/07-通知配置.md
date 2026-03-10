# 通知配置指南（企业微信 / 钉钉）

分析完成后，RootSeeker 通过**任务完成事件**将报告以 Markdown 形式推送到企业微信群或钉钉群。

## 一、事件驱动

通知由 `AnalysisCompletedEvent` 驱动：任务完成时，`NotifierCompletionListener` 监听该事件并推送到配置的 Notifier。所有通知（企业微信、钉钉、控制台、文件）均通过事件监听器统一处理。

## 二、配置项说明

在 `config.yaml` 中，二选一或同时配置：

```yaml
# 企业微信（参考 https://developer.work.weixin.qq.com/document/path/91770）
wecom:
  webhook_url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
  security_mode: ip   # sign | keyword | ip

# 钉钉（参考官方文档：https://open.dingtalk.com/document/robots/custom-robot-access）
dingtalk:
  webhook_url: "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"
  security_mode: sign   # sign（加签）| keyword（关键词）| ip（IP白名单）
  secret: "SEC..."     # security_mode=sign 时必填
```

应用优先使用企业微信，若未配置则用钉钉。两者都配置时都会发送。

## 三、企业微信

1. 在群聊中添加「群机器人」→ 选择「Webhook」
2. 复制 URL，将 `key=xxx` 部分填入 `webhook_url`
3. 安全设置与配置切换：
   - **加签**（`security_mode: sign`）：复制密钥填入 `wecom.secret`
   - **关键词**（`security_mode: keyword`）：不填 secret，报告含「错误分析」等词
   - **IP 白名单**（`security_mode: ip`）：不填 secret，企微侧配置 IP 白名单后直接推送
4. 机器人会以 Markdown 消息发送，内容含：analysis_id、时间、摘要、可能原因、修改建议、关键证据等

## 四、钉钉

1. 在群设置中添加「自定义」机器人
2. 安全设置与配置切换：
   - **加签**（`security_mode: sign`）：复制密钥填入 `dingtalk.secret`，应用自动计算签名
   - **关键词**（`security_mode: keyword`）：不填 secret，报告标题含「错误分析」，需在钉钉侧配置匹配的关键词
   - **IP 白名单**（`security_mode: ip`）：不填 secret，钉钉侧配置 IP 白名单后直接推送，无需额外处理
3. 将机器人提供的 `access_token` 拼成完整 URL 填入 `dingtalk.webhook_url`
4. 发送格式为 Markdown 类型消息

## 五、自定义监听器

可通过 `app.state.event_bus.add_listener()` 注册自定义监听器，在任务完成时执行自定义逻辑：

```python
from root_seeker.events import AnalysisCompletedEvent, AnalysisCompletedListener

class MyListener:
    def on_analysis_completed(self, event: AnalysisCompletedEvent) -> None:
        # event.payload 与 GET /analysis/{id} 返回值一致
        if event.status == "completed":
            print(event.payload.get("summary"))
```

## 六、验证

配置完成后，触发一次分析（如 `POST /ingest/aliyun-sls` 提交一条事件），在对应群中应收到一条 Markdown 消息。

## 七、安全

- Webhook URL 内含密钥，不要提交到代码库
- 仅放在 config 或密钥管理服务中
- 可在企业微信/钉钉侧限制机器人仅被指定群使用，并设置 IP 白名单（若支持）

[English](en/07-notifiers.md)
