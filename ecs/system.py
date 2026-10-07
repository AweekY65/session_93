"""System base class.

Systems hold the behaviour of the ECS. They are registered on a
:class:`~ecs.world.World` in an explicit order and are executed in exactly
that order on every :meth:`~ecs.world.World.step`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


class System:
    """Override :meth:`update` to implement per-step behaviour."""

    def update(self, world: "World", dt: float) -> None:
        raise NotImplementedError
