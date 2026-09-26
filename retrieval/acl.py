from __future__ import annotations

from config.settings import ROLE_COLLECTIONS
from models import SearchHit


def allowed_collections(role: str) -> set[str]:
    return ROLE_COLLECTIONS.get(role.lower().strip(), set())


def is_permitted(chunk: dict, role: str) -> bool:
    return chunk.get("collection") in allowed_collections(role)


def partition_hits(hits: list[SearchHit], chunks: list[dict], role: str) -> tuple[list[SearchHit], list[SearchHit]]:
    permitted: list[SearchHit] = []
    withheld: list[SearchHit] = []
    for hit in hits:
        (permitted if is_permitted(chunks[hit.idx], role) else withheld).append(hit)
    return permitted, withheld
