"""A small, fully local Entity Component System core.

No game engine, server, database or external service is required: all
entity, component, system and world state lives in memory (and optionally
in local JSON snapshot files).
"""

from .command_buffer import CommandBuffer
from .entity import Entity
from .errors import (
    ComponentAlreadyExistsError,
    ComponentNotFoundError,
    ECSError,
    EntityNotAliveError,
    UnknownComponentTypeError,
)
from .system import System
from .world import World, register_component_type

__all__ = [
    "CommandBuffer",
    "ComponentAlreadyExistsError",
    "ComponentNotFoundError",
    "ECSError",
    "Entity",
    "EntityNotAliveError",
    "System",
    "UnknownComponentTypeError",
    "World",
    "register_component_type",
]
