"""Exception types raised by the ECS core."""


class ECSError(Exception):
    """Base class for all ECS errors."""


class EntityNotAliveError(ECSError):
    """Raised when operating on a destroyed or stale entity handle."""


class ComponentNotFoundError(ECSError):
    """Raised when reading/removing a component the entity does not have."""


class ComponentAlreadyExistsError(ECSError):
    """Raised when adding a component type the entity already has."""


class UnknownComponentTypeError(ECSError):
    """Raised when (de)serializing a component type that is not registered."""
