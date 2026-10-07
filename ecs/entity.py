"""Entity handle: a stable, generational identifier.

An Entity is a lightweight value object composed of an ``id`` (slot index)
and a ``generation``. When an entity is destroyed its slot may be reused by
a later entity, but the generation is incremented, so stale handles holding
the old generation can never accidentally refer to the new entity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Entity:
    """Opaque handle to an entity living in a :class:`~ecs.world.World`."""

    id: int
    generation: int

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Entity(id={self.id}, gen={self.generation})"
