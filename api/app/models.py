from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProviderName(str, Enum):
    openai = "openai"
    deepseek = "deepseek"


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


DEFAULT_MODELS: dict[ProviderName, str] = {
    ProviderName.openai: "gpt-5.5",
    ProviderName.deepseek: "deepseek-v4-pro",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class SourceBlock(BaseModel):
    page_number: int
    block_id: str
    source_text: str
    bbox: list[float] = Field(default_factory=list)
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)


class PageImage(BaseModel):
    page_number: int
    width: float
    height: float
    image_name: str
    extraction_method: Literal["text-layer", "ocr"]
    blocks: list[SourceBlock] = Field(default_factory=list)


class GlossaryTerm(BaseModel):
    source: str
    target: str


class TranslatedBlock(BaseModel):
    page_number: int
    block_id: str
    source_text: str
    translation: str
    terms: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TranslationDocument(BaseModel):
    job_id: str
    filename: str
    provider: ProviderName
    model: str
    created_at: datetime
    pages: list[PageImage]
    translations: list[TranslatedBlock]
    glossary: list[GlossaryTerm] = Field(default_factory=list)


class JobPublic(BaseModel):
    id: str
    filename: str
    provider: ProviderName
    model: str
    status: JobStatus
    progress: int = 0
    current_step: str = "Queued"
    pages: int = 0
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class JobInternal(JobPublic):
    job_dir: Path
    source_pdf: Path
    preview_html: Path | None = None
    export_pdf: Path | None = None

    model_config = {"arbitrary_types_allowed": True}

    def public(self) -> JobPublic:
        data: dict[str, Any] = self.model_dump(exclude={"job_dir", "source_pdf", "preview_html", "export_pdf"})
        return JobPublic(**data)
