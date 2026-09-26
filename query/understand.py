from __future__ import annotations

import re

from models import QueryContext

TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*", re.I)

PEDIATRIC = re.compile(r"\b(pediatric|paediatric|child|children|infant|neonate|neonatal|adolescent|teen|\d{1,2}[ -]?year[ -]?old)\b", re.I)
PREGNANCY = re.compile(r"\b(pregnant|pregnancy|gestation|gestational)\b", re.I)
ADULT = re.compile(r"\b(adult|adults|over 18|18 years? and over)\b", re.I)

# Populations that general ("all") documents must mention explicitly to count as evidence.
SPECIFIC_POPULATION_TERMS = {"pediatric": PEDIATRIC, "pregnancy": PREGNANCY}

EGFR = re.compile(r"\be\s*gfr\s*(?:(?:of|=|is|at)\s*)?(?:(below|under|less than|above|over|at least)\s*)?(\d+(?:\.\d+)?)", re.I)
CRCL = re.compile(r"\b(?:crcl|creatinine clearance)\s*(?:(?:of|=|is|at)\s*)?(?:(below|under|less than|above|over|at least)\s*)?(\d+(?:\.\d+)?)", re.I)

IDENTIFIER_REQUEST = re.compile(
    r"\b(?:what|give|show|tell|find|provide|reveal|lookup|look up|identify)\b.{0,35}"
    r"\b(?:mrn|medical record number|date of birth|dob|phone(?: number)?|email(?: address)?|"
    r"member id|policy id|insurance id|patient identifier)\b",
    re.I | re.S,
)
HISTORICAL = re.compile(r"\b(historical|previous|old version|superseded|retired|what did .* say|as of \d{4})\b", re.I)
EXACT_ID = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b")


def normalize(text: str) -> str:
    return " ".join((text or "").strip().split())


def understand_query(question: str, force_historical: bool = False) -> QueryContext:
    normalized = normalize(question)
    population = None
    if PEDIATRIC.search(normalized):
        population = "pediatric"
    elif PREGNANCY.search(normalized):
        population = "pregnancy"
    elif ADULT.search(normalized):
        population = "adult"

    renal_metric = None
    renal_value = None
    def _value(match):
        qualifier = (match.group(1) or "").lower()
        value = float(match.group(2))
        if qualifier in {"below", "under", "less than"}:
            value -= 0.01
        elif qualifier in {"above", "over"}:
            value += 0.01
        return value

    m = EGFR.search(normalized)
    if m:
        renal_metric, renal_value = "egfr", _value(m)
    else:
        m = CRCL.search(normalized)
        if m:
            renal_metric, renal_value = "crcl", _value(m)

    return QueryContext(
        original=question,
        normalized=normalized,
        tokens=[t.lower() for t in TOKEN.findall(normalized)],
        population=population,
        renal_metric=renal_metric,
        renal_value=renal_value,
        requests_identifier=bool(IDENTIFIER_REQUEST.search(normalized)),
        historical_intent=force_historical or bool(HISTORICAL.search(normalized)),
        exact_ids=EXACT_ID.findall(normalized),
    )
