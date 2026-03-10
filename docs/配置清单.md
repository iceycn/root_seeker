# 配置检查清单

按当前 `config.yaml` 与代码要求，以下项**仍为占位或未填**，需要你按实际环境补全。

---

## 一、必填且当前为占位（不填会影响功能）

| 配置项 | 当前值 | 说明 | 获取/填写方式 |
|--------|--------|------|----------------|
| **aliyun_sls.*** | 已从 task-tools 填入 | 阿里云 SLS AK/SK、project、logstore | 见 config.yaml |
| **llm.*** | 已配置 kind=doubao | 豆包 API Key、base_url、model 等 | 见 config.yaml |

说明：当前 `config.yaml` 已填写 **aliyun_sls**（来自 task-tools）和 **llm**（豆包策略），核心分析链路可运行。若后续更换 AK/SK 或 LLM，按上表到控制台申请并替换。

---

## 二、按需填写（不填则对应功能不启用）

| 配置项 | 当前值 | 说明 | 不填时行为 |
|--------|--------|------|------------|
| **wecom.webhook_url** | `...key=REPLACE_ME` | 企业微信群机器人 Webhook | 分析完成后不会推送到企业微信 |
| **dingtalk** | 整块注释 | 钉钉群机器人 Webhook | 未启用钉钉推送；若用钉钉需取消注释并填 `webhook_url` |
| **api_keys** | `[]` | 接口鉴权密钥列表 | 不校验，任何人可调 Webhook/接口；生产建议填至少一个 key |

---

## 三、可选优化（有则更好）

| 配置项 | 说明 |
|--------|------|
| **aliyun_sls.endpoint** | 若 SLS 不在杭州地域，需改为对应 endpoint（如 `cn-shanghai.log.aliyuncs.com`） |
| **aliyun_sls.topic** | 若 Logstore 按 topic 区分日志，可填 topic 过滤 |
| **sql_templates[].query** | 当前为示例 SLS 查询语法，需与你们实际 SLS 字段、索引一致（如 `level`、`service` 等） |
| **llm.kind / base_url / model** | 若用豆包，需改 `kind: doubao`、豆包 `base_url` 及对应 `model` |
| **zoekt** | 若未部署 Zoekt，可注释整块 `zoekt:`，仅用 Qdrant + LLM 做分析 |

---

## 四、已就绪、一般无需改

- **data_dir / audit_dir**：项目内目录，已用 `data`、`data/audit`
- **repos**：48 个 IdeaProjects 仓库已写入，`local_dir` 指向本机路径
- **qdrant**：已指向本机 `127.0.0.1:6333`，Qdrant 已启动则无需改
- **embedding**：fastembed 本地向量化，已配置
- **evidence_level / max_evidence_*** **：已有合理默认值

---

## 五、最小可运行（仅做路由 + 存结果 + 查结果）

若暂时**不接 SLS、不接 LLM、不推送通知**，仅做「按 service_name 路由 → 存分析结果 → 查结果」：

1. **aliyun_sls** 仍为必填（当前代码未做成可选），可先填任意占位 AK/SK 和 project/logstore，或后续改代码将 `aliyun_sls` 改为可选。
2. **llm** 可保持 `api_key: REPLACE_ME`，报告会是「未配置云端LLM」。
3. **wecom** 可保持占位或删掉 wecom 块（若代码支持无 notifier）。

建议优先补全：**aliyun_sls 四项** + **llm.api_key**，再视需要补 **wecom** 或 **dingtalk** 和 **api_keys**。
