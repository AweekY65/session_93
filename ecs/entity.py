"""Entity handle: stable ID with generation-based reuse protection."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entity:
    """Opaque handle to an entity.

    An Entity is a (index, generation) pair. The index may be recycled after
    destruction, but the generation is bumped on every destroy, so a stale
    handle captured before destruction will never resolve to a new entity
    that happens to reuse the same index.
    """

    index: int
    generation: int

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Entity(index={self.index}, gen={self.generation})"
