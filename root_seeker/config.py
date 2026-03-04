from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROOT_SEEKER_", extra="ignore")

    config_path: Path = Path("config.yaml")


class RepoConfig(BaseModel):
    service_name: str
    git_url: str
    local_dir: str
    repo_aliases: list[str] = Field(default_factory=list)
    language_hints: list[str] = Field(default_factory=list)
    feature: list[str] = Field(default_factory=list, description="可选特性标签，便于后续按特性过滤或扩展")


class AliyunSlsConfig(BaseModel):
    endpoint: str
    access_key_id: str
    access_key_secret: str
    project: str
    logstore: str
    topic: str | None = None


class EnrichmentConfig(BaseModel):
    time_window_seconds: int = Field(default=300, description="基础日志查询时间窗口（秒）")
    trace_chain_enabled: bool = Field(default=True, description="是否启用调用链日志查询（根据 trace_id/request_id）")
    trace_chain_time_window_seconds: int = Field(default=600, description="调用链查询时间窗口（秒），通常比基础查询更宽")


class SqlTemplateConfig(BaseModel):
    query_key: str
    query: str


class ZoektConfig(BaseModel):
    api_base_url: HttpUrl


class WeComConfig(BaseModel):
    webhook_url: HttpUrl
    secret: str | None = Field(default=None, description="加签密钥，security_mode=sign 时必填（企微群机器人当前主要靠 key 鉴权）")
    security_mode: str = Field(
        default="ip",
        description="安全模式：sign（加签）| keyword（关键词）| ip（IP白名单，无需额外处理）。参考 https://developer.work.weixin.qq.com/document/path/91770",
    )


class DingTalkConfig(BaseModel):
    webhook_url: HttpUrl
    secret: str | None = Field(default=None, description="加签密钥，security_mode=sign 时必填")
    security_mode: str = Field(
        default="sign",
        description="安全模式：sign（加签）| keyword（关键词）| ip（IP白名单，无需额外处理）。参考 https://open.dingtalk.com/document/robots/customize-robot-security-settings",
    )


class LlmProviderConfig(BaseModel):
    """LLM 可替换策略：kind=deepseek 或 doubao；doubao 时 base_url 填完整对话 URL"""
    kind: str = Field(default="deepseek", description="deepseek | doubao")
    base_url: HttpUrl
    api_key: str
    model: str
    timeout_seconds: float = Field(default=90.0, description="LLM API 超时时间（秒），多轮分析建议 90+ 秒")
    temperature: float = Field(default=0.2, description="doubao 等可调，deepseek 默认 0.2")
    max_tokens: int | None = Field(default=None, description="doubao 等可填，不填则不传")


class EmbeddingConfig(BaseModel):
    kind: str = Field(default="fastembed", description="fastembed|hash")
    model_name: str | None = None
    dimension: int | None = None
    cache_dir: str | None = Field(default=None, description="fastembed 模型缓存目录，便于离线复用")


class QdrantStoreConfig(BaseModel):
    url: str = "http://127.0.0.1:6333"
    api_key: str | None = None
    collection: str = "code_chunks"
    timeout: int = Field(default=30, description="Qdrant 请求超时（秒），默认 30，避免 count 等操作超时导致 500")


class GitSourceConfig(BaseModel):
    """Git 仓库发现配置：根据域名+账号密码获取仓库列表，支持文件或 MySQL 存储。"""
    enabled: bool = Field(default=True, description="是否启用")
    repos_base_dir: str = Field(default="data/repos_from_git", description="仓库克隆根目录")
    storage: dict[str, Any] = Field(
        default_factory=lambda: {"type": "file", "file_path": "data/git_source.json"},
        description="存储配置：type=file 时需 file_path；type=mysql 时需 host,port,user,password,database",
    )


