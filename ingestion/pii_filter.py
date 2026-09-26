from __future__ import annotations

import re
from typing import Iterable

from config.settings import PII_PLACEHOLDERS

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "MRN": re.compile(r"\bMRN[:#\s]*\d{6,10}\b", re.I),
    "DOB": re.compile(r"\b(?:DOB|date of birth)[:\s]*\d{1,4}[-/]\d{1,2}[-/]\d{1,4}\b", re.I),
    "PHONE": re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?)\d{3}[\s-]?\d{4}\b"),
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    "POLICY": re.compile(r"\b(?:member|policy|insurance)\s*(?:id|no\.?|#)[:\s]*[A-Z0-9-]{6,}\b", re.I),
}


def detect_pii(text: str) -> list[str]:
    return [name for name, pattern in PII_PATTERNS.items() if pattern.search(text or "")]


def mask_pii(text: str) -> tuple[str, list[str]]:
    masked = text or ""
    found: list[str] = []
    for name, pattern in PII_PATTERNS.items():
        if pattern.search(masked):
            found.append(name)
            masked = pattern.sub(PII_PLACEHOLDERS[name], masked)
    return masked, found


def contains_pii(text: str, kinds: Iterable[str] | None = None) -> bool:
    selected = PII_PATTERNS if kinds is None else {k: PII_PATTERNS[k] for k in kinds if k in PII_PATTERNS}
    return any(p.search(text or "") for p in selected.values())
