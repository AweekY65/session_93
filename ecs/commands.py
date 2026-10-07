"""Command buffer: defer structural world mutations to a safe sync point."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, List, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from .entity import Entity
    from .world import World


class CommandBuffer:
    """Records structural mutations and replays them on flush.

    Systems may freely record commands while a query iteration is in
    progress; nothing is applied until ``world.flush_commands()`` runs at
    the end of the update tick (the sync point).
    """

    def __init__(self, world: "World") -> None:
        self._world = world
        self._ops: List[Tuple[Callable[..., Any], tuple]] = []

    def __len__(self) -> int:
        return len(self._ops)

    def _record(self, fn: Callable[..., Any], *args: Any) -> None:
        self._ops.append((fn, args))

    # -- structural operations ------------------------------------------------

    def create_entity(self) -> None:
        self._record(self._world.create_entity)

    def destroy_entity(self, entity: "Entity") -> None:
        self._record(self._world.destroy_entity, entity)

    def add_component(self, entity: "Entity", component: Any) -> None:
        self._record(self._world.add_component, entity, component)

    def remove_component(self, entity: "Entity", component_type: type) -> None:
        self._record(self._world.remove_component, entity, component_type)

    def set_component(self, entity: "Entity", component: Any) -> None:
        self._record(self._world.set_component, entity, component)

    # -- execution ------------------------------------------------------------

    def flush(self) -> None:
        """Apply all recorded commands in order, then clear the buffer."""
        ops, self._ops = self._ops, []
        for fn, args in ops:
            fn(*args)

    def clear(self) -> None:
        self._ops.clear()
