# 文档整合索引

本文档将项目内所有文档串联，便于新人或运维快速找到对应说明。

## 1. 使用与配置（面向日常使用）

| 文档 | 说明 |
|------|------|
| [README.md](../README.md) | 快速开始、Webhook 示例、常用接口、鉴权、仓库接入流程 |
| [docs/components/](components/) | **组件配置傻瓜指南**：Zoekt、Qdrant、SLS、LLM、Embedding、Repos、通知、数据存储，每组件单页 |

## 2. 方案与设计（面向理解与扩展）

| 文档 | 说明 |
|------|------|
| [docs/DESIGN_AND_REQUIREMENTS.md](DESIGN_AND_REQUIREMENTS.md) | **设计与需求总览**：背景、要求、选型、补充项与当前实现对应；含项目结构/文档/优化/部署检查结论 |
| [.trae/documents/公司级AI错误分析与代码检索工具方案.md](../.trae/documents/公司级AI错误分析与代码检索工具方案.md) | 已确认方案：数据流、模块化架构、L3 证据包、3 分钟 SLA、交付拆解 |
| [.trae/documents/公司级AI自动代码分析工具方案.md](../.trae/documents/公司级AI自动代码分析工具方案.md) | 目标与边界、总体架构、设计模式、开源选型、数据模型、实施步骤与存疑点 |

## 3. 项目与部署（面向开发与运维）

| 文档 | 说明 |
|------|------|
| [docs/PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | 项目结构说明与检查结论 |
| [docs/OPTIMIZATION_CHECKLIST.md](OPTIMIZATION_CHECKLIST.md) | 当前优化建议清单（P0～P3，已标记完成项） |
| [docs/IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | **实现状态总结**：需求对照、P0/P1/P2/P3 完成情况、新增功能、配置项汇总 |
| [docs/LLM_INTERACTION.md](LLM_INTERACTION.md) | **LLM 交互原理**：系统与大模型（DeepSeek/豆包）的交互流程、Prompt 构建、API 调用、错误处理详解 |
| [docs/LLM_MULTI_TURN_OPTIMIZATION.md](LLM_MULTI_TURN_OPTIMIZATION.md) | **LLM 多轮对话优化方案**：参考 Cursor/Trae 的多轮对话模式，设计分阶段分析、Self-Refine 迭代优化等方案 |
| [docs/LLM_MULTI_TURN_IMPLEMENTATION.md](LLM_MULTI_TURN_IMPLEMENTATION.md) | **LLM 多轮对话实现总结**：三套多轮对话机制的实现细节、使用方法、配置说明 |
| [docs/LOG_CHAIN_ENRICHMENT.md](LOG_CHAIN_ENRICHMENT.md) | **日志链自动读取功能**：使用 LLM 智能提取 trace_id/request_id，自动查询调用链日志 |
| [docs/CONFIG_CHECKLIST.md](CONFIG_CHECKLIST.md) | 配置缺项说明与填写方式 |
| [docs/deploy/00-overview.md](deploy/00-overview.md) | 部署总览与依赖关系 |
| [docs/deploy/01-zoekt.md](deploy/01-zoekt.md) | Zoekt 傻瓜部署 |
| [docs/deploy/02-qdrant.md](deploy/02-qdrant.md) | Qdrant 傻瓜部署 |
| [docs/deploy/03-RootSeeker.md](deploy/03-RootSeeker.md) | RootSeeker 应用傻瓜部署 |
| [docs/deploy/04-aliyun-sls.md](deploy/04-aliyun-sls.md) | 阿里云 SLS 配置与打通 |
| [docs/deploy/05-notifiers.md](deploy/05-notifiers.md) | 企业微信 / 钉钉配置 |

## 4. 文档是否已整合好？

- **已整合**：README 负责「怎么用」；DESIGN_AND_REQUIREMENTS 与 `.trae` 方案负责「为什么这样设计、要求与实现对应」；`docs/` 负责「项目长什么样」「还要改什么」「各组件怎么部署」。
- README 末尾「更多文档」已指向本文档，便于从 README 一步跳到部署或方案。

## 5. 项目检查结论（简要）

| 检查项 | 结论 |
|--------|------|
| **项目结构是否 OK** | ✅ 分层清晰，高内聚低耦合，可扩展与设计模式已落地；见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)、[DESIGN_AND_REQUIREMENTS.md](DESIGN_AND_REQUIREMENTS.md) 第五节。 |
| **文档是否已整合好** | ✅ 使用/方案/项目/部署四类文档齐全，本文档为索引；设计与需求已统一整理到 DESIGN_AND_REQUIREMENTS。 |
| **目前还需要哪些优化** | 见 [OPTIMIZATION_CHECKLIST.md](OPTIMIZATION_CHECKLIST.md)、[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)：✅ P0/P1 已完成；P2（脱敏、白名单、多 LLM、语言扩展）→ P3（并发、增量索引、审计轮转）。 |
| **各组件傻瓜部署是否完善** | ✅ deploy/00～05 覆盖总览、Zoekt、Qdrant、RootSeeker、阿里云 SLS、企业微信/钉钉；顺序与依赖见 [00-overview.md](deploy/00-overview.md)。 |
