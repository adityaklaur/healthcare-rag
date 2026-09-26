"""Legacy compatibility note.

The Trust Gate was refactored to the architecture-aligned `trust_engine/` package.
Use `pipeline.answer_query(...)` for end-to-end execution.
"""
from pipeline import answer_query

__all__ = ["answer_query"]
