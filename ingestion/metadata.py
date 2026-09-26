from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from config.settings import MANIFEST_FILE, DATA_DIR


class DocumentMetadata(BaseModel):
    file: str
    document_id: str
    title: str
    document_type: str
    version: str = "1"
    status: Literal["DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED"] = "ACTIVE"
    effective_date: date | None = None
    review_due: date | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    authority_level: int = Field(default=3, ge=1, le=5)
    collection: str
    population: list[str] = Field(default_factory=lambda: ["all"])
    owner_contact: str = "Document owner"
    synthetic: bool = False
    pii_test: bool = False
    notes: str = ""

    @field_validator("population", mode="before")
    @classmethod
    def normalize_population(cls, value):
        if value is None:
            return ["all"]
        if isinstance(value, str):
            return [value.lower()]
        return [str(v).lower() for v in value]

    @property
    def version_id(self) -> str:
        return f"{self.document_id}@{self.version}"

    @property
    def path(self) -> Path:
        return DATA_DIR / self.file


class Manifest(BaseModel):
    documents: list[DocumentMetadata]


def load_manifest(path: Path = MANIFEST_FILE) -> Manifest:
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(raw, list):
        raw = {"documents": raw}
    return Manifest.model_validate(raw)
