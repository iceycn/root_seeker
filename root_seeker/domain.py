from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class IngestEvent(BaseModel):
    service_name: str
    error_log: str
    query_key: str = Field(default="default_error_context", description="SQL 模板 key，默认使用 default_error_context")
    timestamp: datetime | None = None
    tags: dict[str, Any] = Field(default_factory=dict)
    repo_id: str | None = Field(default=None, description="关联的 git_source_repos.id，用于日志与仓库关联")


class NormalizedErrorEvent(BaseModel):
    service_name: str
    error_log: str
    query_key: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    tags: dict[str, Any] = Field(default_factory=dict)
    repo_id: str | None = Field(default=None, description="关联的 git_source_repos.id")
    correlation_id: str | None = Field(default=None, description="链路追踪 ID，ingest→queue→analyze 贯通")


class LogRecord(BaseModel):
    timestamp: datetime | None = None
    level: str | None = None
    message: str
    fields: dict[str, Any] = Field(default_factory=dict)


class LogBundle(BaseModel):
    query_key: str
    records: list[LogRecord] = Field(default_factory=list)
    raw: Any | None = None


class CandidateRepo(BaseModel):
    service_name: str
    local_dir: str
    git_url: str
    confidence: float = 1.0
    evidence: list[str] = Field(default_factory=list)


class ZoektHit(BaseModel):
    repo: str | None = None
    file_path: str
    line_number: int | None = None
    preview: str | None = None
    score: float | None = None


class EvidenceFile(BaseModel):
    repo_local_dir: str
    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    content: str
    source: str


class EvidencePack(BaseModel):
    level: str
    files: list[EvidenceFile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RelatedService(BaseModel):
    service_name: str
    relation: str = Field(description="upstream|downstream|unknown")
    evidence: list[str] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    analysis_id: str
    service_name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    summary: str
    correlation_id: str | None = Field(default=None, description="链路追踪 ID，与 ingest 时的 correlation_id 一致")
    hypotheses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    evidence: EvidencePack | None = None
    related_services: list[RelatedService] = Field(default_factory=list)
    raw_model_output: str | None = None
    # 业务影响程度：高/中/低/无，用于区分需优先修复 vs 可延后或无需修复
    business_impact: str | None = Field(
        default=None,
        description="业务影响程度：高|中|低|无；如「无：异常被捕获不影响主流程」",
    )
    need_more_evidence: list[str] | None = Field(
        default=None,
        description="证据不足时 LLM 输出的补充检索关键词，供 Orchestrator 触发下一轮",
    )
    diagnosis_summary: dict | None = Field(
        default=None,
        description="v3.0.0 可观测：degraded_modes、truncations、key_evidence_refs",
    )
