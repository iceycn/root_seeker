# 服务依赖关系（由 POST /graph/rebuild 生成）

数据来源：`data/service_graph.json`，或调用 `GET /graph` 获取最新。

含义：**caller** 调用 **callee**（caller 依赖 callee）。

## 依赖边汇总（caller → callee）

| 调用方 (caller) | 被调用方 (callee) |
|-----------------|-------------------|
| customize-api | enterprise-manage-api |
| customize-api | training-manage-api |
| customize-api | user-center-api |
| enterprise-split-api | thirdoa-api |
| knowledge-api | platform-api |
| knowledge-api | isv-api |
| knowledge-api | api-distribution |
| knowledge-api | evaluation-api |
| out-oa-api | thirdoa-api |
| qa-ai-sparring | api-distribution |
| training-manage-api | cool-group |
| user-center-api | api-distribution |
| user-center-api | cmdb-api |
| user-center-api | exam-api |
| user-center-api | evaluation-api |
| user-center-api | thirdoa-api |
| user-center-api | enterprise-manage-api |
| user-center-api | platform-api |
| user-center-api | interaction-api |
| user-center-api | isv-api |

## 按服务查看

- **api-distribution**：被 knowledge-api、qa-ai-sparring、user-center-api 调用（上游多）
- **user-center-api**：被 customize-api 调用；调用 api-distribution、cmdb-api、exam-api、evaluation-api、thirdoa-api、enterprise-manage-api、platform-api、interaction-api、isv-api
- **knowledge-api**：调用 platform-api、isv-api、api-distribution、evaluation-api
- **customize-api**：调用 enterprise-manage-api、training-manage-api、user-center-api
- **thirdoa-api**：被 enterprise-split-api、out-oa-api、user-center-api 调用
- **enterprise-manage-api**：被 customize-api、user-center-api 调用
- 其余见上表。

## 重启前停掉旧进程

```bash
# 默认停掉 8000 端口
bash scripts/stop-server.sh

# 指定端口
PORT=8001 bash scripts/stop-server.sh
# 或
bash scripts/stop-server.sh 8001
```

## 查看最新依赖

```bash
# 先重建图（若仓库有更新）
curl -s -X POST http://127.0.0.1:8000/graph/rebuild

# 获取完整图
curl -s http://127.0.0.1:8000/graph

# 查看某服务的上下游
curl -s "http://127.0.0.1:8000/graph/service/user-center-api"
```
