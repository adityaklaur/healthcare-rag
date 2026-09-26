from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from pydantic import BaseModel, Field


@dataclass
class QueryContext:
    original: str
    normalized: str
    tokens: list[str]
    population: Optional[str] = None
    renal_metric: Optional[str] = None  # egfr | crcl
    renal_value: Optional[float] = None
    requests_identifier: bool = False
    historical_intent: bool = False
    exact_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchHit:
    idx: int
    vector_score: float = 0.0
    bm25_score: float = 0.0
    vector_rank: Optional[int] = None
    bm25_rank: Optional[int] = None
    rrf_score: float = 0.0
    rerank_score: Optional[float] = None


@dataclass
class WithheldSummary:
    doc_count: int = 0
    max_score: Optional[float] = None


@dataclass
class RetrievalResult:
    evidence: list[dict[str, Any]]
    withheld: WithheldSummary
    retrieved_chunk_ids: list[str]
    historical_intent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence,
            "withheld": asdict(self.withheld),
            "retrieved_chunk_ids": self.retrieved_chunk_ids,
            "historical_intent": self.historical_intent,
        }


@dataclass
class RuleResult:
    eligible: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    flags: set[str] = field(default_factory=set)


class JudgeItem(BaseModel):
    id: str
    relevant: bool = True
    population_ok: bool = True


class ConflictPair(BaseModel):
    a: str
    b: str
    topic: str = ""
    summary: str = ""


class JudgeResult(BaseModel):
    items: list[JudgeItem] = Field(default_factory=list)
    sufficient: bool = False
    missing: str = ""
    conflicts: list[ConflictPair] = Field(default_factory=list)
    mode: str = "heuristic"


@dataclass
class Decision:
    state: str
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "reason_codes": self.reason_codes}


class AnswerSentence(BaseModel):
    text: str
    citations: list[str]


class GeneratedAnswer(BaseModel):
    sentences: list[AnswerSentence]
    mode: str = "llm"


@dataclass
class GuardResult:
    passed: bool
    answer: Optional[GeneratedAnswer]
    errors: list[str] = field(default_factory=list)
    pii_masked: bool = False
    retries: int = 0
