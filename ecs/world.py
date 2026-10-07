"""World: entity lifecycle, component storage, queries, systems, snapshots.

Everything lives in local memory; snapshots can optionally be written to a
local JSON file. No engine, server, database or external service is used.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Type

from .commands import CommandBuffer
from .entity import Entity
from .errors import (
    ComponentAlreadyExistsError,
    ComponentNotFoundError,
    EntityNotAliveError,
)


class World:
    def __init__(self) -> None:
        # Entity lifecycle state. Index i is alive iff i in _alive.
        self._generations: List[int] = []
        self._alive: Set[int] = set()
        self._free_indices: List[int] = []

        # Component storage: component type -> {entity index -> component}.
        self._storages: Dict[type, Dict[int, Any]] = {}

        # Systems: (priority, insertion counter, system). Lower priority
        # runs first; ties break by insertion order for determinism.
        self._systems: List[Tuple[int, int, Any]] = []
        self._system_counter = 0

        self.commands = CommandBuffer(self)

    # ------------------------------------------------------------------ entity

    def create_entity(self) -> Entity:
        """Create a new entity, recycling a freed index when available."""
        if self._free_indices:
            index = self._free_indices.pop()
        else:
            index = len(self._generations)
            self._generations.append(0)
        self._alive.add(index)
        return Entity(index=index, generation=self._generations[index])

    def destroy_entity(self, entity: Entity) -> None:
        """Destroy an entity and all of its components.

        The generation is bumped so any stale handle to this index becomes
        permanently invalid, even after the index is reused.
        """
        self._check_alive(entity)
        index = entity.index
        for storage in self._storages.values():
            storage.pop(index, None)
        self._alive.discard(index)
        self._generations[index] += 1
        self._free_indices.append(index)

    def is_alive(self, entity: Entity) -> bool:
        return (
            0 <= entity.index < len(self._generations)
            and self._generations[entity.index] == entity.generation
            and entity.index in self._alive
        )

    def _check_alive(self, entity: Entity) -> None:
        if not self.is_alive(entity):
            raise EntityNotAliveError(f"entity is not alive: {entity!r}")

    # --------------------------------------------------------------- component

    def add_component(self, entity: Entity, component: Any) -> None:
        """Attach a component. Raises if the entity already has this type,
        so an entity can never hold ambiguous duplicate state for one type."""
        self._check_alive(entity)
        storage = self._storages.setdefault(type(component), {})
        if entity.index in storage:
            raise ComponentAlreadyExistsError(
                f"{entity!r} already has {type(component).__name__}"
            )
        storage[entity.index] = component

    def set_component(self, entity: Entity, component: Any) -> None:
        """Insert or replace a component (upsert)."""
        self._check_alive(entity)
        self._storages.setdefault(type(component), {})[entity.index] = component

    def get_component(self, entity: Entity, component_type: Type) -> Any:
        self._check_alive(entity)
        storage = self._storages.get(component_type, {})
        if entity.index not in storage:
            raise ComponentNotFoundError(
                f"{entity!r} has no {component_type.__name__}"
            )
        return storage[entity.index]

    def has_component(self, entity: Entity, component_type: Type) -> bool:
        if not self.is_alive(entity):
            return False
        return entity.index in self._storages.get(component_type, {})

    def remove_component(self, entity: Entity, component_type: Type) -> None:
        self._check_alive(entity)
        storage = self._storages.get(component_type, {})
        if entity.index not in storage:
            raise ComponentNotFoundError(
                f"{entity!r} has no {component_type.__name__}"
            )
        del storage[entity.index]

    # ------------------------------------------------------------------- query

    def query(self, *component_types: Type) -> Iterator[Tuple[Entity, ...]]:
        """Yield (entity, comp1, comp2, ...) for entities having ALL types.

        The matching entity list is materialized when iteration starts, so
        structural changes during iteration never corrupt the traversal:
        - entities created or gaining components mid-iteration are not visited;
        - an entity whose required component was removed mid-iteration is
          skipped when reached;
        - destroyed entities are skipped.
        """
        if not component_types:
            return
        storages = [self._storages.get(t, {}) for t in component_types]
        smallest = min(storages, key=len)
        matches = [
            idx
            for idx in list(smallest.keys())
            if idx in self._alive and all(idx in s for s in storages)
        ]
        matches.sort()
        for index in matches:
            if index not in self._alive:
                continue
            if not all(index in s for s in storages):
                continue
            entity = Entity(index=index, generation=self._generations[index])
            yield (entity, *(s[index] for s in storages))

    # ------------------------------------------------------------------ system

    def add_system(self, system: Any, priority: int = 0) -> None:
        """Register a system. Systems run in ascending priority order;
        equal priorities run in registration order."""
        self._systems.append((priority, self._system_counter, system))
        self._system_counter += 1
        self._systems.sort(key=lambda entry: (entry[0], entry[1]))

    def update(self, dt: float = 0.0) -> None:
        """Run every system in order, then flush the command buffer at the
        sync point so deferred structural changes take effect."""
        for _, _, system in list(self._systems):
            system.update(self, dt)
        self.commands.flush()

    # ---------------------------------------------------------------- snapshot

    def snapshot(self) -> Dict[str, Any]:
        """Capture a deep in-memory snapshot of the full world state."""
        return {
            "generations": copy.deepcopy(self._generations),
            "alive": sorted(self._alive),
            "free_indices": list(self._free_indices),
            "components": {
                type_.__name__: {
                    str(index): copy.deepcopy(component)
                    for index, component in storage.items()
                }
                for type_, storage in self._storages.items()
            },
        }

    def restore(self, snapshot: Dict[str, Any], component_types: Dict[str, type]) -> None:
        """Restore world state from a snapshot produced by ``snapshot``.

        ``component_types`` maps component class name -> class, used to
        rebuild component instances. After restore, entity handles, component
        state and query results match the moment the snapshot was taken.
        """
        self._generations = list(snapshot["generations"])
        self._alive = set(snapshot["alive"])
        self._free_indices = list(snapshot["free_indices"])
        self._storages = {}
        for type_name, entries in snapshot["components"].items():
            cls = component_types[type_name]
            storage: Dict[int, Any] = {}
            for index_str, data in entries.items():
                storage[int(index_str)] = self._build_component(cls, data)
            self._storages[cls] = storage

    # ------------------------------------------------------- snapshot file I/O

    def save_snapshot(self, path: str) -> None:
        """Serialize a snapshot to a local JSON file."""
        data = self.snapshot()
        data["components"] = {
            type_name: {
                index: self._component_to_dict(component)
                for index, component in entries.items()
            }
            for type_name, entries in data["components"].items()
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    def load_snapshot(self, path: str, component_types: Dict[str, type]) -> None:
        """Restore world state from a local JSON snapshot file."""
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.restore(data, component_types)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _component_to_dict(component: Any) -> Dict[str, Any]:
        if is_dataclass(component):
            return asdict(component)
        return dict(vars(component))

    @staticmethod
    def _build_component(cls: type, data: Any) -> Any:
        if isinstance(data, cls):
            return copy.deepcopy(data)
        return cls(**data)
