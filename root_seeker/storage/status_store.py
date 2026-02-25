from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field


class AnalysisStatus(BaseModel):
    analysis_id: str
    status: str = Field(description="pending|running|completed|failed")
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    error: str | None = None


@dataclass(frozen=True)
class StatusStore:
    base_dir: Path

    def __post_init__(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, analysis_id: str) -> Path:
        # 安全验证：确保 analysis_id 不包含路径遍历字符
        if not analysis_id or "/" in analysis_id or ".." in analysis_id or "\\" in analysis_id:
            raise ValueError(f"Invalid analysis_id: {analysis_id}")
        # 只允许字母、数字、连字符和下划线
        if not all(c.isalnum() or c in "-_" for c in analysis_id):
            raise ValueError(f"Invalid analysis_id format: {analysis_id}")
        return self.base_dir / f"{analysis_id}.json"

    def save(self, status: AnalysisStatus) -> None:
        path = self.path_for(status.analysis_id)
        path.write_text(status.model_dump_json(indent=2), encoding="utf-8")

    def load(self, analysis_id: str) -> AnalysisStatus | None:
        path = self.path_for(analysis_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return AnalysisStatus.model_validate(raw)