class AppConfig(BaseModel):
    data_dir: str = "data"
    audit_dir: str = "data/audit"
    api_keys: list[str] = Field(default_factory=list)
    analysis_workers: int = 2
    llm_concurrency: int = 4
    git_timeout_seconds: int = 180
    analysis_timeout_seconds: int = Field(default=160, description="单次分析任务超时时间（秒），默认 160 秒以保障 3 分钟 SLA")
    log_level: str = Field(default="INFO", description="日志级别：DEBUG、INFO、WARNING、ERROR（默认 INFO）")
    repos: list[RepoConfig] = Field(default_factory=list)

    aliyun_sls: AliyunSlsConfig
    sql_templates: list[SqlTemplateConfig] = Field(default_factory=list)

    zoekt: ZoektConfig | None = None
    wecom: WeComConfig | None = None
    dingtalk: DingTalkConfig | None = None
    notify_console: bool = Field(default=False, description="为 true 时分析完成后将 Markdown 报告打印到控制台")
    report_store_path: str | None = Field(default=None, description="非空时将 Markdown 报告写入该路径（文件）或 SQLite 库路径")
    ingest_source: str = Field(default="aliyun_sls", description="当前错误入口来源：aliyun_sls，后续可扩展 sentry/kafka 等")
    cross_repo_evidence: bool = Field(default=False, description="为 true 时在关联服务对应仓库内做向量检索并合并证据")
    cross_repo_max_services: int = Field(default=2, description="跨仓库证据最多取几个关联服务")
    cross_repo_max_chunks_per_service: int = Field(default=3, description="每个关联服务最多取几条向量片段")
    call_graph_expansion: bool = Field(default=False, description="为 true 时启用方法级调用链展开：从代码片段解析方法调用关系并迭代扩展证据")
    call_graph_max_rounds: int = Field(default=2, description="方法级调用链展开最多迭代几轮")
    call_graph_max_methods_per_round: int = Field(default=5, description="每轮最多找几个方法")
    call_graph_max_total_methods: int = Field(default=15, description="总共最多找几个方法")
    call_graph_use_tree_sitter: bool = Field(default=True, description="使用 Tree-sitter 解析方法调用（更精确），否则用正则")
    call_graph_scan_limit_dirs: list[str] | None = Field(default=None, description="限制扫描目录（如 ['src/main', 'src']），None 表示全仓库")
    call_graph_cache_size: int = Field(default=100, description="方法定位缓存大小（LRU）")

    llm: LlmProviderConfig | None = None
    embedding: EmbeddingConfig | None = None
    qdrant: QdrantStoreConfig | None = None
    git_source: GitSourceConfig | None = None

    evidence_level: str = Field(default="L3", description="L1|L2|L3")
    max_evidence_files: int = 12
    max_evidence_chunks: int = 24
    max_context_chars_total: int = 160_000
    max_context_chars_per_file: int = 24_000

    # 多轮对话配置（默认启用混合模式）
    llm_multi_turn_enabled: bool = Field(default=True, description="是否启用多轮对话")
    llm_multi_turn_mode: str = Field(default="hybrid", description="多轮对话模式：staged（分阶段）| self_refine（自我优化）| hybrid（混合）")
    llm_multi_turn_max_rounds: int = Field(default=3, description="最大轮数")
    llm_multi_turn_enable_self_review: bool = Field(default=True, description="是否启用自我审查（仅 hybrid 模式）")
    llm_multi_turn_staged_round1: bool = Field(default=True, description="分阶段模式：阶段1快速定位")
    llm_multi_turn_staged_round2: bool = Field(default=True, description="分阶段模式：阶段2深入分析")
    llm_multi_turn_staged_round3: bool = Field(default=True, description="分阶段模式：阶段3生成建议")
    llm_multi_turn_self_refine_review_rounds: int = Field(default=1, description="Self-Refine 模式：审查轮数")
    llm_multi_turn_self_refine_improvement_threshold: float = Field(default=0.1, description="Self-Refine 模式：改进阈值（如果改进幅度小于此值，提前终止）")

    # 日志链查询配置
    trace_chain_enabled: bool = Field(default=True, description="是否启用调用链日志查询（使用 LLM 提取 trace_id/request_id）")
    trace_chain_time_window_seconds: int = Field(default=300, description="调用链查询时间窗口（秒），默认5分钟（300秒）")
    max_trace_chain_time_window_seconds: int = Field(default=300, description="调用链查询最大时间窗口（秒），默认5分钟（300秒），超过此值会自动调整")

    # 定时任务配置
    periodic_tasks_enabled: bool = Field(default=False, description="是否启用定时任务功能（总开关），默认 false")
    auto_sync_enabled: bool = Field(default=False, description="是否启用定时仓库同步（git pull），需要 periodic_tasks_enabled=true 才生效")
    auto_sync_interval_seconds: int = Field(default=3600, description="仓库同步间隔（秒），默认1小时（3600秒）")
    auto_index_enabled: bool = Field(default=False, description="是否启用定时向量索引更新（同步完成后自动触发），需要 periodic_tasks_enabled=true 才生效")
    auto_index_after_sync: bool = Field(default=True, description="仓库同步完成后是否自动触发向量索引更新（仅对有变更的仓库），默认 true")
    auto_index_interval_seconds: int = Field(default=7200, description="向量索引更新间隔（秒），默认2小时（7200秒），仅在 auto_index_after_sync=false 时生效")
    auto_sync_concurrency: int = Field(default=8, description="仓库同步并发数，默认8")
    auto_index_concurrency: int = Field(default=1, description="向量索引并发数，默认1（按仓库排队加载，避免一次性加载过多）")
    indexing_queue: str = Field(default="memory", description="索引队列策略：memory（默认内存队列），后续可扩展 redis 等")


@dataclass(frozen=True)
class LoadedConfig:
    settings: Settings
    app: AppConfig


def load_config() -> LoadedConfig:
    """通过 ConfigReader 读取配置，支持 file / database 双模式。"""
    from root_seeker.config_reader import ConfigReader

    settings = Settings()
    raw = ConfigReader(config_path=settings.config_path).read()
    app = AppConfig.model_validate(raw)
    return LoadedConfig(settings=settings, app=app)


def get_config_db(raw: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """获取数据库连接配置。若 raw 为 None 则从 config_path 读取。供 API 等使用。"""
    from root_seeker.config_reader import get_config_db as _get

    return _get(raw)
