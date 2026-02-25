# Embedding Setup

Embedding converts code chunks to vectors for Qdrant.

## Config

In `config.yaml`:

```yaml
embedding:
  kind: "fastembed"
  model_name: "BAAI/bge-small-en-v1.5"
  cache_dir: "data/embedding_cache"   # optional
```

First run downloads the model; for China use `HF_ENDPOINT=https://hf-mirror.com`.

[中文](../05-embedding.md)
