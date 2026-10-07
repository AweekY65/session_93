"""ECS-specific exceptions."""


class ECSError(Exception):
    """Base class for all ECS errors."""


class EntityNotAliveError(ECSError):
    """Raised when operating on a destroyed or stale entity handle."""


class ComponentAlreadyExistsError(ECSError):
    """Raised when adding a component type the entity already has."""


class ComponentNotFoundError(ECSError):
    """Raised when reading/removing a component the entity does not have."""
