"""System base class. Systems are updated by the world in explicit order."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


class System:
    """Override ``update``. Access deferred structural changes via
    ``world.commands``; they apply at the end-of-tick sync point."""

    def update(self, world: "World", dt: float) -> None:
        raise NotImplementedError
