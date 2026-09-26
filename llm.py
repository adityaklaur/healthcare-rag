"""Legacy compatibility note.

Grounded generation now lives in `generation/generator.py` and is invoked only
for ANSWER / ANSWER_WITH_WARNING decisions by `pipeline.py`.
"""
from generation.generator import generate_grounded

__all__ = ["generate_grounded"]
