"""Deferred structural modifications.

A :class:`CommandBuffer` records structural changes (entity creation /
destruction, component add / remove) without applying them immediately.
The recorded commands are replayed on the world at an explicit
synchronization point via :meth:`CommandBuffer.execute` (or
:meth:`ecs.world.World.flush`), which makes it safe to queue structural
changes from inside systems while a query iteration is in progress.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, List, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from .entity import Entity
    from .world import World


class CommandBuffer:
    """An ordered queue of deferred world mutations."""

    def __init__(self) -> None:
        self._commands: List[Tuple[str, tuple]] = []

    def __len__(self) -> int:
        return len(self._commands)

    @property
    def pending(self) -> bool:
        return bool(self._commands)

    # -- recording API -------------------------------------------------

    def create_entity(self) -> None:
        """Record creation of a new (empty) entity."""
        self._commands.append(("create_entity", ()))

    def destroy_entity(self, entity: "Entity") -> None:
        self._commands.append(("destroy_entity", (entity,)))

    def add_component(self, entity: "Entity", component: Any) -> None:
        self._commands.append(("add_component", (entity, component)))

    def set_component(self, entity: "Entity", component: Any) -> None:
        self._commands.append(("set_component", (entity, component)))

    def remove_component(self, entity: "Entity", component_type: type) -> None:
        self._commands.append(("remove_component", (entity, component_type)))

    # -- playback ------------------------------------------------------

    def execute(self, world: "World") -> List["Entity"]:
        """Replay all recorded commands against ``world`` in order.

        Returns the entities created by ``create_entity`` commands, in the
        order the commands were recorded. The buffer is cleared afterwards.
        """
        created: List[Entity] = []
        dispatch: dict[str, Callable[[tuple], None]] = {
            "create_entity": lambda args: created.append(world.create_entity()),
            "destroy_entity": lambda args: world.destroy_entity(args[0]),
            "add_component": lambda args: world.add_component(args[0], args[1]),
            "set_component": lambda args: world.set_component(args[0], args[1]),
            "remove_component": lambda args: world.remove_component(
                args[0], args[1]
            ),
        }
        commands, self._commands = self._commands, []
        for name, args in commands:
            dispatch[name](args)
        return created

    def clear(self) -> None:
        """Drop all recorded commands without executing them."""
        self._commands.clear()
