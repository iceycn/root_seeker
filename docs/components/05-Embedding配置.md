# Embedding 配置指南

Embedding 用于将代码块转为向量，供 Qdrant 存储和语义检索。

## 一、配置项说明

在 `config.yaml` 中：

```yaml
embedding:
  kind: "fastembed"                      # fastembed | hash
  model_name: "BAAI/bge-small-en-v1.5"   # 模型名
  cache_dir: "data/embedding_cache"      # 可选，模型缓存目录
```

### 字段说明

| 字段 | 说明 |
|------|------|
| kind | fastembed：使用 FastEmbed 库；hash：简单哈希（不推荐生产） |
| model_name | 模型名称，如 BAAI/bge-small-en-v1.5 |
| cache_dir | 可选，模型下载缓存，国内可设 HF_ENDPOINT=https://hf-mirror.com |

## 二、首次启动

首次启动会下载 Embedding 模型，可能较慢。国内网络可设置：

```bash
export HF_ENDPOINT=https://hf-mirror.com
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## 三、与 Qdrant 的配合

- Embedding 维度由模型决定，Qdrant 会在首次创建 collection 时按维度初始化。
- 更换模型需重建向量索引（删除 collection 或清空后重新 `POST /index/repo/{service_name}`）。

[English](en/05-embedding.md)
