"""The ECS World: entity lifecycle, component storage, queries, systems
and snapshots.

Storage model
-------------
* Entities are slots in parallel arrays: ``_generations`` and ``_alive``.
  Destroyed slots are pushed onto a free list and recycled with an
  incremented generation, which invalidates stale handles.
* Components live in ``_components: dict[type, dict[int, component]]`` --
  one sparse map per component type, keyed by entity id. Because the inner
  map is keyed by id, an entity can hold at most one component of a given
  type; duplicate state is impossible by construction.

Query model
-----------
``World.query(*types)`` intersects the per-type storage maps and
*materializes* the matching ``(entity, comp, ...)`` tuples before
returning an iterator. Adding or removing components (or entities) while
iterating therefore never corrupts the ongoing traversal.

Everything is kept in plain memory; snapshots can optionally be written
to / loaded from a local JSON file. No engine, server, database or
network service is involved.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type

from .command_buffer import CommandBuffer
from .entity import Entity
from .errors import (
    ComponentAlreadyExistsError,
    ComponentNotFoundError,
    EntityNotAliveError,
    UnknownComponentTypeError,
)
from .system import System

# Process-wide component registry. Component types are recorded here the
# first time any world sees them, so ``World.from_snapshot`` /
# ``World.load_snapshot`` can resolve types without manual registration
# (as long as the component classes have been imported).
_GLOBAL_COMPONENT_TYPES: Dict[str, type] = {}


def register_component_type(component_type: type, name: Optional[str] = None) -> type:
    """Register a component type globally; usable as a decorator."""
    _GLOBAL_COMPONENT_TYPES[name or component_type.__name__] = component_type
    return component_type


class World:
    """Container for all entity / component / system state."""

    def __init__(self) -> None:
        self._generations: List[int] = []
        self._alive: List[bool] = []
        self._free: List[int] = []
        self._components: Dict[type, Dict[int, Any]] = {}
        self._systems: List[System] = []
        # name <-> type registry used for snapshot (de)serialization.
        self._component_names: Dict[type, str] = {}
        self._component_types: Dict[str, type] = {}

    # ------------------------------------------------------------------
    # component type registry (needed for snapshots)
    # ------------------------------------------------------------------

    def register_component(self, component_type: type, name: Optional[str] = None) -> None:
        """Register a component type so it can be serialized in snapshots."""
        name = name or component_type.__name__
        self._component_names[component_type] = name
        self._component_types[name] = component_type
        _GLOBAL_COMPONENT_TYPES.setdefault(name, component_type)

    def _name_for(self, component_type: type) -> str:
        if component_type not in self._component_names:
            self.register_component(component_type)
        return self._component_names[component_type]

    # ------------------------------------------------------------------
    # entity lifecycle
    # ------------------------------------------------------------------

    def create_entity(self) -> Entity:
        """Create a new entity, recycling a destroyed slot if available."""
        if self._free:
            slot = self._free.pop()
            self._alive[slot] = True
            return Entity(slot, self._generations[slot])
        slot = len(self._generations)
        self._generations.append(0)
        self._alive.append(True)
        return Entity(slot, 0)

    def destroy_entity(self, entity: Entity) -> None:
        """Destroy an entity and drop all of its components."""
        self._check_alive(entity)
        slot = entity.id
        self._alive[slot] = False
        self._generations[slot] += 1
        self._free.append(slot)
        for storage in self._components.values():
            storage.pop(slot, None)

    def is_alive(self, entity: Entity) -> bool:
        """True only if ``entity`` refers to a currently living entity."""
        return (
            0 <= entity.id < len(self._generations)
            and self._alive[entity.id]
            and self._generations[entity.id] == entity.generation
        )

    def entities(self) -> List[Entity]:
        """Snapshot list of all currently alive entities (id order)."""
        return [
            Entity(slot, self._generations[slot])
            for slot in range(len(self._generations))
            if self._alive[slot]
        ]

    def _check_alive(self, entity: Entity) -> None:
        if not self.is_alive(entity):
            raise EntityNotAliveError(
                f"{entity!r} is not alive in this world (stale or destroyed handle)"
            )

    # ------------------------------------------------------------------
    # component operations
    # ------------------------------------------------------------------

    def add_component(self, entity: Entity, component: Any) -> None:
        """Attach ``component``. Fails if the type is already present."""
        self._check_alive(entity)
        storage = self._components.setdefault(type(component), {})
        if entity.id in storage:
            raise ComponentAlreadyExistsError(
                f"{entity!r} already has {type(component).__name__}; "
                "use set_component() to replace it"
            )
        storage[entity.id] = component

    def set_component(self, entity: Entity, component: Any) -> None:
        """Attach or replace ``component`` (upsert)."""
        self._check_alive(entity)
        self._components.setdefault(type(component), {})[entity.id] = component

    def get_component(self, entity: Entity, component_type: Type) -> Any:
        """Return the component of ``component_type`` (raises if missing)."""
        self._check_alive(entity)
        storage = self._components.get(component_type, {})
        if entity.id not in storage:
            raise ComponentNotFoundError(
                f"{entity!r} has no component {component_type.__name__}"
            )
        return storage[entity.id]

    def try_get(self, entity: Entity, component_type: Type) -> Optional[Any]:
        """Return the component or ``None`` if the entity lacks it."""
        self._check_alive(entity)
        return self._components.get(component_type, {}).get(entity.id)

    def has_component(self, entity: Entity, component_type: Type) -> bool:
        self._check_alive(entity)
        return entity.id in self._components.get(component_type, {})

    def remove_component(self, entity: Entity, component_type: Type) -> None:
        """Detach a component (raises if missing)."""
        self._check_alive(entity)
        storage = self._components.get(component_type, {})
        if entity.id not in storage:
            raise ComponentNotFoundError(
                f"{entity!r} has no component {component_type.__name__}"
            )
        del storage[entity.id]

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    def query(self, *component_types: Type) -> Iterator[Tuple]:
        """Iterate ``(entity, comp1, comp2, ...)`` for entities having all
        of ``component_types``.

        The result set is materialized up front, so structural changes
        made while iterating do not affect the ongoing traversal.
        """
        if not component_types:
            raise ValueError("query() requires at least one component type")
        storages = []
        for ctype in component_types:
            storage = self._components.get(ctype)
            if storage is None:
                return iter(())  # one type has no instances at all
            storages.append(storage)
        # Intersect starting from the smallest storage for efficiency.
        smallest = min(storages, key=len)
        rows: List[Tuple] = []
        for slot in smallest:
            if not self._alive[slot]:
                continue
            comps = []
            for storage in storages:
                if slot not in storage:
                    break
                comps.append(storage[slot])
            else:
                entity = Entity(slot, self._generations[slot])
                rows.append((entity, *comps))
        return iter(rows)

    # ------------------------------------------------------------------
    # systems
    # ------------------------------------------------------------------

    def add_system(self, system: System) -> System:
        """Append a system; systems run in registration order."""
        self._systems.append(system)
        return system

    def step(self, dt: float = 1.0) -> None:
        """Run every system once, in registration order."""
        for system in list(self._systems):
            system.update(self, dt)

    def flush(self, command_buffer: CommandBuffer) -> List[Entity]:
        """Execute a command buffer against this world (sync point)."""
        return command_buffer.execute(self)

    # ------------------------------------------------------------------
    # snapshots
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Capture the full world state as a plain (JSON-able) dict."""
        components: Dict[str, Dict[str, Any]] = {}
        for ctype, storage in self._components.items():
            name = self._name_for(ctype)
            components[name] = {
                str(slot): copy.deepcopy(vars(comp)) for slot, comp in storage.items()
            }
        return {
            "generations": list(self._generations),
            "alive": list(self._alive),
            "free": list(self._free),
            "components": components,
        }

    def restore(self, snapshot: Dict[str, Any]) -> None:
        """Replace the world's state with a previously captured snapshot."""
        self._generations = list(snapshot["generations"])
        self._alive = list(snapshot["alive"])
        self._free = list(snapshot["free"])
        self._components = {}
        for name, entries in snapshot["components"].items():
            ctype = self._component_types.get(name) or _GLOBAL_COMPONENT_TYPES.get(name)
            if ctype is None:
                raise UnknownComponentTypeError(
                    f"component type {name!r} is not registered; "
                    "call register_component() before restore()"
                )
            self._components[ctype] = {
                int(slot): ctype(**copy.deepcopy(data))
                for slot, data in entries.items()
            }

    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Any]) -> "World":
        world = cls()
        world.restore(snapshot)
        return world

    def save_snapshot(self, path: str | Path) -> None:
        """Write a snapshot to a local JSON file."""
        Path(path).write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")

    @classmethod
    def load_snapshot(cls, path: str | Path) -> "World":
        """Load a world from a local JSON snapshot file."""
        return cls.from_snapshot(json.loads(Path(path).read_text(encoding="utf-8")))
